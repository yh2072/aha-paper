"""小红书图文版：把一篇论文做成 3:4 多页卡片（封面 + 讲图页 + 观点页 + 结尾）。

和视频版共用同一批素材（论文主图、手绘配图、封面、文稿），只是换一种载体：
图文帖不需要配音和时间轴，但每页文字必须极短——手机上一屏就要读完。
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .. import llm
from .cover import _body_font as _font
from .cover import _title_font as _tfont

W, H = 1080, 1440          # 小红书竖版图文标准比例
BG = (250, 244, 230)       # 奶油米，与封面/视频同一套品牌色
INK = (61, 47, 38)
SOFT = (138, 122, 109)
ACCENT = (214, 108, 90)
MARGIN = 72
MAX_PAGES = 12             # 小红书上限 18，留出余量；太多没人翻完


_PLAN_PROMPT = """把下面这篇论文科普稿改写成小红书【图文帖】的分页文案。

【最重要：图文是"读"的，不是"听"的】
原稿是口播稿，为耳朵写的，所以口语、重复、有语气词。图文要重写成**书面语**：
- 用完整、准确的句子。专业名词该出现就出现，第一次出现时用一个短句解释清楚
- 去掉所有口水词和语气承接："说白了""你别说""咱们来看看""接下来""其实呢"
- 去掉为了念顺口而做的重复。同一个意思只说一遍，说准
- 书面不等于端着：仍然平视读者、不说教、不用"你必须""大部分人都不知道"

已有的论文插图（可以配到讲图页上）：
{figs}

产出 {n_content} 页正文（不含封面和结尾页），只输出 JSON：
{{"pages": [{{"heading": "本页标题", "lines": ["要点1", "要点2"], "figure": "fig_0X.png 或 null"}}]}}

硬性要求：
- heading：不超过 14 字，**必须是一个有信息量的结论**，让人只看标题就有收获。
  ✗ 禁止空转标题：「这张图说明了什么」「带你看一张图」「什么是信息熵」
    「大脑为什么会卡顿」——这类标题什么都没说，读者划过去一无所获
  ✓ 要这样：「混乱信息让反应慢32毫秒」「模块化结构降低认知负担」
    「真实网络的信息容量更高」
- lines：2~3 条，每条不超过 26 字，各自独立成句，合起来把这一页讲透。
  读者会跳着看，所以每页都要能单独读懂，不许写承接上下页的句子
- 有 2~3 页挂论文插图（figure 填对应文件名）。讲图页的写法：
  heading 直接写出**这张图证明了什么**（带上关键数字）；
  lines 说清楚坐标轴是什么、该看哪条线或哪个对比、差异有多大
- 其余页 figure 填 null
- 【真实性】所有数字和结论必须来自原稿，一个都不许编
- 不写 emoji、不写页码、不写"图1显示"这类论文腔

原稿：
{script}"""


# 空转标题黑名单：这类标题读者划过去一无所获，是图文帖最常见的废话
_EMPTY_HEADINGS = ("说明了什么", "是什么", "什么是", "为什么会", "带你看",
                   "一起来看", "怎么回事", "了解一下", "看这张图", "划重点",
                   "揭秘", "真相是", "你知道吗")


def _bad_heading(h: str) -> bool:
    h = h.strip()
    return (not h) or len(h) < 5 or any(k in h for k in _EMPTY_HEADINGS)


def _wrap(text: str, per_line: int) -> list[str]:
    lines, cur = [], ""
    for ch in text.strip():
        cur += ch
        if len(cur) >= per_line and ch not in "，。！？、；：":
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines


def _page_base(idx: int, total: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 页码：右上角小圆点标，翻页时有连续感
    f = _font(30)
    txt = f"{idx}/{total}"
    tw = d.textlength(txt, font=f)
    d.rounded_rectangle([W - MARGIN - tw - 34, 52, W - MARGIN, 104],
                        radius=26, fill=ACCENT)
    d.text((W - MARGIN - tw - 17, 60), txt, font=f, fill=(255, 250, 242))
    return img, d


def _paste_art(img: Image.Image, src: Path, box: tuple[int, int, int, int],
               fill: bool) -> int:
    """把素材放进 box，返回图片底边 y。fill=True 裁切满铺，False 完整展示。"""
    x, y, bw, bh = box
    art = Image.open(src).convert("RGB")
    if fill:
        art = ImageOps.fit(art, (bw, bh), method=Image.LANCZOS)
    else:
        art = ImageOps.contain(art, (bw, bh), method=Image.LANCZOS)
    card = Image.new("RGB", art.size, (255, 253, 248))
    card.paste(art, (0, 0))
    mask = Image.new("L", art.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, art.size[0], art.size[1]],
                                           radius=28, fill=255)
    px = x + (bw - art.width) // 2
    img.paste(card, (px, y), mask)
    return y + art.height


def _draw_text_block(d: ImageDraw.ImageDraw, heading: str, lines: list[str],
                     top: int) -> int:
    """小标题 + 要点。返回底边 y。"""
    y = top
    hf = _tfont(62)
    for ln in _wrap(heading, 13)[:2]:
        d.text((MARGIN, y), ln, font=hf, fill=INK)
        y += 78
    y += 14
    d.line([MARGIN, y, MARGIN + 96, y], fill=ACCENT, width=6)   # 小色条分隔
    y += 30
    bf = _font(40)
    for item in lines:
        for k, ln in enumerate(_wrap(item, 22)):
            if k == 0:
                d.ellipse([MARGIN + 4, y + 20, MARGIN + 18, y + 34], fill=ACCENT)
            d.text((MARGIN + 38, y), ln, font=bf, fill=INK if k == 0 else SOFT)
            y += 58
        y += 12
    return y


def _ending_page(idx: int, total: int, question: str, tags: list[str]) -> Image.Image:
    img, d = _page_base(idx, total)
    y = 300
    hf = _tfont(70)
    for ln in _wrap(question or "你有过这种感觉吗？", 11)[:3]:
        d.text((MARGIN, y), ln, font=hf, fill=INK)
        y += 92
    y += 40
    d.line([MARGIN, y, W - MARGIN, y], fill=(232, 221, 204), width=3)
    y += 46
    bf = _font(42)
    d.text((MARGIN, y), "评论区聊聊你的情况 👇", font=bf, fill=ACCENT)
    y += 90
    tf = _font(34)
    line = ""
    for t in tags[:6]:
        cand = (line + "  " + t).strip()
        if d.textlength(cand, font=tf) > W - MARGIN * 2:
            d.text((MARGIN, y), line, font=tf, fill=SOFT)
            y += 52
            line = t
        else:
            line = cand
    if line:
        d.text((MARGIN, y), line, font=tf, fill=SOFT)
    return img


def _tags_from_intro(intro: str) -> list[str]:
    return [w for w in intro.split() if w.startswith("#")][:6]


def build(proj_dir: Path, meta: dict, log=print) -> list[str]:
    """生成图文页，返回文件名列表（第 1 页是封面）。"""
    out_dir = proj_dir / "carousel"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("p*.png"):
        old.unlink()

    figs = meta.get("figures") or []
    figs_desc = "\n".join(
        f"- {f['file']}: {f.get('caption', '')}" for f in figs) or "（这篇没有可用主图）"
    n_content = min(max(len(meta.get("storyboard", {}).get("scenes", [])), 5),
                    MAX_PAGES - 2)
    plan = llm.chat_json([{"role": "user", "content": _PLAN_PROMPT.format(
        figs=figs_desc, n_content=n_content,
        script=meta.get("script", ""))}], temperature=0.8)
    pages = plan.get("pages", [])[:n_content]
    if not pages:
        raise RuntimeError("图文分页生成失败：模型没给出 pages")
    bad = [p for p in pages if _bad_heading(str(p.get("heading", "")))]
    if bad:
        # 拦下空转标题，带着反面例子让它重写一次。程序侧兜底，不指望提示词百分百听话。
        log(f"  标题空转 {len(bad)} 页，要求重写：{[p.get('heading') for p in bad]}")
        retry = llm.chat_json([{"role": "user", "content":
            "下面这些图文页的标题是废话，读者看了一无所获，请逐条重写。\n"
            "每个标题不超过 14 字，必须是有信息量的结论，带上关键数字或对比。\n"
            "禁止「这张图说明了什么」「什么是XX」「带你看XX」这类空转写法。\n"
            "只输出 JSON：{\"headings\": [\"新标题1\", ...]}，顺序和下面一致。\n\n"
            + "\n".join(f"{i + 1}. 原标题：{p.get('heading')}｜本页要点："
                        f"{'；'.join(str(x) for x in (p.get('lines') or []))}"
                        for i, p in enumerate(bad))}], temperature=0.7)
        for p, h in zip(bad, retry.get("headings", [])):
            if not _bad_heading(str(h)):
                p["heading"] = str(h).strip()

    total = len(pages) + 2          # 封面 + 正文 + 结尾
    files: list[str] = []

    # 第 1 页：直接用已有封面，图文和视频共用同一张脸
    cov = proj_dir / "images" / "cover.png"
    p1 = out_dir / "p01.png"
    if cov.exists():
        Image.open(cov).convert("RGB").resize((W, H), Image.LANCZOS).save(p1)
    else:
        img, d = _page_base(1, total)
        d.text((MARGIN, 500), meta.get("title", "")[:15], font=_tfont(88), fill=INK)
        img.save(p1)
    files.append(p1.name)

    scene_imgs = [proj_dir / "images" / n
                  for n in (meta.get("images") or []) if n]
    si = 0
    for i, pg in enumerate(pages):
        idx = i + 2
        img, d = _page_base(idx, total)
        fig_name = pg.get("figure")
        fig_path = proj_dir / "figures" / str(fig_name) if fig_name else None
        if fig_path and fig_path.exists():
            # 讲图页：论文图完整展示不裁切（图里的坐标轴和标注不能切掉）。
            # 给到 760 高，宽幅图也能撑满宽度；文字块紧跟在图下方，不留空档。
            bottom = _paste_art(img, fig_path, (MARGIN, 150, W - MARGIN * 2, 760),
                                fill=False)
        else:
            art = scene_imgs[si] if si < len(scene_imgs) else None
            si += 1
            bottom = (_paste_art(img, art, (MARGIN, 150, W - MARGIN * 2, 620),
                                 fill=True) if art and art.exists() else 150)
        _draw_text_block(d, str(pg.get("heading", "")),
                         [str(x) for x in (pg.get("lines") or [])][:3],
                         bottom + 56)
        p = out_dir / f"p{idx:02d}.png"
        img.save(p)
        files.append(p.name)

    # 末页：互动钩子 + 话题标签
    board = meta.get("storyboard") or {}
    last_txt = (board.get("scenes") or [{}])[-1].get("text", "")
    question = next((s for s in reversed(last_txt.split("。")) if "？" in s), "")
    end = _ending_page(total, total, question.strip()[:40],
                       _tags_from_intro(meta.get("intro", "")))
    pe = out_dir / f"p{total:02d}.png"
    end.save(pe)
    files.append(pe.name)

    log(f"  图文版完成：{len(files)} 页（含封面和结尾）")
    return files
