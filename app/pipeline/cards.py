"""The explainer as a deck of 3:4 cards, for reading rather than watching.

The video asks for thirteen minutes and headphones. A deck asks for a thumb.
Same chapters, same figures, same claims, same source pages -- what changes is
that the reader sets the pace and can stop on one card and read it twice.

Two rules shape every card here:

* **The text is fitted before the picture.** Chapters run 295 to 406 characters
  and the box is fixed, so sizing the picture first and giving the text what is
  left guarantees that the longest chapter overflows -- which in a rendered PNG
  means silently cut off, with nothing to notice. So the type size comes down a
  ladder until the wrapped text fits, and the picture takes the height that
  remains. A short chapter gets a big picture; a long one gets a smaller
  picture and all of its words.

* **Wrapping is the narration language's.** cover.py's own _wrap cuts every
  max_per_line characters, which is right for Chinese and breaks English words
  in half. Profile.subtitle_lines already settles that question for the video's
  captions; a card is the same question with a wider box.

Nothing here is drawn by a model. The cover is the paper's own title, screen-
shotted from page one, under the explainer's headline; each chapter card is the
paper's own figure or page. That is the same promise the player makes, kept in
a format that travels.
"""
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .. import lang
from .cover import (W, H, _body_font, _draw_playful_title, _paper_snippet_card,
                    _split_title, _title_font)

CREAM = (252, 247, 236)
INK = (58, 53, 82)
MUTED = (106, 101, 133)
LINE = (228, 220, 205)
ACCENT = (255, 143, 69)

MARGIN = 72
HEADER_TOP = 64
FOOTER_H = 92
GAP = 34
MIN_PICTURE = 380          # below this a figure stops being readable at all
TEXT_SIZES = (40, 36, 33, 30, 27, 24)


def _text_block(text: str, profile, size: int) -> tuple[list[str], int]:
    """The narration wrapped to the card's width, and how tall it comes out."""
    lines = profile.subtitle_lines(text, W - MARGIN * 2, size)
    return lines, len(lines) * int(size * 1.62)


def _fit(text: str, profile, budget: int) -> tuple[list[str], int, int]:
    """Largest size on the ladder whose wrapped text fits the budget.

    Falls through to the smallest rather than raising: a card with small type
    is still readable, and a chapter that cannot be shown at all is not."""
    for size in TEXT_SIZES:
        lines, height = _text_block(text, profile, size)
        if height <= budget:
            return lines, size, height
    lines, height = _text_block(text, profile, TEXT_SIZES[-1])
    return lines, TEXT_SIZES[-1], height


MARKER = (247, 206, 86, 150)        # the player's marker, as a flat wash


def _picture(path: Path | None, box: tuple[int, int]) -> Image.Image | None:
    """The paper's own figure or page, contained in the space left for it."""
    if not path or not Path(path).exists():
        return None
    img = Image.open(path).convert("RGB")
    return ImageOps.contain(img, box, Image.Resampling.LANCZOS)


def _page_passage(path: Path | None, highlights: list[dict]) -> Image.Image | None:
    """The page cropped to the sentences this chapter explains, marked.

    A whole PDF page contained in half a card is 400 pixels of 9-point type --
    present, and unreadable, which is the worst of both. The chapter already
    knows which lines it is about: every cue carries the rectangles its quote
    resolved to, in normalised page coordinates. Cropping to their band gives
    text at a size worth setting, and it is the passage rather than an arbitrary
    part of the page.

    The marker is drawn here because the rendered page is clean -- in the player
    the highlight is painted on a canvas above it, so a card that only cropped
    would show the right paragraph with nothing pointing at it.
    """
    rects = [r for spot in highlights for r in (spot.get("rects") or [])]
    if not path or not Path(path).exists() or not rects:
        return None
    page = Image.open(path).convert("RGB")
    pw, ph = page.size

    top = max(min(r[1] for r in rects) - 0.025, 0.0)
    bottom = min(max(r[1] + r[3] for r in rects) + 0.030, 1.0)
    if bottom - top < 0.10:            # a single line: give it something to sit in
        middle = (top + bottom) / 2
        top, bottom = max(middle - 0.05, 0.0), min(middle + 0.05, 1.0)

    wash = Image.new("RGBA", page.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(wash)
    for x, y, w, h in rects:
        pad = h * 0.18
        draw.rectangle([x * pw, (y - pad) * ph, (x + w) * pw, (y + h + pad) * ph],
                       fill=MARKER)
    page = Image.alpha_composite(page.convert("RGBA"), wash).convert("RGB")

    # Horizontally too, because a paper is set in columns. Keeping the full
    # width means half the crop is the column the chapter is not talking about,
    # and the type ends up half the size it could be. If the highlights do span
    # both columns this widens back out on its own.
    left = max(min(r[0] for r in rects) - 0.030, 0.0)
    right = min(max(r[0] + r[2] for r in rects) + 0.030, 1.0)
    if right - left < 0.30:
        middle = (left + right) / 2
        left, right = max(middle - 0.15, 0.0), min(middle + 0.15, 1.0)
    return page.crop((int(left * pw), int(top * ph), int(right * pw), int(bottom * ph)))


def _header(draw: ImageDraw.ImageDraw, index: int, total: int, title: str) -> int:
    badge = f"{index:02d} / {total:02d}"
    font = _body_font(30)
    draw.text((MARGIN, HEADER_TOP), badge, font=font, fill=ACCENT)
    width = int(draw.textlength(badge, font=font))
    if title:
        tfont = _body_font(30)
        room = W - MARGIN * 2 - width - 24
        shown = title
        while shown and draw.textlength(shown, font=tfont) > room:
            shown = shown[:-1]
        if shown != title:
            shown = shown[:-1] + "…"
        draw.text((MARGIN + width + 24, HEADER_TOP), shown, font=tfont, fill=MUTED)
    y = HEADER_TOP + 46
    draw.line([(MARGIN, y), (W - MARGIN, y)], fill=LINE, width=2)
    return y + GAP


def _footer(draw: ImageDraw.ImageDraw, source: str) -> None:
    font = _body_font(26)
    y = H - FOOTER_H + 18
    draw.line([(MARGIN, y - 18), (W - MARGIN, y - 18)], fill=LINE, width=2)
    if source:
        draw.text((MARGIN, y), source, font=font, fill=MUTED)
    mark = "aha-paper"
    draw.text((W - MARGIN - int(draw.textlength(mark, font=font)), y),
              mark, font=font, fill=MUTED)


def _headline(title: str, max_lines: int = 5) -> list[str]:
    """The explainer's own headline, broken only where the author paused.

    Two failures to avoid, and they pull against each other. cover.py's
    _split_title caps at three lines and drops the rest, so a 32-character
    headline lost its back half. Packing greedily into the narrowest line that
    fits the line budget gives "在大脑里共 / 用多少表征" -- every word present
    and one of them cut in half.

    So the line width is chosen to avoid splitting a phrase at all, and only a
    phrase that cannot fit any line gets divided. Wider lines mean smaller type;
    a smaller headline reads, a headline broken mid-word does not.
    """
    phrases = [p for p in re.split(r"[，。！？、；：,.!?;:\s]+", title.strip()) if p]
    if not phrases:
        return [title.strip() or ""]

    def pack(width: int) -> tuple[list[str], bool]:
        lines, cur, split = [], "", False
        for phrase in phrases:
            while len(phrase) > width:          # cannot fit any line: divide it
                split = True
                parts = -(-len(phrase) // width)
                cut = -(-len(phrase) // parts)
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(phrase[:cut])
                phrase = phrase[cut:]
            if not cur:
                cur = phrase
            elif len(cur) + len(phrase) <= width:
                cur += phrase
            else:
                lines.append(cur)
                cur = phrase
        if cur:
            lines.append(cur)
        return lines, split

    widest = max(len(p) for p in phrases)
    # Narrowest width that needs no split and stays inside the budget: the
    # largest type that keeps every phrase whole.
    for width in range(widest, 25):
        lines, split = pack(width)
        if not split and len(lines) <= max_lines:
            return lines
    for width in range(9, 25):               # nothing fits whole; keep it short
        lines, _ = pack(width)
        if len(lines) <= max_lines:
            return lines
    return pack(24)[0][:max_lines]


def chapter_card(picture: Path | None, title: str, text: str, index: int,
                 total: int, source: str, out_path: Path, profile=None,
                 passage: Image.Image | None = None) -> Path:
    profile = profile or lang.get(None)
    canvas = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(canvas)
    top = _header(draw, index, total, title)
    bottom = H - FOOTER_H

    # Text first: it decides how much room is left, never the other way round.
    budget = bottom - top - MIN_PICTURE - GAP * 2
    lines, size, text_h = _fit(text, profile, budget)

    picture_box = (W - MARGIN * 2, bottom - top - text_h - GAP * 2)
    img = (ImageOps.contain(passage, picture_box, Image.Resampling.LANCZOS)
           if passage is not None else _picture(picture, picture_box))
    y = top
    if img:
        canvas.paste(img, ((W - img.width) // 2, y))
        y += img.height + GAP * 2
    else:
        y += GAP

    font = _body_font(size)
    for line in lines:
        draw.text((MARGIN, y), line.strip(), font=font, fill=INK)
        y += int(size * 1.62)

    _footer(draw, source)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def cover_card(title: str, out_path: Path, title_snippet: Path | None = None,
               journal: str | None = None, paper_title: str = "") -> Path:
    """The paper's own title, screenshotted, under the explainer's headline.

    No generated art: the one thing a cover must not do is invent a picture of a
    paper it is about to be accurate about."""
    canvas = Image.new("RGB", (W, H), CREAM)
    draw = ImageDraw.Draw(canvas)

    y = 96
    if journal:
        font = _body_font(34)
        pad = 18
        width = int(draw.textlength(journal, font=font))
        draw.rounded_rectangle([MARGIN, y, MARGIN + width + pad * 2, y + 58],
                               radius=29, fill=ACCENT)
        draw.text((MARGIN + pad, y + 10), journal, font=font, fill=(255, 250, 242))
        y += 92

    lines = _headline(" ".join((title or "").split()))
    longest = max((len(line) for line in lines), default=1)
    size = max(56, min(132, int((W - MARGIN * 2) * 0.98 / max(longest, 1))))
    y = _draw_playful_title(canvas, lines, _title_font(size), y) + 56

    if title_snippet and Path(title_snippet).exists():
        card = _paper_snippet_card(Path(title_snippet), W - MARGIN * 2)
        room = H - FOOTER_H - y - GAP
        if card.height > room:
            card = ImageOps.contain(card, (card.width, room), Image.Resampling.LANCZOS)
        canvas.paste(card, ((W - card.width) // 2, y), card)
    elif paper_title:
        font = _body_font(32)
        for line in lang.get(None).subtitle_lines(paper_title, W - MARGIN * 2, 32):
            draw.text((MARGIN, y), line.strip(), font=font, fill=MUTED)
            y += 52

    _footer(draw, "")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def _local(url: str, project_dir: Path) -> Path | None:
    """The file behind a manifest URL. /files/<pid>/x -> <project_dir>/x."""
    if not url:
        return None
    from urllib.parse import unquote
    tail = re.sub(r"^/files/[^/]+/", "", unquote(url))
    candidate = project_dir / tail
    return candidate if candidate.exists() else None


def render_deck(project_dir: Path, meta: dict, out_dir: Path | None = None,
                log=print, profile=None) -> list[Path]:
    """Cover plus one card a chapter, numbered so they sort the way they read."""
    manifest_path = project_dir / "explainer.json"
    if not manifest_path.exists():
        raise ValueError("还没有生成互动讲解，无法导出图文卡片")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    segments = manifest.get("segments") or []
    if not segments:
        raise ValueError("讲解里没有章节，无法导出图文卡片")

    profile = profile or lang.get(meta.get("lang"))
    out_dir = out_dir or project_dir / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("card_*.png"):
        stale.unlink()

    made = [cover_card(
        meta.get("title") or manifest.get("title") or "",
        out_dir / "card_00.png",
        title_snippet=project_dir / "images" / "title_snippet.png",
        journal=(meta.get("journal") or "").strip() or None,
        paper_title=meta.get("paper_title") or "")]
    total = len(segments)
    log(f"  图文卡片 {len(made)}/{total + 1}：封面")
    for i, segment in enumerate(segments, start=1):
        visual = segment.get("visual") or {}
        picture, passage = None, None
        if visual.get("kind") == "figure":
            picture = _local(visual.get("url", ""), project_dir)
        else:
            pages = visual.get("pages") or {}
            spots = [c["highlight"] for c in segment.get("cues", []) if c.get("highlight")]
            page = _local(next(iter(pages.values()), ""), project_dir)
            passage = _page_passage(page, spots)
            picture = page if passage is None else None
        made.append(chapter_card(
            picture, segment.get("title") or "", segment.get("summary") or "",
            i, total, segment.get("figure_source") or "",
            out_dir / f"card_{i:02d}.png", profile, passage=passage))
        log(f"  图文卡片 {len(made)}/{total + 1}：第{i}章")

    log(f"图文讲解卡片完成：{len(made)} 张 3:4 图片")
    return made


def export_zip(project_dir: Path, meta: dict, log=print, profile=None) -> Path:
    """The deck as one file, named so the cards keep their order anywhere."""
    import zipfile
    made = render_deck(project_dir, meta, log=log, profile=profile)
    path = project_dir / "aha-paper-cards.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for card in made:
            bundle.write(card, card.name)
    return path
