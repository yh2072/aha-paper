"""The interactive explainer, recorded as an MP4.

A frame-for-frame port of web/explainer-player.js: the narration is the clock,
each cue owns one visual state, and the camera, the marker on the page and the
pointer on a figure move exactly as they do on the watch page. The current cue
is burnt in underneath as a caption, so the video stands on its own.

Most of a narration is a settled page: once a cue's animation has finished
(about a second), its frame is reused until the next cue, and only figures --
where the pointer keeps breathing -- are redrawn every frame.
"""
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..bin import ffmpeg as ffmpeg_bin
from .cover import _body_font

FPS = 25
SIZE = (1920, 1080)
CAPTION_H = 150
SURROUND = (250, 248, 243)          # '#faf8f3', the player's stage
LANE, LANE_RULE, CAPTION_INK = (250, 248, 238), (227, 228, 213), (57, 78, 64)
CHAPTER_INK = (128, 146, 118)
MARGIN = 12                          # the player's 6px at dpr 2
SETTLED = 1.0                        # every page animation ends by here (camera .85, keys 1.0)

# Canvas 'multiply' at alpha a with colour c scales each channel by 1 - a + a*c/255.
MARKER = tuple(1 - .62 + .62 * c / 255 for c in (243, 216, 122))
KEY = tuple(1 - .5 + .5 * c / 255 for c in (240, 178, 64))
UNDERLINE = (166, 88, 24, 230)


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _valid(r) -> bool:
    return isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r) and r[2] > 0 and r[3] > 0


def _figure_crop(r):
    if not _valid(r) or r[2] * r[3] > .65:
        return [0, 0, 1, 1]
    w, h = min(1, max(.26, r[2] + .13)), min(1, max(.26, r[3] + .13))
    return [max(0, min(1 - w, r[0] + r[2] / 2 - w / 2)), max(0, min(1 - h, r[1] + r[3] / 2 - h / 2)), w, h]


def _page_crop(r):
    if not r:
        return [0, 0, 1, 1]
    w, h = min(1, max(.46, r[2] + .14)), min(1, max(.22, r[3] + .17))
    return [max(0, min(1 - w, r[0] + r[2] / 2 - w / 2)), max(0, min(1 - h, r[1] + r[3] / 2 - h / 2)), w, h]


def _bounds(rects):
    if not rects:
        return None
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    x1, y1 = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    return [x0, y0, x1 - x0, y1 - y0]


def _mix(a, b, s):
    return [x + (y - x) * s for x, y in zip(a, b)]


def local_path(base: Path, url: str) -> Path:
    """A manifest URL as a file in the project: the studio writes /files/<id>/x,
    the offline bundle writes x."""
    path = unquote(url)
    if path.startswith('/files/'):
        path = path.split('/', 3)[3]
    return base / path


def locate(segments: list[dict], time: float):
    """(segment index, time within it, cue index) -- the player's own lookup."""
    index = next((i for i, s in enumerate(segments) if s['start'] <= time < s['end']), None)
    if index is None:
        index = len(segments) - 1 if time > 0 else 0
    segment = segments[index]
    t = max(0.0, time - segment['start'])
    cues = segment.get('cues') or []
    cue = next((i for i, c in enumerate(cues) if c['start'] <= t < c['end']), None)
    if cue is None:
        cue = 0 if t <= 0 else len(cues) - 1
    return index, t, cue


class Renderer:
    def __init__(self, base: Path, manifest: dict, size=SIZE):
        self.base, self.data = Path(base), manifest
        self.W, self.H = size
        self.stage = (self.W, self.H - CAPTION_H)
        self.area = (MARGIN, MARGIN, self.stage[0] - MARGIN * 2, self.stage[1] - MARGIN * 2)
        self.pointer_size = max(48, min(self.stage[0] / 24, 78))
        self._static_key = self._static_frame = None
        self._base_key = self._base = None
        self._caption_key = self._caption = None

    # ── assets ──
    @lru_cache(maxsize=32)
    def image(self, url: str) -> Image.Image:
        return Image.open(local_path(self.base, url)).convert('RGB')

    @lru_cache(maxsize=8)
    def _locator_card(self, url: str):
        """The inset's paper card with its shadow, drawn once per image."""
        image = self.image(url)
        box = min(self.stage[0] * .16, self.stage[1] * .28)
        fit = min(box / image.width, box / image.height)
        w, h, pad, blur = round(image.width * fit), round(image.height * fit), 16, 22
        size = (w + pad * 2 + blur * 4, h + pad * 2 + blur * 4)
        shadow = Image.new('L', size, 0)
        ImageDraw.Draw(shadow).rectangle((blur * 2, blur * 2 + 4, blur * 2 + w + pad * 2, blur * 2 + 4 + h + pad * 2), fill=51)
        card = Image.new('RGBA', size, (42, 66, 52, 0))
        card.putalpha(shadow.filter(ImageFilter.GaussianBlur(blur / 2)))
        ImageDraw.Draw(card).rectangle((blur * 2, blur * 2, blur * 2 + w + pad * 2, blur * 2 + h + pad * 2), fill=(255, 253, 243, 255))
        thumb = Image.blend(Image.new('RGB', (w, h), (255, 253, 243)), image.resize((w, h), Image.LANCZOS), .85)
        card.paste(thumb, (blur * 2 + pad, blur * 2 + pad))
        return card, (w, h), pad, blur

    @lru_cache(maxsize=4)
    def _arrow(self, size: int) -> Image.Image:
        """The player's pointer arrow with its soft shadow, at 4x then reduced."""
        over, pad = 4, .5
        scale = size * over
        dim = round((1.5 + pad) * scale)
        pts = [((x + pad / 2) * scale, (y + pad / 2) * scale)
               for x, y in [(.12, .1), (.12, 1.08), (.38, .86), (.58, 1.26), (.77, 1.16), (.57, .78), (.91, .77)]]
        shadow = Image.new('L', (dim, dim), 0)
        ImageDraw.Draw(shadow).polygon([(x, y + 2 * over) for x, y in pts], fill=59)
        shadow = shadow.filter(ImageFilter.GaussianBlur(5 * over / 2))
        sprite = Image.new('RGBA', (dim, dim), (39, 66, 53, 0))
        sprite.putalpha(shadow)
        draw = ImageDraw.Draw(sprite)
        draw.polygon(pts, fill=(255, 253, 242, 255), outline=(65, 101, 83, 255), width=max(1, round(.055 * scale)))
        draw.line([((.25 + pad / 2) * scale, (.34 + pad / 2) * scale), ((.25 + pad / 2) * scale, (.67 + pad / 2) * scale)],
                  fill=(199, 185, 226, 255), width=max(1, round(.075 * scale)))
        return sprite.resize((dim // over, dim // over), Image.LANCZOS)

    # ── drawing ──
    def _place_image(self, frame: Image.Image, image: Image.Image, crop, white=False):
        """Draw the cropped image fitted into the stage; returns its (ix, iy, iw, ih)."""
        ax, ay, aw, ah = self.area
        sw, sh = crop[2] * image.width, crop[3] * image.height
        fit = min(aw / sw, ah / sh)
        iw, ih = sw * fit, sh * fit
        ix, iy = ax + (aw - iw) / 2, ay + (ah - ih) / 2
        box = (crop[0] * image.width, crop[1] * image.height, crop[0] * image.width + sw, crop[1] * image.height + sh)
        size = (max(1, round(iw)), max(1, round(ih)))
        piece = image.resize(size, Image.BILINEAR if crop[2] < 1 or crop[3] < 1 else Image.LANCZOS, box=box)
        if white:
            frame.paste((255, 255, 255), (round(ix), round(iy), round(ix) + size[0], round(iy) + size[1]))
        frame.paste(piece, (round(ix), round(iy)))
        return ix, iy, iw, ih

    def _locator(self, frame: Image.Image, url: str, r):
        card, (w, h), pad, blur = self._locator_card(url)
        W, H = self.stage
        x, y = W - 36 - pad - w, H - 36 - pad - h
        frame.paste(card, (round(x - pad - blur * 2), round(y - pad - blur * 2)), card)
        overlay = Image.new('RGBA', frame.size, (0, 0, 0, 0))
        rect = (x + r[0] * w, y + r[1] * h, x + (r[0] + r[2]) * w, y + (r[1] + r[3]) * h)
        ImageDraw.Draw(overlay).rectangle(rect, fill=(139, 166, 118, 56), outline=(127, 154, 111, 255), width=3)
        frame.paste(overlay, (0, 0), overlay)

    def _multiply(self, frame: Image.Image, rect, factor):
        ax, ay, aw, ah = self.area
        x0, y0 = max(round(rect[0]), ax), max(round(rect[1]), ay)
        x1, y1 = min(round(rect[2]), ax + aw), min(round(rect[3]), ay + ah)
        if x1 <= x0 or y1 <= y0:
            return
        region = frame.crop((x0, y0, x1, y1))
        tint = Image.new('RGB', region.size, tuple(round(255 * f) for f in factor))
        frame.paste(ImageChops.multiply(region, tint), (x0, y0))

    def draw_page(self, segment: dict, t: float, cue_index: int) -> Image.Image:
        cues = segment.get('cues') or []
        cue = cues[cue_index]
        pages = segment['visual'].get('pages') or {}
        spot = cue.get('highlight')
        url = pages.get(str(spot.get('page'))) if spot else None
        url = url or next(iter(pages.values()))
        image = self.image(url)
        frame = Image.new('RGB', self.stage, SURROUND)
        box = _bounds(spot.get('rects')) if spot else None
        prior = cues[cue_index - 1].get('highlight') if cue_index > 0 else None
        same = prior and spot and prior.get('page') == spot.get('page')
        target = _page_crop(box)
        before = _page_crop(_bounds(prior.get('rects'))) if same else target
        elapsed = max(0.0, t - cue['start'])
        crop = _mix(before, target, _ease(elapsed / .85))
        ix, iy, iw, ih = self._place_image(frame, image, crop, white=True)
        if spot and spot.get('rects'):
            def place(r):
                return (ix + (r[0] - crop[0]) / crop[2] * iw, iy + (r[1] - crop[1]) / crop[3] * ih,
                        r[2] / crop[2] * iw, r[3] / crop[3] * ih)
            wipe = min(1.0, max(0.0, elapsed / .55))
            for r in spot['rects']:
                x, y, w, h = place(r)
                pad = max(3, h * .26)
                self._multiply(frame, (x - pad * .6, y - pad, x - pad * .6 + w * wipe + pad * 1.2, y + h + pad), MARKER)
            lift = min(1.0, max(0.0, (elapsed - .5) / .5))
            keys = spot.get('keys') or [] if lift > 0 else []
            for k in keys:
                for r in k.get('rects') or []:
                    x, y, w, h = place(r)
                    pad = max(2.4, h * .2)
                    self._multiply(frame, (x - pad * .5, y - pad * .8, x - pad * .5 + w * lift + pad, y + h + pad * .8), KEY)
            if keys:
                overlay = Image.new('RGBA', frame.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                for k in keys:
                    for r in k.get('rects') or []:
                        x, y, w, h = place(r)
                        top = y + h + max(2, h * .09)
                        draw.rectangle((x, top, x + w * lift, top + max(3.6, h * .1)), fill=UNDERLINE)
                frame.paste(overlay, (0, 0), overlay)
        if (crop[2] < 1 or crop[3] < 1) and box:
            self._locator(frame, url, box)
        return frame

    def _figure_base(self, url: str, crop, region, zoomed: bool) -> tuple[Image.Image, tuple]:
        key = (url, tuple(round(v, 4) for v in crop), tuple(region) if zoomed and region else None)
        if key != self._base_key:
            frame = Image.new('RGB', self.stage, SURROUND)
            placed = self._place_image(frame, self.image(url), crop)
            if zoomed and region:
                self._locator(frame, url, region)
            self._base_key, self._base = key, (frame, placed)
        return self._base

    def draw_figure(self, segment: dict, t: float, cue_index: int) -> Image.Image:
        url = segment['visual']['url']
        cues = segment.get('cues') or []
        cue = cues[cue_index]
        prior_cue = cues[cue_index - 1] if cue_index > 0 else None
        valid = _valid(cue.get('region'))
        target = _figure_crop(cue.get('region'))
        before = _figure_crop(prior_cue.get('region') if prior_cue else None)
        elapsed = max(0.0, t - cue['start'])
        crop = _mix(before, target, _ease(elapsed / .9))
        zoomed = target[2] < 1 or target[3] < 1
        base, (ix, iy, iw, ih) = self._figure_base(url, crop, cue.get('region') if valid else None, zoomed)
        frame = base.copy()
        if valid:
            r = cue['region']
            goal = [r[0] + r[2] / 2, r[1] + r[3] / 2]
            pr = prior_cue.get('region') if prior_cue else None
            start = [pr[0] + pr[2] / 2, pr[1] + pr[3] / 2] if _valid(pr) else goal

            def point(when):
                s = _ease(when / .65)
                x = start[0] + (goal[0] - start[0]) * s + math.sin(when * 1.9) * min(r[2] * .045, .01) * s
                y = start[1] + (goal[1] - start[1]) * s + math.sin(when * 2.7) * min(r[3] * .04, .01) * s
                return ix + (x - crop[0]) / crop[2] * iw, iy + (y - crop[1]) / crop[3] * ih
            history = [point(max(0.0, elapsed - (7 - i) * .04)) for i in range(7)]
            self._pointer(frame, point(elapsed), history, t)
        return frame

    def _pointer(self, frame: Image.Image, at, history, t: float):
        size = self.pointer_size
        px, py = at
        radius = size * (.5 + .04 * math.sin(t * 4))
        # Ring and trail on a small supersampled patch around the pointer.
        over, half = 2, round(size * 1.6)
        patch = Image.new('RGBA', (half * 2 * over, half * 2 * over), (0, 0, 0, 0))
        draw = ImageDraw.Draw(patch)
        local = lambda x, y: ((x - px + half) * over, (y - py + half) * over)  # noqa: E731
        cx, cy = local(px, py)
        rr = radius * over
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(176, 207, 190, 43))
        start = math.degrees(t * .5)
        draw.arc((cx - rr, cy - rr, cx + rr, cy + rr), start, start + 1.58 * 180,
                 fill=(105, 150, 122, 158), width=max(1, round(2.4 * over)))
        for i, (x, y) in enumerate(history):
            hx, hy = local(x, y)
            dot = size * (.025 + .035 * i / 7) * over
            draw.ellipse((hx - dot, hy - dot, hx + dot, hy + dot), fill=(168, 155, 201, round(255 * (i + 1) / 18)))
        patch = patch.resize((half * 2, half * 2), Image.LANCZOS)
        frame.paste(patch, (round(px - half), round(py - half)), patch)
        arrow = self._arrow(round(size))
        frame.paste(arrow, (round(px - size * .12 - size * .25), round(py - size * .1 - size * .25)), arrow)

    def _caption_lane(self, segment_index: int, cue_index: int) -> Image.Image:
        key = (segment_index, cue_index)
        if key == self._caption_key:
            return self._caption
        segment = self.data['segments'][segment_index]
        cues = segment.get('cues') or []
        # Cues keep the script's paragraph breaks ("\n\n..."). The page's caption
        # collapses them as HTML does; Pillow cannot measure text that has them.
        text = re.sub(r'\s*[\r\n]+\s*', ' ', (cues[cue_index].get('text') if cues else '') or '').strip()
        lane = Image.new('RGB', (self.W, CAPTION_H), LANE)
        draw = ImageDraw.Draw(lane)
        draw.line((0, 0, self.W, 0), fill=LANE_RULE, width=2)
        label = f"{segment_index + 1} / {len(self.data['segments'])} · {' '.join(str(segment.get('title', '')).split())}"
        draw.text((36, 16), label, font=_body_font(22), fill=CHAPTER_INK)
        width = self.W - 160
        for size in (40, 36, 32, 28):
            font = _body_font(size)
            lines = _wrap(draw, text, font, width)
            if len(lines) <= 2:
                break
        lines = lines[:3]
        line_h = size * 1.45
        top = 52 + (CAPTION_H - 52 - line_h * len(lines)) / 2
        for i, line in enumerate(lines):
            w = draw.textlength(line, font=font)
            draw.text(((self.W - w) / 2, top + i * line_h), line, font=font, fill=CAPTION_INK)
        self._caption_key, self._caption = key, lane
        return lane

    def frame(self, time: float) -> bytes:
        segments = self.data['segments']
        index, t, cue_index = locate(segments, time)
        segment = segments[index]
        kind = segment['visual']['kind']
        cues = segment.get('cues') or []
        settled = kind == 'page' and cues and t - cues[cue_index]['start'] >= SETTLED
        key = (index, cue_index) if settled else None
        if key and key == self._static_key:
            return self._static_frame
        if not cues:
            stage = Image.new('RGB', self.stage, SURROUND)
        elif kind == 'page':
            stage = self.draw_page(segment, t, cue_index)
        else:
            stage = self.draw_figure(segment, t, cue_index)
        full = Image.new('RGB', (self.W, self.H), SURROUND)
        full.paste(stage, (0, 0))
        full.paste(self._caption_lane(index, cue_index), (0, self.H - CAPTION_H))
        data = full.tobytes()
        self._static_key, self._static_frame = key, data
        return data


def _wrap(draw, text: str, font, width: int) -> list[str]:
    """Greedy wrap that works for CJK (no spaces) and for English words."""
    lines, line = [], ''
    for token in _tokens(text):
        if line and draw.textlength(line + token, font=font) > width:
            lines.append(line.rstrip())
            line = token.lstrip()
        else:
            line += token
    if line:
        lines.append(line.rstrip())
    return lines


def _tokens(text: str):
    word = ''
    for ch in text:
        if ch.isascii() and not ch.isspace():
            word += ch
            continue
        if word:
            yield word
            word = ''
        yield ch
    if word:
        yield word


def render(project_dir: Path, out: Path, manifest_name: str = 'experience.json',
           log=print, progress=None, until: float | None = None) -> Path:
    """Write the explainer at project_dir as an H.264/AAC MP4 at out.

    until: stop after this many seconds (for checks); None renders all of it."""
    project_dir = Path(project_dir)
    manifest = json.loads((project_dir / manifest_name).read_text())
    if not manifest.get('segments'):
        raise ValueError('互动讲解没有章节，无法导出 MP4')
    audio = local_path(project_dir, manifest.get('audio') or 'narration.mp3')
    duration = float(manifest['duration'] if until is None else min(until, manifest['duration']))
    total = max(1, math.ceil(duration * FPS))
    renderer = Renderer(project_dir, manifest)
    partial = out.with_name(out.stem + '.partial.mp4')
    command = [ffmpeg_bin(), '-y', '-v', 'error',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{SIZE[0]}x{SIZE[1]}', '-r', str(FPS), '-i', 'pipe:0',
               '-i', str(audio), '-t', f'{duration:.3f}',
               '-map', '0:v', '-map', '1:a',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(partial)]
    log(f'  导出 MP4：{SIZE[0]}×{SIZE[1]} · {FPS} fps · {duration / 60:.1f} 分钟')
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    reported = -1
    try:
        for i in range(total):
            process.stdin.write(renderer.frame(i / FPS))
            percent = i * 100 // total
            if progress and percent // 5 != reported // 5:
                reported = percent
                progress(percent)
        process.stdin.close()
    except BrokenPipeError:
        pass  # ffmpeg stopped reading; its own error is reported below
    except BaseException:
        # A frame that cannot be drawn must not leave ffmpeg waiting on its
        # input, or half a video where the next export looks for one.
        process.kill()
        process.wait()
        process.stderr.close()
        partial.unlink(missing_ok=True)
        raise
    with process.stderr:
        error = process.stderr.read().decode(errors='replace')
    if process.wait():
        partial.unlink(missing_ok=True)
        raise RuntimeError(f'MP4 编码失败：{error[-500:]}')
    partial.replace(out)
    return out
