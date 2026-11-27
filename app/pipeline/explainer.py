"""Fast default delivery: narrated live Canvas/figure explainer, without video frames."""
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import quote
from .. import config, lang
from . import figures,tts,cue_alignment,page_highlight
from ..bin import ffmpeg as ffmpeg_bin


def build(project_dir:Path,meta:dict,log=print,progress=None):
    scenes=(meta.get('storyboard') or {}).get('scenes') or []
    if not scenes:raise ValueError('尚未生成深度章节')
    # The narration's language decides the voice, where a sentence ends and where
    # the cursor moves. An absent lang is a project made before the parameter
    # existed, which is Chinese -- see lang.get.
    profile=lang.get(meta.get('lang'))
    work=project_dir/'explainer_work';work.mkdir(exist_ok=True)
    if meta.get('script_profile')=='deep-science-v1':
        # A chapter with no figure reads the paper itself. There is no second
        # renderer: every picture on screen is either the paper's own figure or
        # the paper's own page.
        page_highlight.prepare(scenes,project_dir,work,log=log,profile=profile)
    prefix='/files/'+quote(project_dir.name,safe='')+'/'
    segments=[];start=0.0;audio=[]
    for i,scene in enumerate(scenes):
        if progress:progress(f'互动讲解配音与同步 {i+1}/{len(scenes)}')
        log(f'  实时章节 {i+1}/{len(scenes)}：配音与同步，不渲染视频帧')
        sentences=tts.split_sentences(scene['text'],profile=profile)
        wav=work/f'seg_{i:02d}.wav';stamp=wav.with_suffix('.key');timing=wav.with_suffix('.durs.json')
        key=hashlib.sha256((tts.cache_identity(profile)+scene['text']).encode()).hexdigest()
        if wav.exists() and stamp.exists() and stamp.read_text()==key and timing.exists():
            durs=json.loads(timing.read_text());log('    复用已合成的配音')
        else:
            _,durs=tts.synthesize_sentences(sentences,wav,log=log,profile=profile)
            timing.write_text(json.dumps(durs));stamp.write_text(key)
        duration=tts.duration_of(wav)
        timestamps=wav.with_suffix('.timestamps.json')
        if timestamps.exists():
            sentences=cue_alignment.units(scene['text'],profile)
            cues,alignment=cue_alignment.align(sentences,json.loads(timestamps.read_text()),duration)
        else:
            cues=[];local=0.0
            for sentence,dur in zip(sentences,durs):
                cues.append({'text':sentence,'start':round(local,4),'end':round(local+dur,4),'region':None});local+=dur
            alignment={'version':'legacy-sentence-cache'}
        figure=Path(scene['figure_path']) if scene.get('figure_path') else None
        regions=[None]*len(sentences)
        visual=None
        if figure and figure.exists():
            regfile=work/f'seg_{i:02d}.regions.json'
            regkey=hashlib.sha256(figure.read_bytes()+json.dumps(sentences,ensure_ascii=False).encode()+b'cue-v3').hexdigest()
            if regfile.exists():stored=json.loads(regfile.read_text())
            else:stored={}
            if stored.get('key')==regkey:regions=stored['regions']
            else:
                regions=figures.map_sentences_to_regions(figure,sentences,log=log)
                regfile.write_text(json.dumps({'key':regkey,'regions':regions}))
            regions=(regions+[None]*len(sentences))[:len(sentences)]
            visual={'kind':'figure','url':prefix+'figures/'+quote(figure.name),'pointer_style':'sage-paper-v2'}
        elif (project_dir/'paper.pdf').exists():
            stored=json.loads(Path(scene['page_plan']).read_text(encoding='utf-8')) if scene.get('page_plan') else {}
            highlights=(stored.get('highlights') or [])
            # One highlight per cue, by position. A count that does not match
            # means the plan was made from a different split of this narration,
            # and padding it would silently mark the wrong source sentence for
            # every cue after the first. Showing the page with nothing marked is
            # a worse-looking failure and an honest one.
            if highlights and len(highlights)!=len(cues):
                log(f'  章节{i+1}：原文高亮{len(highlights)}条对不上{len(cues)}句讲解，这一章只显示页面')
                highlights=[]
            highlights=(highlights+[None]*len(cues))[:len(cues)]
            used=sorted({h['page'] for h in highlights if h})
            # Nothing matched: show the pages this chapter cites rather than nothing.
            if not used:used=sorted({n for n in (scene.get('source_pages') or []) if isinstance(n,int)})[:2] or [1]
            names=page_highlight.render_pages(project_dir/'paper.pdf',used,project_dir/'pages')
            if not names:raise ValueError(f'章节{i+1}的论文页渲染失败')
            for cue,spot in zip(cues,highlights):cue['highlight']=spot
            visual={'kind':'page','aspect':'page','engine':page_highlight.VERSION,
                'pages':{str(number):prefix+'pages/'+quote(name) for number,name in names.items()}}
        else:raise ValueError(f'章节{i+1}既没有主图，也没有可读的论文 PDF')
        for cue,region in zip(cues,regions):cue['region']=region
        page=next((f.get('page')for f in meta.get('figures',[])if f.get('file')==scene.get('figure')),None)
        segments.append({'id':f'segment-{i+1}','index':i,'title':scene.get('segment_title') or scene.get('visual_concept',''),
            'summary':scene['text'],'start':round(start,4),'end':round(start+duration,4),'duration':duration,
            'figure':bool(figure),'visual':visual,'cues':cues,'alignment':alignment,
            'figure_source':(f'原论文插图 · PDF 第{page}页' if page else
                '原文高亮 · PDF 第'+'、'.join(str(n) for n in sorted({c['highlight']['page']
                    for c in cues if c.get('highlight')}))+'页'
                if visual['kind']=='page' and any(c.get('highlight') for c in cues) else None),
            'sources':[{'label':f'原论文 · PDF 第{n}页','url':prefix+'paper.pdf#page='+str(n),'page':n}
                for n in scene.get('source_pages',[])]})
        start+=duration;audio.append(wav)
    if progress:progress('拼接旁白与互动章节')
    concat=work/'audio-concat.txt'
    concat.write_text(''.join(f"file '{path.name}'\n"for path in audio))
    out=project_dir/'narration.mp3';partial=project_dir/'narration.partial.mp3'
    result=subprocess.run([ffmpeg_bin(),'-y','-v','error','-f','concat','-safe','0','-i',str(concat.resolve()),
        '-c:a','libmp3lame','-b:a','128k',str(partial.resolve())],capture_output=True,text=True,cwd=work)
    if result.returncode:raise RuntimeError('旁白拼接失败: '+result.stderr[-500:])
    partial.replace(out)
    manifest={'version':2,'product':'aha-paper','mode':'explainer','id':project_dir.name,
        'title':meta.get('title') or meta.get('paper_title','论文深度讲解'),'paper_title':meta.get('paper_title',''),
        'audio':prefix+'narration.mp3','video':None,'cover':prefix+'images/'+quote(meta['cover']) if meta.get('cover') else None,
        'duration':round(start,4),'segments':segments,'doi':meta.get('doi',''),'script_profile':meta.get('script_profile',''),
        'pointer_style':'sage-paper-v2','aspect_ratio':'16:9','sync_version':cue_alignment.VERSION}
    raw=json.dumps(manifest,ensure_ascii=False,indent=2)
    for name in ('explainer.json','experience.json'):
        tmp=project_dir/(name+'.tmp');tmp.write_text(raw);tmp.replace(project_dir/name)
    log(f'实时互动讲解完成：{len(segments)}章，{start/60:.1f}分钟；无需渲染MP4')
    return manifest
