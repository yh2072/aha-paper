"""The cover without an image model: an open-source icon on the paper's colours.

Used when AI covers are switched off, when no image provider is connected, or
when the image API fails. It costs nothing and cannot fail on a network, so a
whole run no longer stops at its last step for want of a picture.

The icons are Lucide's (ISC, app/assets/LICENSE-lucide.txt): strokes on a
24x24 grid. Pillow cannot read SVG, and Lucide uses only a handful of shapes,
so they are flattened to polylines here and stroked with round ends -- the
look Lucide specifies -- at 4x and scaled down for clean edges.
"""
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from .. import config, llm
from . import art_cover

ICONS = config.ROOT / 'app' / 'assets' / 'lucide-icons.json'
FALLBACK = 'book-open-text'
SIZE = (1080, 1440)                   # the same 3:4 canvas the AI cover is cut to
PAPER, INK = '#f7f5ee', '#365943'
# Soft discs behind the icon, from the studio palette; the title picks one, so
# covers in a list are told apart by colour as well as by shape.
TINTS = ('#e3edcc', '#efe4c8', '#e4e3ef', '#dde8de', '#f0dfd6')


@lru_cache(maxsize=1)
def icons() -> dict:
    return json.loads(ICONS.read_text())['icons']


# ── SVG shapes to polylines ──────────────────────────────────────────────────

_TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
STEPS = 24  # segments per curve or arc; at cover size this is smooth


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """Points along an SVG elliptical arc (endpoint form, SVG 1.1 F.6.5)."""
    if rx == 0 or ry == 0 or (x1, y1) == (x2, y2):
        return [(x2, y2)]
    rx, ry, cos, sin = abs(rx), abs(ry), math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    xp, yp = cos * dx + sin * dy, -sin * dx + cos * dy
    scale = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
    root = math.sqrt(max(0.0, num / (rx * rx * yp * yp + ry * ry * xp * xp)))
    if large == sweep:
        root = -root
    cxp, cyp = root * rx * yp / ry, -root * ry * xp / rx
    cx = cos * cxp - sin * cyp + (x1 + x2) / 2
    cy = sin * cxp + cos * cyp + (y1 + y2) / 2
    start = math.atan2((yp - cyp) / ry, (xp - cxp) / rx)
    delta = math.atan2((-yp - cyp) / ry, (-xp - cxp) / rx) - start
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    out = []
    for i in range(1, STEPS + 1):
        t = start + delta * i / STEPS
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cos * x - sin * y + cx, sin * x + cos * y + cy))
    return out


def _bezier(points):
    """Points along a quadratic or cubic Bézier, excluding its start."""
    out = []
    for i in range(1, STEPS + 1):
        t, ps = i / STEPS, list(points)
        while len(ps) > 1:  # de Casteljau
            ps = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(ps, ps[1:])]
        out.append(ps[0])
    return out


def path_lines(d: str) -> list[tuple[list, bool]]:
    """An SVG path as (points, closed) subpaths."""
    tokens, i = _TOKEN.findall(d), 0
    lines, current, cmd = [], [], None
    x = y = sx = sy = 0.0
    last_ctrl = None  # (x, y, kind) of the previous curve's last control point

    def num():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def flag():
        # Arc flags may be packed against the next number: "a1 1 0 01.5.5".
        nonlocal i
        token = tokens[i]
        if len(token) > 1 and token[0] in '01':
            tokens[i] = token[1:]
            return int(token[0])
        i += 1
        return int(float(token))

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in 'Zz':
                if current:
                    lines.append((current, True))
                current, x, y, last_ctrl = [], sx, sy, None
                continue
        rel = cmd.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        kind = cmd.upper()
        if kind == 'M':
            if current:
                lines.append((current, False))
            x, y = num() + ox, num() + oy
            sx, sy, current = x, y, [(x, y)]
            cmd = 'l' if rel else 'L'  # further pairs are line-tos
            last_ctrl = None
            continue
        if not current:
            current = [(x, y)]
        if kind == 'L':
            x, y = num() + ox, num() + oy
            current.append((x, y))
            last_ctrl = None
        elif kind == 'H':
            x = num() + ox
            current.append((x, y))
            last_ctrl = None
        elif kind == 'V':
            y = num() + oy
            current.append((x, y))
            last_ctrl = None
        elif kind in 'CS':
            if kind == 'C':
                c1 = (num() + ox, num() + oy)
            else:  # reflect the previous cubic's second control point
                c1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl and last_ctrl[2] == 'C' else (x, y)
            c2 = (num() + ox, num() + oy)
            end = (num() + ox, num() + oy)
            current += _bezier([(x, y), c1, c2, end])
            last_ctrl, (x, y) = (*c2, 'C'), end
        elif kind in 'QT':
            if kind == 'Q':
                c = (num() + ox, num() + oy)
            else:
                c = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl and last_ctrl[2] == 'Q' else (x, y)
            end = (num() + ox, num() + oy)
            current += _bezier([(x, y), c, end])
            last_ctrl, (x, y) = (*c, 'Q'), end
        elif kind == 'A':
            rx, ry, phi = num(), num(), num()
            large, sweep = flag(), flag()
            end = (num() + ox, num() + oy)
            current += _arc(x, y, rx, ry, phi, large, sweep, *end)
            (x, y), last_ctrl = end, None
        else:
            raise ValueError(f'Unsupported path command {cmd!r}')
    if current:
        lines.append((current, False))
    return lines


def _ellipse(cx, cy, rx, ry):
    return [(cx + rx * math.cos(2 * math.pi * i / 72), cy + ry * math.sin(2 * math.pi * i / 72)) for i in range(72)]


def shape_lines(tag: str, a: dict) -> list[tuple[list, bool]]:
    f = lambda k, default=0.0: float(a.get(k, default))  # noqa: E731
    if tag == 'path':
        return path_lines(a['d'])
    if tag == 'circle':
        return [(_ellipse(f('cx'), f('cy'), f('r'), f('r')), True)]
    if tag == 'ellipse':
        return [(_ellipse(f('cx'), f('cy'), f('rx'), f('ry')), True)]
    if tag == 'line':
        return [([(f('x1'), f('y1')), (f('x2'), f('y2'))], False)]
    if tag in ('polyline', 'polygon'):
        values = [float(v) for v in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', a['points'])]
        return [(list(zip(values[::2], values[1::2])), tag == 'polygon')]
    if tag == 'rect':
        x, y, w, h = f('x'), f('y'), f('width'), f('height')
        rx = min(f('rx', a.get('ry', 0)), w / 2)
        ry = min(f('ry', a.get('rx', 0)), h / 2)
        if not rx and not ry:
            return [([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
        d = (f'M{x + rx} {y}H{x + w - rx}A{rx} {ry} 0 0 1 {x + w} {y + ry}V{y + h - ry}'
             f'A{rx} {ry} 0 0 1 {x + w - rx} {y + h}H{x + rx}A{rx} {ry} 0 0 1 {x} {y + h - ry}'
             f'V{y + ry}A{rx} {ry} 0 0 1 {x + rx} {y}Z')
        return path_lines(d)
    raise ValueError(f'Unsupported icon element {tag!r}')


def render(name: str, size: int, color: str = INK, stroke: float = 1.6) -> Image.Image:
    """One icon as a transparent square image, stroked the way Lucide draws it."""
    over = 4
    scale = size * over / 24
    width = stroke * scale
    image = Image.new('L', (size * over, size * over), 0)
    draw = ImageDraw.Draw(image)
    radius = width / 2
    for tag, attrs in icons()[name]:
        for points, closed in shape_lines(tag, attrs):
            pts = [(px * scale, py * scale) for px, py in points]
            if closed:
                pts.append(pts[0])
            if len(pts) > 1:
                draw.line(pts, fill=255, width=round(width))
            # A disc at every vertex gives round joins and caps, and draws
            # Lucide's zero-length "dots" (M12 12h.01) as dots.
            for px, py in pts:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=255)
    mask = image.resize((size, size), Image.LANCZOS)
    out = Image.new('RGBA', (size, size), color)
    out.putalpha(mask)
    return out


# ── the cover ────────────────────────────────────────────────────────────────

def choose_icon(meta: dict, log=print) -> str:
    """The icon closest to what the paper is about, picked by the language model
    from the vendored list. One short text call; any failure uses the fallback."""
    topic = ' / '.join(filter(None, (meta.get('paper_title'), meta.get('title'),
                                     (meta.get('storyboard') or {}).get('cover_prompt'))))
    if not topic:
        return FALLBACK
    names = sorted(icons())
    try:
        answer = llm.chat_json([{'role': 'user', 'content':
            'Pick the single icon that best stands for what this paper is about, as a '
            'reader would recognise it at a glance.\n'
            f'Paper: {topic[:600]}\n'
            f'Icons: {", ".join(names)}\n'
            'Reply with JSON only: {"icon": "<one name from the list>"}'}], temperature=0.2)
        name = answer.get('icon') if isinstance(answer, dict) else None
        if name in icons():
            return name
        log(f'  图标封面：模型给出的 {name!r} 不在列表里，用默认图标')
    except Exception as error:  # noqa: BLE001 - a cover never stops the run
        log(f'  图标封面：选图标失败（{error}），用默认图标')
    return FALLBACK


def draw_art(name: str, title: str) -> Image.Image:
    """The cover without its title: paper, one tinted disc, the icon on it.
    The upper part is left empty for art_cover.compose to set the title in."""
    canvas = Image.new('RGB', SIZE, PAPER)
    draw = ImageDraw.Draw(canvas)
    tint = TINTS[int(hashlib.sha1(title.encode()).hexdigest(), 16) % len(TINTS)]
    cx, cy, r = SIZE[0] // 2, 930, 360
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tint)
    icon = render(name, 440, stroke=1.25)
    canvas.paste(icon, (cx - 220, cy - 220), icon)
    return canvas


def generate(meta: dict, out_dir: Path, log=print, icon: str | None = None) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = icon or choose_icon(meta, log)
    title = meta.get('title') or meta.get('paper_title') or ''
    log(f'  图标封面 · Lucide {name}')
    draw_art(name, title).save(out_dir / 'cover_art.png')
    # The icon is recorded so a title change re-sets the same cover for free.
    (out_dir / 'cover_prompt.json').write_text(json.dumps({'engine': 'icon', 'icon': name}, ensure_ascii=False))
    art_cover.compose(out_dir / 'cover_art.png', meta, out_dir / 'cover.png')
    return 'cover.png'
