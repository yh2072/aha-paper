"""The cover image: a restrained diagram, not a painting.

What this replaced asked for impressionist brushwork, sun-dappled light and a
coral-and-ochre risograph palette. Next to a page of a journal article that reads
as decoration, and it fought the interface it sits in. The brief now is a journal
figure's economy: flat shapes, a near-empty field, one idea.
"""
import base64
import io
import json
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageOps
from .. import config, llm
from .cover import _body_font


def generate(meta: dict, out_dir: Path, log=print):
    out_dir.mkdir(parents=True,exist_ok=True)
    prompt=("A spare, precise cover illustration for a scientific paper about: "
        +meta.get('storyboard',{}).get('cover_prompt',meta.get('title',''))+
        ". Flat vector shapes with clean geometry and a great deal of empty space. "
        "Palette limited to off-white paper, one deep ink tone, and at most two desaturated "
        "accents; flat fills only, no gradients, no texture, no paper grain. "
        "One clear diagrammatic metaphor taken from the topic -- nodes and links, axes, "
        "nested planes, a simple instrument -- drawn with the economy of a journal figure. "
        "Calm, exact and unsentimental, like a well-made textbook plate. "
        "No brush strokes, no painterly rendering, no landscape, no people, no mascots, no clutter. "
        "One focal form in the middle and lower two thirds; the upper 30 percent is plain "
        "empty background for typesetting. Portrait 3:4. "
        "No text, no lettering, no numbers, no captions, no logos, no watermark.")
    log(f'  AI Image 封面 · {config.setting("MODEL_COVER")}')
    base,headers=llm.connection('image')
    payload={'model':config.setting('MODEL_COVER'),'prompt':prompt,'quality':'high','output_format':'png'}
    if config.setting('IMAGE_PROTOCOL')=='openrouter-images':
        endpoint='/images';payload['aspect_ratio']='3:4'
    elif config.setting('IMAGE_PROTOCOL')=='openai-images':
        endpoint='/images/generations';payload['size']='1024x1536'
    else:raise ValueError('未配置支持的图片 API 协议')
    response=httpx.post(base+endpoint,headers=headers,json=payload,timeout=300)
    response.raise_for_status()
    data=response.json()
    if not data.get('data'):raise RuntimeError('图片 API 未返回封面图片')
    item=data['data'][0]
    if item.get('b64_json'):raw=base64.b64decode(item['b64_json'])
    elif item.get('url'):
        download=httpx.get(item['url'],timeout=120);download.raise_for_status();raw=download.content
    else:raise RuntimeError('图片 API 未返回 base64 或下载 URL')
    image=Image.open(io.BytesIO(raw)).convert('RGB')
    image.save(out_dir/'cover_art.png')
    (out_dir/'cover_prompt.json').write_text(json.dumps({'model':config.setting('MODEL_COVER'),'prompt':prompt},ensure_ascii=False,indent=2))
    compose(out_dir/'cover_art.png',meta,out_dir/'cover.png')
    return 'cover.png'


def compose(art: Path, meta: dict, output: Path):
    canvas=ImageOps.fit(Image.open(art).convert('RGB'),(1080,1440))
    draw=ImageDraw.Draw(canvas)
    draw.text((80,62),'a h a - p a p e r',font=_body_font(24),fill='#1f6f4f')
    title=meta.get('title') or meta.get('paper_title') or '一篇论文的故事'
    for size in (82,72,62,52):
        font=_body_font(size)
        lines=[];line=''
        for char in title[:40]:
            if draw.textlength(line+char,font=font)>920:
                lines.append(line);line=char
            else:
                line+=char
        if line:lines.append(line)
        if len(lines)<=3:break
    for i,line in enumerate(lines[:3]):
        draw.text((76,126+i*size*1.3),line,font=font,fill='#18181b',stroke_width=0)
    # No subtitle. One line of 30px type could not hold a real one, and trimming it
    # to fit left a fragment that ended mid-clause -- less informative than the
    # white space it occupied. The full subtitle is still in the manifest and on
    # the page; it is just not burnt into the image.
    canvas.save(output)
