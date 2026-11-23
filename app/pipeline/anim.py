"""Shared aha-paper pointer rendering: ivory arrow, sage halo, and lilac motion trail.
Guided and cyclic figure explanations use the same antialiased visual style.
"""
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from ..bin import ffmpeg as ffmpeg_bin

FPS = 15
SECONDS = 3.2          # 一圈游走的周期（首尾闭合，无缝循环）
STYLE_VERSION = "sage-paper-v2"


def _cursor_layer(size: int) -> Image.Image:
    """Supersampled ivory pointer with sage outline and a soft lifted shadow."""
    scale = 4
    w, h = int(size * 1.2), int(size * 1.55)
    layer = Image.new("RGBA", (w * scale, h * scale))
    pts = [(0.12,0.1),(0.12,1.08),(0.38,0.86),(0.58,1.26),
           (0.77,1.16),(0.57,0.78),(0.91,0.77)]
    points = [(int(x*size*scale),int(y*size*scale)) for x,y in pts]
    shadow = Image.new("RGBA",layer.size)
    ImageDraw.Draw(shadow).polygon([(x+scale*2,y+scale*4) for x,y in points],fill=(39,66,53,70))
    layer = Image.alpha_composite(layer,shadow.filter(ImageFilter.GaussianBlur(2.2*scale)))
    draw=ImageDraw.Draw(layer)
    draw.polygon(points, fill=(255,253,242,255))
    draw.line(points+[points[0]],fill=(65,101,83,255),width=max(5,int(size*.055*scale)),joint="curve")
    draw.line([(int(size*.25*scale),int(size*.34*scale)),
               (int(size*.25*scale),int(size*.67*scale))],fill=(199,185,226,255),width=max(4,int(size*.09*scale)))
    return layer.resize((w,h),Image.Resampling.LANCZOS)


def _paint_pointer(img, point, history, t, size, cursor):
    """Quiet sage halo, lilac motion beads, and a paper-white editorial pointer."""
    px,py=point
    fx=Image.new("RGBA",img.size)
    draw=ImageDraw.Draw(fx)
    radius=size*(.50+.055*math.sin(t*math.pi*1.35))
    draw.ellipse((px-radius,py-radius,px+radius,py+radius),fill=(176,207,190,38))
    draw.arc((px-radius,py-radius,px+radius,py+radius),
             start=(t*30)%360,end=(t*30)%360+285,fill=(105,150,122,140),width=max(1,size//26))
    for j,(hx,hy) in enumerate(history):
        fade=(j+1)/max(len(history),1)
        rr=size*(.025+.035*fade)
        draw.ellipse((hx-rr,hy-rr,hx+rr,hy+rr),fill=(168,155,201,int(105*fade)))
    dot=max(2,size*.045)
    draw.ellipse((px-dot,py-dot,px+dot,py+dot),fill=(221,163,117,210))
    frame=Image.alpha_composite(img.convert("RGBA"),fx)
    frame.alpha_composite(cursor,(int(px-size*.12),int(py-size*.1)))
    return frame.convert("RGB")


def _path(t: float, cx: float, cy: float, rx: float, ry: float) -> tuple[float, float]:
    """8 字形游走轨迹，t∈[0,1) 首尾闭合。"""
    return (cx + rx * math.sin(2 * math.pi * t + 0.7),
            cy + ry * math.sin(4 * math.pi * t))


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def render_guided_pointer(fig_path: Path, segments: list[tuple[float, list | None]],
                          out_mp4: Path, log=print) -> Path:
    """跟随讲解的光标：segments = [(该句时长, 该句讲的区域bbox或None)]。

    每句开头 0.7s 光标平滑滑到该句区域，随后在区域内小幅游走；
    None 区域 = 停在原处轻微悬浮。非循环，总长 = 各句时长之和。
    """
    img = Image.open(fig_path).convert("RGB")
    W, H = img.size
    W -= W % 2
    H -= H % 2
    img = img.crop((0, 0, W, H))
    size = max(38, min(W // 18, 100))
    cursor = _cursor_layer(size)

    def center(bb):
        return ((bb[0] + bb[2] / 2) * W, (bb[1] + bb[3] / 2) * H)

    # 预计算每一帧的光标位置（含跨句平滑过渡）
    pos = (W * 0.5, H * 0.55)
    points: list[tuple[float, float]] = []
    for dur, bb in segments:
        n = max(int(dur * FPS), 1)
        if bb:
            tgt = center(bb)
            rx = bb[2] * W / 2 * 0.18
            ry = bb[3] * H / 2 * 0.15
        else:
            tgt = pos
            rx, ry = size * 0.5, size * 0.35
        glide = min(int(0.7 * FPS), max(n - 1, 1))
        start = pos
        for k in range(n):
            if k < glide:
                a = _smoothstep(k / glide)
                p = (start[0] + (tgt[0] - start[0]) * a,
                     start[1] + (tgt[1] - start[1]) * a)
            else:
                t = (k - glide) / FPS / 3.2  # 到位后小幅 8 字悬浮
                p = (tgt[0] + rx * math.sin(2 * math.pi * t + 0.7),
                     tgt[1] + ry * math.sin(4 * math.pi * t))
            points.append(p)
            pos = p

    work = out_mp4.parent / (out_mp4.stem + "_frames")
    work.mkdir(parents=True, exist_ok=True)
    for k, (px, py) in enumerate(points):
        t = k / FPS
        history=[points[max(k-j*2,0)] for j in range(7,0,-1)]
        frame=_paint_pointer(img,(px,py),history,t,size,cursor)
        frame.save(work / f"f_{k:04d}.png")

    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-framerate", str(FPS), "-i", str(work / "f_%04d.png"),
         "-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p", str(out_mp4)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"光标动画编码失败: {proc.stderr[-400:]}")
    for f in work.glob("f_*.png"):
        f.unlink()
    work.rmdir()
    log(f"  跟随式光标动画 {out_mp4.name}（{len(points)}帧）✓")
    return out_mp4


def render_pointer_cycle(fig_path: Path, bbox: list[float], out_mp4: Path,
                         log=print) -> Path:
    img = Image.open(fig_path).convert("RGB")
    W, H = img.size
    W -= W % 2
    H -= H % 2
    img = img.crop((0, 0, W, H))

    # 光标在相关子图范围内游走
    x1, y1 = bbox[0] * W, bbox[1] * H
    x2, y2 = (bbox[0] + bbox[2]) * W, (bbox[1] + bbox[3]) * H
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = (x2 - x1) / 2 * 0.62, (y2 - y1) / 2 * 0.55

    size = max(38, min(W // 18, 100))
    cursor = _cursor_layer(size)

    n_frames = int(FPS * SECONDS)
    work = out_mp4.parent / (out_mp4.stem + "_frames")
    work.mkdir(parents=True, exist_ok=True)
    for k in range(n_frames):
        t = k / n_frames
        px,py=_path(t,cx,cy,rx,ry)
        history=[_path((t-j*.022)%1,cx,cy,rx,ry) for j in range(7,0,-1)]
        frame=_paint_pointer(img,(px,py),history,t*SECONDS,size,cursor)
        frame.save(work / f"f_{k:03d}.png")

    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-framerate", str(FPS), "-i", str(work / "f_%03d.png"),
         "-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p", str(out_mp4)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"光标动画编码失败: {proc.stderr[-400:]}")
    for f in work.glob("f_*.png"):
        f.unlink()
    work.rmdir()
    log(f"  光标动画 {out_mp4.name} ✓")
    return out_mp4
