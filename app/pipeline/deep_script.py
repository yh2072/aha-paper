"""Default aha-paper editorial workflow: deep science writing, source pages, visual audit."""
import base64
import json
import re
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
from .. import lang, llm
from . import outline
from .figures import _png_bytes

PROFILE='deep-science-v1'
# The narration rate the whole pipeline assumes (see config.MAX_SCRIPT_CHARS).
# Kept as the Chinese figure it has always been; the rate in force is the
# narration profile's -- see app/lang.py.
CHARS_PER_MINUTE=lang.ZH_CHARS_PER_MINUTE
DEFAULT_MINUTES=11
MIN_MINUTES=3
MAX_MINUTES=30


def budget(minutes=None,profile=None):
    """How long the narration may run, for a requested duration in minutes.

    Minutes are the language-independent part: a 11-minute explainer is 11
    minutes in either language. Characters are not -- a minute of English
    narration is three times the len() of a minute of Chinese -- so every
    figure here comes from the profile rather than from a constant.

    With no profile the default reproduces the hand-tuned numbers this pipeline
    shipped with: 11 minutes is 3300 characters, a 2640-4125 band and 8-14
    chapters, so an unspecified duration behaves exactly as before."""
    profile=profile or lang.get(None)
    minutes=DEFAULT_MINUTES if minutes is None else max(MIN_MINUTES,min(MAX_MINUTES,int(minutes)))
    target=profile.budget_chars(minutes)
    low,high=round(target*.8),round(target*1.25)
    # A chapter is one question, about a minute of narration; the band around that
    # has to scale with the duration rather than stop at a fixed ceiling, or a
    # long explainer gets a handful of overlong chapters instead of more of them.
    middle=max(3,round(target/profile.chars_per_chapter))
    chapters_low=max(3,round(middle*.75))
    chapters_high=max(chapters_low+2,round(middle*1.3))
    return {'minutes':minutes,'target':target,'low':low,'high':high,'lang':profile.code,
            'chapters_low':chapters_low,'chapters_high':chapters_high}

# The writer's system prompt now lives with everything else the narration's
# language decides. Kept as a name here because that is what the pipeline and
# its tests have always imported.
PERSONA=lang.ZH_PERSONA




def _canonical(text,profile=None):
    """An absolute difference written as a percentage, put back. Each language
    makes that mistake in its own words -- see Profile.canonical."""
    return (profile or lang.get(None)).canonical(text)


def validate_outline(outline,figs,page_count,plan=None,allowed_pages=None,profile=None):
    """allowed_pages is the mechanical half of a section selection: a chapter may
    cite only pages the chosen sections cover, so the writer cannot wander into
    the rest of the paper however the prompt is read."""
    profile=profile or lang.get((plan or {}).get('lang'))
    plan=plan or budget(profile=profile)
    if not isinstance(outline,dict):raise ValueError('深度文稿响应必须是结构化对象')
    chapters=outline.get('chapters') or outline.get('scenes') or []
    if not plan['chapters_low']<=len(chapters)<=plan['chapters_high']:
        raise ValueError(f"深度内容需要{plan['chapters_low']}–{plan['chapters_high']}章，当前{len(chapters)}章")
    allowed={f['file']:f for f in figs}
    scenes=[]
    for chapter in chapters:
        text=_canonical(str(chapter.get('text','')).strip(),profile)
        if not text:raise ValueError('章节不能缺少正文')
        pages=chapter.get('source_pages') or []
        if not pages or any(not isinstance(n,int) or isinstance(n,bool) or not 1<=n<=page_count for n in pages):
            raise ValueError('每章必须包含真实有效的 PDF 来源页码')
        if allowed_pages is not None:
            stray=sorted(set(pages)-allowed_pages)
            if stray:raise ValueError(f'第{stray[:4]}页不在选定的章节范围内，只能引用所选小节的页码')
        figure=chapter.get('figure') or None
        if figure and figure not in allowed:raise ValueError('章节引用了不存在的论文主图')
        if figure:pages=sorted(set(pages+[allowed[figure]['page']]))
        scenes.append({'text':text,'segment_title':str(chapter.get('segment_title',''))[:40],
            'visual_concept':str(chapter.get('visual_concept',''))[:400],
            'image_prompt':str(chapter.get('visual_concept',''))[:400],
            'source_pages':sorted(set(pages)), 'figure':figure})
    total=sum(len(s['text']) for s in scenes)
    if not plan['low']<=total<=plan['high']:
        raise ValueError(f"深度正文需{plan['low']}–{plan['high']}字（约{plan['minutes']}分钟），当前{total}字")
    if len(allowed)>=3 and len({s['figure'] for s in scenes if s['figure']})<3:
        raise ValueError('深度讲解必须覆盖至少3张关键真实主图')
    return {'title':str(outline.get('title') or profile.default_title)[:40],
        'subtitle':str(outline.get('subtitle') or '')[:80],
        'cover_prompt':str(outline.get('cover_prompt') or 'Scientific discovery and careful reasoning'),
        'scenes':scenes, 'total_chars':total,
        'corrections':outline.get('corrections') or []}


def generate(pdf_path:Path,figs:list,fig_dir:Path,log=print,guidance="",minutes=None,
             section_ids=None,lang_code=None):
    profile=lang.get(lang_code)
    plan=budget(minutes,profile)
    reader=PdfReader(str(pdf_path))
    pages=[p.extract_text() or '' for p in reader.pages]
    whole='\n\n'.join(f'{profile.page_label(i+1)}\n{text}'for i,text in enumerate(pages))
    # The DOI lives on the first page, which a section selection may well exclude.
    doi_match=re.search(r'10\.\d{4,9}/[A-Za-z0-9._;()/:-]+',whole[:40000])
    doi=doi_match.group(0).rstrip('.;,') if doi_match else ''
    entries=outline.extract(pdf_path) if section_ids else []
    picked=outline.chosen(entries,section_ids)
    allowed=outline.pages_for(entries,section_ids) if picked else None
    if allowed:
        # A figure outside the chosen sections illustrates something this explainer
        # is not about, so it is dropped rather than offered.
        figs=[f for f in figs if f.get('page') in allowed]
        allowed=allowed|{f['page'] for f in figs if f.get('page')}
        paper='\n\n'.join(f'{profile.page_label(i+1)}\n{text}'for i,text in enumerate(pages)
                          if (i+1) in allowed)[:100000]
        log(f'  只讲选定的 {len(picked)} 个小节：{len(allowed)} 页，{len(figs)} 张主图')
    else:
        paper=whole[:100000]
    fig_data=[{k:f.get(k) for k in ('file','page','caption','walkthrough')}for f in figs]
    instructions=profile.instructions(plan,len(figs))
    if picked:
        instructions += '\n' + profile.section_scope(outline.describe(picked))
    if guidance.strip():
        # The user's own words, in whatever language they wrote them. The frame
        # around them is the narration's language, because it is an instruction
        # to the writer; what it frames is quoted as typed.
        instructions += '\n' + profile.user_focus(guidance[:2000])
    content=[{'type':'text','text':instructions+'\n'+profile.paper_header+'\n'+paper
              +'\n'+profile.figures_header+'\n'+json.dumps(fig_data,ensure_ascii=False)}]
    for f in figs:
        content.append({'type':'text','text':profile.figure_note(f['file'],f['page'])})
        content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+
            base64.b64encode(_png_bytes(Image.open(fig_dir/f['file']),1600)).decode()}})
    messages=[{'role':'system','content':profile.persona},{'role':'user','content':content}]
    log(f'  深度科普：规划约{plan["target"]}字、{plan["chapters_low"]}–{plan["chapters_high"]}章（口播约{plan["minutes"]}分钟）')
    draft=llm.chat_json(messages,temperature=.45)
    audit_prompt=profile.audit(plan)
    log('  深度科普：独立核对方法、数据、主图与来源页码')
    reviewed=llm.chat_json(messages+[{'role':'assistant','content':json.dumps(draft,ensure_ascii=False)},
        {'role':'user','content':audit_prompt}],temperature=.2)
    for attempt in range(2):
        try:
            board=validate_outline(reviewed,figs,len(pages),plan=plan,
                                   allowed_pages=allowed,profile=profile);break
        except ValueError as error:
            if attempt:raise
            log('  深度文稿结构修正: '+str(error))
            reviewed=llm.chat_json(messages+[{'role':'assistant','content':json.dumps(reviewed,ensure_ascii=False)},
                {'role':'user','content':profile.repair(error)}],temperature=.2)
    board['doi']=doi
    board['page_count']=len(pages)
    board['lang']=profile.code
    for change in board['corrections']:log('  深度核对: '+str(change))
    log(f"  深度正文完成：{board['total_chars']}字，{len(board['scenes'])}章，来源页码已附")
    return board
