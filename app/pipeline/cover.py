"""爆款封面合成：AI 底图 + 大字标题（Pillow 排版，不依赖模型写字）。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1440  # 小红书 3:4 竖版

_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]

# 封面大标题用更 fancy 的展示字体（可在 .env 用 COVER_TITLE_FONT 换成任意字体路径）
import os as _os  # noqa: E402

_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
_YUANTI = ("/System/Library/AssetsV2/com_apple_MobileAsset_Font7/"
           "b86e58f38fd21e9782e70a104676f1655e72ebab.asset/AssetData/Yuanti.ttc")

_TITLE_FONT_CANDIDATES = [
    _os.getenv("COVER_TITLE_FONT", ""),
    str(_FONTS_DIR / "ZCOOLKuaiLe-Regular.ttf"),  # 站酷快乐体：手绘涂鸦感
    _YUANTI,
    *_FONT_CANDIDATES,
]

_BODY_FONT_CANDIDATES = [
    _os.getenv("COVER_BODY_FONT", ""),
    str(_FONTS_DIR / "LXGWWenKai-Medium.ttf"),    # 霞鹜文楷：温暖手写楷体
    _YUANTI,
    *_FONT_CANDIDATES,
]


def _body_font(size: int) -> ImageFont.FreeTypeFont:
    """正文/字幕字体。"""
    for path in filter(None, _BODY_FONT_CANDIDATES):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _title_font(size: int) -> ImageFont.FreeTypeFont:
    """加载标题字体，ttc 里优先挑最粗的一款。"""
    for path in filter(None, _TITLE_FONT_CANDIDATES):
        best = None
        for i in range(6):
            try:
                f = ImageFont.truetype(path, size=size, index=i)
            except OSError:
                break
            sub = f.getname()[1]
            if best is None or "Bold" in sub or "W6" in sub or "Heavy" in sub:
                best = f
        if best is not None:
            return best
    return ImageFont.load_default(size=size)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size, index=1)
        except Exception:  # noqa: BLE001
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default(size=size)


def _wrap(text: str, max_per_line: int) -> list[str]:
    return [text[i:i + max_per_line] for i in range(0, len(text), max_per_line)] or [""]


def _split_title(title: str) -> list[str]:
    """标题按标点断句成行；超长的短语再对半均分，避免行首标点和孤字。"""
    import re
    phrases = [p for p in re.split(r"[，。！？、；：,.!?;:\s]+", title.strip()) if p]
    lines: list[str] = []
    for p in phrases or [title.strip()]:
        if len(p) <= 8:
            lines.append(p)
        else:  # 均分成尽量等长的两三行
            n = 2 if len(p) <= 16 else 3
            step = -(-len(p) // n)
            lines += _wrap(p, step)
    return lines[:3]


def _paper_snippet_card(snippet_path: Path, max_w: int) -> Image.Image:
    """论文标题截图 → 白色纸片卡 + 「📄 本期论文」红标签（程序合成，非 AI 生成）。"""
    from PIL import ImageOps  # noqa: PLC0415
    snip = Image.open(snippet_path).convert("RGB")
    snip = ImageOps.contain(snip, (max_w - 56, 360))
    card = Image.new("RGB", (snip.width + 56, snip.height + 48), (255, 255, 255))
    card.paste(snip, (28, 24))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, card.width - 1, card.height - 1],
                outline=(225, 214, 196), width=2)
    card = card.convert("RGBA").rotate(-1.4, expand=True,
                                       resample=Image.BICUBIC)  # 微斜贴纸感
    # 柔和投影
    shadow = Image.new("RGBA", (card.width + 40, card.height + 40), (0, 0, 0, 0))
    alpha = card.split()[3].point(lambda a: a * 0.35)
    shadow.paste((60, 42, 33, 90), (24, 26), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    shadow.paste(card, (12, 8), card)
    return shadow


# 可爱标题的轮换色（暖色系、都压得住奶油底）
_PLAYFUL_COLORS = [(201, 92, 74), (219, 150, 47), (114, 148, 86), (98, 134, 170)]
_CREAM = (252, 247, 236)


def _draw_playful_title(img: Image.Image, lines: list[str],
                        font: ImageFont.FreeTypeFont, y: int) -> int:
    """手账风标题：逐字换色 + 微旋转错落 + 厚奶油描边 + 柔和投影。返回结束 y。"""
    import math  # noqa: PLC0415
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 6
    stroke = max(8, font.size // 11)
    fallback = None  # 快乐体偶有缺字 → 该字回退圆体
    ci = 0
    for line in lines:
        advances = [ImageDraw.Draw(img).textlength(ch, font=font) for ch in line]
        total = sum(advances)
        x = (img.width - total) / 2
        for k, raw_ch in enumerate(line):
            ch = raw_ch
            char_font = font
            if font.getmask(ch).getbbox() is None and ch.strip():
                if fallback is None:
                    try:
                        fallback = ImageFont.truetype(_YUANTI, font.size)
                    except OSError:
                        fallback = font
                char_font = fallback
            pad = stroke + font.size // 3
            side = int(font.size + pad * 2 + descent)
            layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text(
                (pad, pad - font.size // 8), ch, font=char_font,
                fill=(*_PLAYFUL_COLORS[ci % 4], 255),
                stroke_width=stroke, stroke_fill=(*_CREAM, 255))
            angle = 5.5 * math.sin(k * 1.7 + len(line))   # 每字微旋转，错落但可控
            layer = layer.rotate(angle, resample=Image.BICUBIC, expand=False)
            bounce = int(font.size * 0.07 * math.sin(k * 2.1))  # 波浪 baseline
            px = int(x + advances[k] / 2 - side / 2)
            py = int(y + bounce - (pad - font.size // 8))  # 抵消图层内边距，对齐真实行高
            shadow = layer.split()[3].point(lambda a: int(a * 0.30))
            img.paste((150, 112, 82), (px + 5, py + 7), shadow.filter(ImageFilter.GaussianBlur(5)))
            img.paste(layer, (px, py), layer)
            x += advances[k] * 0.97  # 轻微紧排更俏皮
            ci += 1
        y += line_h
    return y + 26


def _cutout_subject(img: Image.Image) -> Image.Image | None:
    """白底图 → 镂空贴纸：从四角泛洪填充抠掉边缘连通的白底（保住眼白等内部白色）。

    背景不是近白色时返回 None（调用方走别的路）。
    """
    import numpy as np  # noqa: PLC0415
    im = img.convert("RGB")
    a = np.asarray(im)
    corners = [a[2, 2], a[2, -3], a[-3, 2], a[-3, -3]]
    if min(int(c.min()) for c in corners) < 195:
        return None
    work = im.copy()
    marker = (255, 0, 255)
    for xy in [(0, 0), (im.width - 1, 0), (0, im.height - 1),
               (im.width - 1, im.height - 1)]:
        ImageDraw.floodfill(work, xy, marker, thresh=52)
    wa = np.asarray(work)
    bg = (wa[:, :, 0] == 255) & (wa[:, :, 1] == 0) & (wa[:, :, 2] == 255)
    if bg.mean() < 0.08:  # 几乎没抠掉东西 → 背景并非纯色
        return None
    alpha = Image.fromarray(np.where(bg, 0, 255).astype("uint8"))
    alpha = alpha.filter(ImageFilter.GaussianBlur(1.4))
    out = img.convert("RGBA")
    out.putalpha(alpha)
    # 有效内容 bbox：忽略零星杂点（不足 8 个实心像素的行/列不算内容）
    am = np.asarray(alpha)
    rows = (am > 60).sum(axis=1) > 8
    cols = (am > 60).sum(axis=0) > 8
    if rows.any() and cols.any():
        y0 = int(np.argmax(rows))
        y1 = int(len(rows) - np.argmax(rows[::-1]))
        x0 = int(np.argmax(cols))
        x1 = int(len(cols) - np.argmax(cols[::-1]))
        out = out.crop((x0, y0, x1, y1))
    return out


def _figure_polaroid(fig_path: Path, max_w: int) -> Image.Image:
    """代表性主图 → 白框拍立得相片卡（微斜 + 柔影 + 和纸胶带），封面第二主角。"""
    from PIL import ImageOps  # noqa: PLC0415
    fig = Image.open(fig_path).convert("RGB")
    fig = ImageOps.contain(fig, (max_w - 44, 430))
    card = Image.new("RGB", (fig.width + 44, fig.height + 62), (255, 255, 255))
    card.paste(fig, (22, 20))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, card.width - 1, card.height - 1],
                outline=(228, 218, 200), width=2)
    card = card.convert("RGBA").rotate(2.4, expand=True, resample=Image.BICUBIC)

    # 一小条亮珊瑚"和纸胶带"骑在卡片顶边正中，像手账里贴上去的
    tape = Image.new("RGBA", (max(card.width // 4, 130), 46), (0, 0, 0, 0))
    ImageDraw.Draw(tape).rounded_rectangle([0, 0, tape.width - 1, 45], radius=6,
                                           fill=(228, 142, 122, 210))
    tape = tape.rotate(-4, expand=True, resample=Image.BICUBIC)

    shadow = Image.new("RGBA", (card.width + 40, card.height + 46), (0, 0, 0, 0))
    alpha = card.split()[3].point(lambda a: int(a * 0.38))
    shadow.paste((60, 42, 33, 95), (22, 28), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    card_x, card_y = 10, 22
    shadow.paste(card, (card_x, card_y), card)
    # 探测卡片中线处的真实顶边（旋转后与包围盒不重合），让胶带正好骑上去
    import numpy as np  # noqa: PLC0415
    a = np.asarray(card.split()[3])
    col = a[:, card.width // 2]
    top_row = int(np.argmax(col > 10)) if (col > 10).any() else 0
    shadow.paste(tape, (card_x + card.width // 2 - tape.width // 2,
                        card_y + top_row - tape.height // 2 + 8), tape)
    return shadow


def _circle_avatar(face_path: Path, d: int) -> Image.Image:
    """头像圆形角标：中心裁方 → 圆形蒙版（超采样抗锯齿）→ 白描边 → 柔影。"""
    from PIL import ImageOps  # noqa: PLC0415
    face = Image.open(face_path).convert("RGB")
    side = min(face.size)
    face = face.crop(((face.width - side) // 2, (face.height - side) // 2,
                      (face.width + side) // 2, (face.height + side) // 2))
    face = face.resize((d, d), Image.LANCZOS)
    big = d * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    face.putalpha(mask)
    ring = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([4, 4, d - 5, d - 5],
                                 outline=(255, 255, 255, 255), width=9)
    face.alpha_composite(ring)
    out = Image.new("RGBA", (d + 36, d + 36), (0, 0, 0, 0))
    shadow = face.split()[3].point(lambda a: int(a * 0.35))
    out.paste((60, 42, 33), (22, 26), shadow.filter(ImageFilter.GaussianBlur(9)))
    out.paste(face, (12, 10), face)
    return out


def compose_cover(art_path: Path, title: str, subtitle: str, out_path: Path,
                  title_snippet: Path | None = None,
                  journal: str | None = None,
                  main_figure: Path | None = None,
                  avatar_face: Path | None = None) -> Path:
    title = " ".join((title or "").split())      # 防换行符（Pillow 不接受多行 textlength）
    subtitle = " ".join((subtitle or "").split())
    # 拼贴布局：纯白底 → 期刊标签+标题 → 论文卡 → 镂空角色贴纸 ⤫ 主图拍立得
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = _split_title(title)
    longest = max(len(l) for l in lines)
    size = max(88, min(160, int(W * 0.88 / max(longest, 1))))
    # 左上角：期刊小标签（微旋转贴纸感）——低调但一眼可见
    title_top = 72
    if journal:
        jfont = _title_font(40)
        jt = journal.strip()
        tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        jw = tmp.textlength(jt, font=jfont)
        pill = Image.new("RGBA", (int(jw) + 64, 70), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pill)
        pd.rounded_rectangle([0, 0, pill.width - 1, 69], radius=24,
                             fill=(98, 134, 170, 255),
                             outline=(252, 247, 236, 255), width=4)
        pd.text((32, 12), jt, font=jfont, fill=(255, 250, 242))
        pill = pill.rotate(-2.5, expand=True, resample=Image.BICUBIC)
        shadow = pill.split()[3].point(lambda a: int(a * 0.25))
        img.paste((140, 105, 75), (32, 34),
                  shadow.filter(ImageFilter.GaussianBlur(5)))
        img.paste(pill, (28, 28), pill)
        title_top = 128

    # 大标题（无副标题，留出呼吸感）
    font = _title_font(size)
    y = _draw_playful_title(img, lines, font, title_top)

    # 全拼贴手账排版：论文卡 → 底部左右两张微斜贴纸（插画 + 主图拍立得）互相叠压
    import math  # noqa: PLC0415
    from PIL import ImageOps  # noqa: PLC0415
    from .slideshow import _trim_uniform_border  # noqa: PLC0415
    card = None
    y_card = y  # 紧贴标题下方
    if title_snippet and Path(title_snippet).exists():
        # 论文标题截图：白底直接融入白色背景，无边框无投影
        snip = Image.open(title_snippet).convert("RGB")
        snip = ImageOps.contain(snip, (int(W * 0.94), 420), method=Image.LANCZOS)
        card = snip.convert("RGBA")

    # 奶油底上撒几颗小星星，填补留白
    deco_y0 = y_card + (card.height if card else 0)
    for j, (fx, fy, r) in enumerate([(0.07, 0.30, 15), (0.90, 0.14, 12),
                                     (0.05, 0.88, 11), (0.95, 0.55, 16),
                                     (0.50, 0.97, 10)]):
        cx_, cy_ = fx * W, deco_y0 + fy * (H - deco_y0)
        pts = []
        for k in range(8):
            rad = r if k % 2 == 0 else r * 0.42
            ang = math.pi / 4 * k
            pts.append((cx_ + rad * math.cos(ang), cy_ + rad * math.sin(ang)))
        draw.polygon(pts, fill=_PLAYFUL_COLORS[j % 4])

    if card is not None:
        img.paste(card, ((W - card.width) // 2, y_card), card)

    # 插画：镂空贴纸（透明背景、无边框），角色直接"站"在纸上
    art_raw = Image.open(art_path)
    cut = _cutout_subject(art_raw)
    if cut is not None:
        sticker = cut
    else:  # 背景抠不掉（旧素材带场景）→ 退回圆角裁切，但不加白框
        art = _trim_uniform_border(art_raw.convert("RGB"))
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, *art.size], radius=48, fill=255)
        sticker = art.convert("RGBA")
        sticker.putalpha(mask)
    card_bottom = y_card + (card.height if card else 0)
    target_w = int(W * 0.60)  # AI 贴纸适当缩小
    target_h = int(target_w * sticker.height / sticker.width)
    max_h = H - card_bottom - 4
    if target_h > max_h:
        target_h = max_h
        target_w = int(target_h * sticker.width / sticker.height)
    sticker = sticker.resize((target_w, target_h), Image.LANCZOS)
    sticker = sticker.rotate(-2.4, expand=True, resample=Image.BICUBIC)
    x_pos, y_pos = -24, card_bottom + 2

    # 主图（先画，垫在 AI 贴纸下层）：不透明、更大、右侧偏上
    if main_figure and Path(main_figure).exists():
        fig = Image.open(main_figure).convert("RGB")
        fig = ImageOps.contain(fig, (int(W * 0.66), 560), method=Image.LANCZOS)
        fx_pos = W - fig.width - 16
        fy_pos = card_bottom + 60  # 偏上：紧随论文卡下方，而不是沉底
        img.paste(fig, (fx_pos, fy_pos))
        tape = Image.new("RGBA", (max(fig.width // 4, 130), 46), (0, 0, 0, 0))
        ImageDraw.Draw(tape).rounded_rectangle([0, 0, tape.width - 1, 45], radius=6,
                                               fill=(228, 142, 122, 205))
        tape = tape.rotate(-4, expand=True, resample=Image.BICUBIC)
        img.paste(tape, (fx_pos + fig.width // 2 - tape.width // 2,
                         fy_pos - tape.height // 2 + 6), tape)

    # AI 贴纸后画，压在主图上层
    s_shadow = sticker.split()[3].point(lambda a: int(a * 0.30))
    img.paste((60, 42, 33), (x_pos + 12, y_pos + 14),
              s_shadow.filter(ImageFilter.GaussianBlur(12)))
    img.paste(sticker, (x_pos, y_pos), sticker)

    if avatar_face and Path(avatar_face).exists():
        # 右下角圆形头像角标（叠在最上层）
        bub = _circle_avatar(Path(avatar_face), d=400)  # 放大：封面主视觉之一
        img.paste(bub, (W - bub.width + 8, H - bub.height + 6), bub)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)
    return out_path
