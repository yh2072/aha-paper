"""公众号深度报告：论文全文 + 全部主图逐一深讲 → wechat.docx。

定位区别于视频：视频是 3 分钟钩子型科普，公众号是 2500~4000 字的深度解读，
讲解**所有**检出的 main figures（不止视频里用到的那几张）。
Word 打开全选复制，粘进公众号编辑器即可（图片自动上传）。
"""
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .. import llm
from . import pdf_extract

INK = RGBColor(0x3D, 0x2F, 0x26)
GRAY = RGBColor(0x8A, 0x7A, 0x6D)
CORAL = RGBColor(0xC9, 0x5C, 0x4A)

_PROMPT = """你是精通神经科学的深度科普作者。基于论文全文和图注素材，写一篇微信公众号深度解读
（面向聪明的外行：保持亲和口吻"咱们"，但信息密度要高，敢给数字、敢讲方法）。

要求：
- figure_sections 必须覆盖下面列出的【全部 {n_figs} 张图】，一张不落，顺序一致；
  每张图 250~450 字深度讲解：逐面板讲（a图画什么、坐标轴/颜色怎么读、
  关键数字是多少、这张图在整个论证链里扮演什么角色）；给每张图起一个小标题
- background 讲清这研究要回答什么问题、为什么之前没答案（200~300字）
- method_note 用大白话讲研究怎么做的（150~250字，含样本量等关键数字）
- takeaways 3~5 条对普通人的启示/可操作建议
- limitations 诚实讲 1~2 条研究局限（100字内）
- 全文书面但不学究，杜绝"值得注意的是"这类套话

只输出 JSON：
{{"lead": "导语，3~4句钩住读者",
  "background": "...",
  "figure_sections": [{{"file": "fig_01.png", "heading": "图1小标题", "body": "..."}}, ...],
  "method_note": "...",
  "takeaways": ["...", "..."],
  "limitations": "...",
  "ending": "结尾：升华 + 互动问题"}}

论文图片素材（共 {n_figs} 张，讲解要点供参考）：
{figs_desc}

论文全文（截取）：
{paper}"""


def _set_cn_font(run, size=12, bold=False, color=INK, name="微软雅黑"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _para(doc, text, size=12, bold=False, color=INK, align=None, space_after=10):
    p = doc.add_paragraph()
    run = p.add_run(str(text))
    _set_cn_font(run, size=size, bold=bold, color=color)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.6
    if align:
        p.alignment = align
    return p


def _heading(doc, text, size=15):
    _para(doc, text, size=size, bold=True, color=CORAL, space_after=8)


def _image(doc, path: Path, caption: str, width=5.6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Inches(width))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cap.add_run(caption)
    _set_cn_font(run, size=9, color=GRAY)
    cap.paragraph_format.space_after = Pt(14)


def build_article(proj_dir: Path, meta: dict, log=print) -> Path:
    figs = meta.get("figures") or []
    figs_desc = "\n".join(
        f"- {f['file']}: {f.get('caption', '')}\n" +
        "".join(f"    · {p}\n" for p in f.get("walkthrough", []))
        for f in figs) or "（本论文未检出插图）"
    paper = pdf_extract.extract_text(proj_dir / "paper.pdf")[:42000]

    art = llm.chat_json([{"role": "user", "content": _PROMPT.format(
        n_figs=len(figs), figs_desc=figs_desc, paper=paper)}], temperature=0.5)
    fig_secs = {s.get("file"): s for s in art.get("figure_sections", [])}

    doc = Document()
    _para(doc, meta.get("title", ""), size=20, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    src = " · ".join(x for x in [meta.get("journal", ""),
                                 meta.get("paper_title", "")] if x)
    if src:
        _para(doc, f"论文出处：{src}", size=9, color=GRAY,
              align=WD_ALIGN_PARAGRAPH.CENTER, space_after=16)
    if art.get("lead"):
        _para(doc, art["lead"], size=13, color=CORAL, space_after=14)

    # 开篇配一张手绘图缓和阅读节奏
    opener = proj_dir / "images" / "scene_00.png"
    if opener.exists():
        _image(doc, opener, "▲ 插图 by AI", width=4.6)

    if art.get("background"):
        _heading(doc, "这项研究想回答什么？")
        _para(doc, art["background"])
    if art.get("method_note"):
        _heading(doc, "他们是怎么做的？")
        _para(doc, art["method_note"])

    # 核心：全部主图逐一深讲
    journal = meta.get("journal") or "原论文"
    for k, f in enumerate(figs):
        img = proj_dir / "figures" / f["file"]
        if not img.exists():
            continue
        sec = fig_secs.get(f["file"], {})
        _heading(doc, f"图 {k + 1} ｜ {sec.get('heading', f.get('caption', ''))}")
        _image(doc, img, f"▲ 论文原图 Figure（{journal}）")
        _para(doc, sec.get("body", f.get("caption", "")))

    if art.get("takeaways"):
        _heading(doc, "对咱们意味着什么？")
        for t in art["takeaways"]:
            _para(doc, f"✅ {t}", space_after=6)
    if art.get("limitations"):
        _heading(doc, "冷静一下：这研究的边界")
        _para(doc, art["limitations"])
    if art.get("ending"):
        _para(doc, art["ending"], size=12, space_after=16)
    _para(doc, "—— 关注我，每周深读一篇顶刊论文 ——", size=10, color=GRAY,
          align=WD_ALIGN_PARAGRAPH.CENTER)

    out = proj_dir / "wechat.docx"
    doc.save(out)
    log(f"  公众号深度报告 wechat.docx（{len(figs)} 图全讲）✓")
    return out
