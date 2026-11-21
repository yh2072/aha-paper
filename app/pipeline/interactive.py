"""A seekable segment manifest and the offline bundle for aha-paper."""
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote
from .. import config, llm
from . import tts


# The offline bundle rewrites these paths in watch.html AND copies the files;
# listing them twice let i18n.js be referenced but not shipped.
# The flat emoji the watch page uses are served from web/emoji; a bundle opened
# from disk has no network, so the ones it references travel with it.
BUNDLE_ASSETS=('watch.css','refine.css','watch.js',
               'explainer-player.js','i18n.js',
               'emoji/1f5a5.svg','emoji/LICENSE.txt')

def _text(value,limit=300):
    return str(value or '').strip()[:limit]


def build_manifest(project_dir: Path, meta: dict):
    live=project_dir/'explainer.json'
    if meta.get('experience_mode') == 'explainer' and live.exists():
        return json.loads(live.read_text())
    scenes=(meta.get('storyboard') or {}).get('scenes') or []
    segments=[];start=0.0
    for i,scene in enumerate(scenes):
        video=project_dir/'tts_work'/f'seg_{i:02d}.mp4'
        if not video.exists():
            return None  # Never invent timestamps for legacy or incomplete videos.
        duration=tts.duration_of(video)
        title=scene.get('segment_title') or scene.get('visual_concept') or scene.get('text','').split('。')[0]
        segments.append({'id':f'segment-{i+1}','index':i,'title':_text(title,42),
            'summary':_text(scene.get('text'),500),'start':round(start,4),
            'end':round(start+duration,4),'duration':duration,
            'figure':bool(scene.get('figure_path')),
            'sources':[{'label':f'原论文 · PDF 第{n}页',
                        'url':'/files/'+quote(project_dir.name,safe='')+'/paper.pdf#page='+str(n),
                        'page':n} for n in scene.get('source_pages',[])],
            'figure_source':('原论文插图 · PDF 第'+str(next((f.get('page') for f in meta.get('figures',[]) if f.get('file')==scene.get('figure')), ''))+'页') if scene.get('figure_path') else None})
        start+=duration
    if not segments:return None
    video_name=meta.get('tts_output') or meta.get('output')
    if not video_name:return None
    prefix='/files/'+quote(project_dir.name,safe='')+'/'
    return {'version':1,'product':'aha-paper','id':project_dir.name,
        'title':meta.get('title') or meta.get('paper_title') or meta.get('pdf_name','论文故事'),
        'paper_title':meta.get('paper_title',''),'video':prefix+quote(video_name),
        'cover':prefix+'images/'+quote(meta['cover']) if meta.get('cover') else None,
        'duration':round(start,4),'segments':segments,'doi':meta.get('doi',''),'script_profile':meta.get('script_profile','')}


def write_manifest(project_dir,meta):
    manifest=build_manifest(project_dir,meta)
    if manifest:
        (project_dir/'experience.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


def export_bundle(project_dir,meta):
    manifest=build_manifest(project_dir,meta)
    if not manifest:raise ValueError('互动讲解尚未生成完成')
    manifest=copy.deepcopy(manifest)
    live=manifest.get('mode')=='explainer'
    video_name=meta.get('tts_output') or meta.get('output')
    if live:
        manifest['audio']='media/narration.mp3'
        for segment in manifest['segments']:
            visual=segment['visual']
            from urllib.parse import unquote,urlsplit
            local=lambda url:unquote(Path(urlsplit(url).path).name)
            if visual['kind']=='page':
                # Several rendered pages per chapter, addressed by page number.
                visual['pages']={n:'pages/'+local(url) for n,url in (visual.get('pages') or {}).items()}
                continue
            visual['url']='figures/'+local(visual['url'])   # 只剩真实主图这一种单文件画面
    else:
        manifest['video']='media/video.mp4'
    manifest['cover']='media/cover.png' if meta.get('cover') else None
    for segment in manifest['segments']:
        for source in segment.get('sources',[]):
            source['url']='source/paper.pdf#page='+str(source['page'])
    raw=json.dumps(manifest,ensure_ascii=False).replace('<','\\u003c')
    html=(config.ROOT/'web/watch.html').read_text()
    for name in BUNDLE_ASSETS:
        html=html.replace('/assets/'+name,name)
    html=html.replace('</head>','<script type="application/json" id="experienceData">'+raw+'</script></head>')
    path=project_dir/'aha-paper-interactive.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as bundle:
        bundle.writestr('index.html',html)
        for name in BUNDLE_ASSETS:
            bundle.write(config.ROOT/'web'/name,name)
        bundle.write(config.ROOT/'web/RISO-LICENSE.txt','RISO-LICENSE.txt')
        if live:
            bundle.write(project_dir/'narration.mp3','media/narration.mp3')
            used=set()
            for segment in manifest['segments']:
                visual=segment['visual']
                # The page view ships one image per cited page, not a single file.
                paths=list((visual.get('pages') or {}).values()) if visual['kind']=='page' else [visual['url']]
                for relative in paths:
                    if relative not in used:
                        bundle.write(project_dir/relative,relative);used.add(relative)
        else:
            bundle.write(project_dir/video_name,'media/video.mp4')
        if (project_dir/'paper.pdf').exists():bundle.write(project_dir/'paper.pdf','source/paper.pdf')
        if meta.get('cover'):bundle.write(project_dir/'images'/meta['cover'],'media/cover.png')
        bundle.writestr('experience.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return path
