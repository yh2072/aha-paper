"""ffmpeg 自动剪辑：在每个场景的时间段把配图以圆角卡片形式浮层进画面（带淡入淡出）。"""
import json
import subprocess
from pathlib import Path
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin

FADE = 0.4       # 淡入淡出时长
MARGIN_T = 0.05  # 卡片距顶部比例
OUT_W, OUT_H = 1080, 1440  # 成片统一 3:4 竖版


def add_avatar_bubble(video: Path, avatar: Path, out_path: Path,
                      diameter: int = 420, hide_spans: list | None = None,
                      log=print) -> Path:
    """数字人口播视频 → 圆形气泡叠进成片右下角。

    hide_spans: [(start, end), ...] 这些时间段隐藏气泡（讲图场景让位给 figure）。
    """
    from PIL import Image, ImageDraw  # noqa: PLC0415
    d = diameter
    work = out_path.parent
    # 圆形 alpha 蒙版（抗锯齿：4x 超采样再缩小）
    big = d * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    mask_p = work / "_bubble_mask.png"
    mask.save(mask_p)
    # 白色描边圆环
    ring = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for w_, a_ in ((10, 255), (14, 120)):
        rd.ellipse([w_ // 2, w_ // 2, d - w_ // 2 - 1, d - w_ // 2 - 1],
                   outline=(255, 253, 248, a_), width=w_)
    ring_p = work / "_bubble_ring.png"
    ring.save(ring_p)

    dur = subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    x = OUT_W - d - 22
    y = OUT_H - d - 40     # 全屏右下角（素材已通屏，不再有字幕区要避让）
    enable = ""
    if hide_spans:
        cond = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in hide_spans)
        enable = f":enable='lt({cond},1)'"
    # 帧率必须全链路统一，否则时间基错配会疯狂补帧
    cmd = [ffmpeg_bin(), "-y", "-i", str(video), "-i", str(avatar),
           "-loop", "1", "-framerate", "30", "-i", str(mask_p),
           "-loop", "1", "-framerate", "30", "-i", str(ring_p),
           "-filter_complex",
           "[1:v]crop='min(iw,ih)':'min(iw,ih)',"
           f"scale={d}:{d},fps=30,format=rgba[a];"
           f"[2:v]format=gray[m];[a][m]alphamerge[bub];"
           f"[0:v]fps=30[base];[base][bub]overlay={x}:{y}:eof_action=repeat{enable}[t];"
           f"[t][3:v]overlay={x}:{y}:eof_action=repeat{enable},fps=30[v]",
           "-map", "[v]", "-map", "0:a", "-c:a", "copy",
           *VENC,
           "-t", dur or "600",
           "-movflags", "+faststart", str(out_path)]
    log("  合成数字人圆形角标…")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"数字人合成失败: {proc.stderr[-500:]}")
    return out_path


def add_progress_bar(video: Path, out_path: Path, log=print) -> Path:
    """顶部进度条：淡灰底轨，随播放进度填充成珊瑚色。"""
    dur = subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    h = 16  # 通栏贴顶
    # drawbox 的 w 表达式只在初始化求值一次，不能用于动画！
    # 正确做法：纯色填充条用 overlay 的 x 表达式（逐帧求值）从左侧滑入。
    from PIL import Image  # noqa: PLC0415
    fill_png = out_path.parent / "_bar_fill.png"
    Image.new("RGB", (OUT_W, h), (214, 108, 90)).save(fill_png)
    vf = (f"[0:v]drawbox=x=0:y=0:w={OUT_W}:h={h}:color=0xDCD4C4@1.0:t=fill[trk];"
          f"[trk][1:v]overlay=x='-{OUT_W}+{OUT_W}*min(t/{dur},1)':y=0[v]")
    log("  叠加顶部进度条…")
    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-i", str(video),
         "-loop", "1", "-framerate", "30", "-i", str(fill_png),
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
         "-t", dur or "600",
         *VENC,
         "-c:a", "copy", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"进度条合成失败: {proc.stderr[-400:]}")
    return out_path


def add_avatar_bubbles_segmented(video: Path, avatar: Path, segments: list[dict],
                                 out_path: Path, diameter: int = 420,
                                 log=print) -> Path:
    """分段圆形角标：avatar 视频按段 trim 后放到各自场景时间窗（讲图时段无人像）。

    segments: [{"start": 成片时间轴起点, "clip_off": 在avatar里的偏移, "clip_dur": 时长}]
    """
    from PIL import Image, ImageDraw  # noqa: PLC0415
    d = diameter
    work = out_path.parent
    big = d * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    mask.resize((d, d), Image.LANCZOS).save(work / "_bubble_mask.png")
    ring = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for w_, a_ in ((10, 255), (14, 120)):
        rd.ellipse([w_ // 2, w_ // 2, d - w_ // 2 - 1, d - w_ // 2 - 1],
                   outline=(255, 253, 248, a_), width=w_)
    ring.save(work / "_bubble_ring.png")

    dur = subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    x = OUT_W - d - 22
    y = OUT_H - d - 40     # 全屏右下角
    n = len(segments)
    f = [f"[1:v]crop='min(iw,ih)':'min(iw,ih)',scale={d}:{d},fps=30,format=rgba[sq];"
         f"[2:v]format=gray[m];[sq][m]alphamerge[bub];"
         f"[bub]split={n}" + "".join(f"[b{k}]" for k in range(n)) + ";"]
    ring_windows = []
    prev = "base"
    f.append("[0:v]fps=30[base];")
    for k, seg in enumerate(segments):
        s, off, cd = seg["start"], seg["clip_off"], seg["clip_dur"]
        span = seg.get("span", cd)
        e = s + span - 0.02  # 撑满整个场景（含尾部停顿）：定格末帧，无缝接下一场景
        ring_windows.append(f"between(t,{s:.2f},{e:.2f})")
        f.append(f"[b{k}]trim=start={off:.3f}:end={off + cd:.3f},"
                 f"setpts=PTS-STARTPTS+{s:.3f}/TB[c{k}];")
        f.append(f"[{prev}][c{k}]overlay={x}:{y}:eof_action=repeat:"
                 f"enable='between(t,{s:.2f},{e:.2f})'[v{k}];")
        prev = f"v{k}"
    ring_enable = "+".join(ring_windows)
    f.append(f"[{prev}][3:v]overlay={x}:{y}:eof_action=repeat:"
             f"enable='gte({ring_enable},1)',fps=30[v]")
    cmd = [ffmpeg_bin(), "-y", "-i", str(video), "-i", str(avatar),
           "-loop", "1", "-framerate", "30", "-i", str(work / "_bubble_mask.png"),
           "-loop", "1", "-framerate", "30", "-i", str(work / "_bubble_ring.png"),
           "-filter_complex", "".join(f),
           "-map", "[v]", "-map", "0:a", "-c:a", "copy",
           *VENC,
           "-t", dur or "600", "-movflags", "+faststart", str(out_path)]
    log(f"  分段合成数字人角标（{n} 段出镜）…")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"分段数字人合成失败: {proc.stderr[-500:]}")
    return out_path


def _probe_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-print_format", "json", "-show_streams",
         "-select_streams", "v:0", str(video)],
        capture_output=True, text=True, check=True)
    st = json.loads(out.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


# ── 口播剪辑版式：素材在框内，人像出框压在框上（人像永远是最上层）──
BG_COLOR = "0xFAF4E6"              # 单色背景（奶油米，与品牌一致）
MAT_BOX = (30, 40, 1020, 880)      # 素材框：加大
PERSON_D = 540                     # 人像圆形直径
PERSON_POS = (486, 828)            # 人像圆左上角：压住素材框下沿 → 出框
RING_W = 12                        # 人像白色描边宽度
PERSON_CROP_Y = 0.45               # 人像取景纵向位置（0=顶部，1=底部）
INTRO_SEC = 4.5                    # 开头全屏人像的秒数


def _rounded_mask(size: tuple[int, int], radius: int, out_png: Path) -> Path:
    from PIL import Image, ImageDraw  # noqa: PLC0415
    big = (size[0] * 2, size[1] * 2)
    m = Image.new("L", big, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, big[0] - 1, big[1] - 1],
                                        radius=radius * 2, fill=255)
    m.resize(size, Image.LANCZOS).save(out_png)
    return out_png


def _material_card(img: Path, out_png: Path) -> Path:
    """把配图放进白色圆角卡片（留白+描边+投影），作为"框内素材"。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps  # noqa: PLC0415
    w, h = MAT_BOX[2], MAT_BOX[3]
    card = Image.new("RGBA", (w, h), (255, 253, 248, 255))
    pic = ImageOps.contain(Image.open(img).convert("RGB"), (w - 44, h - 44),
                           method=Image.LANCZOS)
    card.paste(pic, ((w - pic.width) // 2, (h - pic.height) // 2))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=34, fill=255)
    card.putalpha(mask)
    out = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    sh = mask.point(lambda a: int(a * 0.32)).filter(ImageFilter.GaussianBlur(12))
    out.paste((60, 42, 33), (24, 28), sh)
    out.alpha_composite(card, (20, 16))
    out.save(out_png)
    return out_png


# Apple Silicon 的专用媒体引擎：比 x264 软件编码快一个量级，且几乎不占 CPU/内存
VENC = ["-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p"]
ENC = [*VENC, "-r", "30", "-an"]


def _circle_ring_png(d: int, work: Path, pad: int = 20) -> tuple[Path, int]:
    """人像圆形的白色描边 + 圆外柔和投影（叠在人像之上，不压暗脸）。"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter  # noqa: PLC0415
    size = d + pad * 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # 投影：模糊圆减去实心圆 → 只留圆外那一圈
    solid = Image.new("L", (size, size), 0)
    ImageDraw.Draw(solid).ellipse([pad, pad, pad + d - 1, pad + d - 1], fill=255)
    blur = solid.filter(ImageFilter.GaussianBlur(10)).point(lambda a: int(a * 0.45))
    img.paste((122, 96, 70), (0, 6), ImageChops.subtract(blur, solid))
    ImageDraw.Draw(img).ellipse([pad, pad, pad + d - 1, pad + d - 1],
                                outline=(255, 255, 255, 255), width=RING_W)
    p = work / f"ring_{d}.png"
    img.save(p)
    return p, pad


def _corner_frame_png(work: Path) -> Path:
    """挖了圆角洞的同色框：盖在素材上即可把直角修成圆角。"""
    from PIL import Image, ImageDraw  # noqa: PLC0415
    p = work / "corner_frame.png"
    w_, h_ = MAT_BOX[2], MAT_BOX[3]
    rgb = tuple(int(BG_COLOR[i:i + 2], 16) for i in (2, 4, 6))
    img = Image.new("RGBA", (w_, h_), (*rgb, 255))
    hole = Image.new("L", (w_, h_), 255)
    ImageDraw.Draw(hole).rounded_rectangle([0, 0, w_ - 1, h_ - 1], radius=34, fill=0)
    img.putalpha(hole)
    img.save(p)
    return p


def _piece_gap(dur: float, out: Path) -> Path:
    subprocess.run([ffmpeg_bin(), "-y", "-f", "lavfi",
                    "-i", f"color=c={BG_COLOR}:s={OUT_W}x{OUT_H}:r=30",
                    "-t", f"{dur:.3f}", *ENC, str(out)],
                   capture_output=True, check=True)
    return out


def _piece_material(img: Path, dur: float, out: Path, work: Path) -> Path:
    """一段素材（图片卡 / 讲图动画）铺在纯色底上的整幅画面。"""
    mx, my, mw, mh = MAT_BOX
    base = [ffmpeg_bin(), "-y", "-f", "lavfi",
            "-i", f"color=c={BG_COLOR}:s={OUT_W}x{OUT_H}:r=30"]
    if img.suffix == ".mp4":                     # 讲图光标动画：等比放入，不裁切
        cmd = base + ["-stream_loop", "-1", "-i", str(img), "-filter_complex",
                      f"[1:v]scale={mw}:{mh}:force_original_aspect_ratio=decrease,"
                      f"fps=30[m];[0:v][m]overlay=({mx}+({mw}-w)/2):"
                      f"({my}+({mh}-h)/2)[v]", "-map", "[v]"]
    else:                                        # 静态配图：预先做好的白色圆角卡
        card = _material_card(img, work / f"card_{out.stem}.png")
        cmd = base + ["-loop", "1", "-i", str(card), "-filter_complex",
                      f"[0:v][1:v]overlay={mx - 20}:{my - 16}[v]", "-map", "[v]"]
    subprocess.run(cmd + ["-t", f"{dur:.3f}", *ENC, str(out)],
                   capture_output=True, check=True)
    return out


def render_video(video: Path, images: list[Path | None],
                 spans: list[tuple[float, float]], out_path: Path, log=print) -> Path:
    """口播视频 + 素材：素材轨（单色底+素材）→ 圆形人像压顶；开头一段全屏人像。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent / "_edit"
    work.mkdir(exist_ok=True)
    d = PERSON_D
    px, py = PERSON_POS
    pmask = _rounded_mask((d, d), d // 2, work / "person_mask.png")  # 半径=半边长 → 圆
    ring, rpad = _circle_ring_png(d, work)

    total = float(subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout or 0)
    intro = min(INTRO_SEC, max(total - 2, 0))

    # 第一段：开头全屏人像（单独渲染，避免 split+enable 的滤镜死锁）
    seg_intro = work / "seg_intro.mp4"
    subprocess.run(
        [ffmpeg_bin(), "-y", "-t", f"{intro:.2f}", "-i", str(video),
         "-vf", f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},setsar=1,fps=30",
         *VENC,
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(seg_intro)],
        capture_output=True, check=True)

    # 第二段：单色底 + 素材框 + 圆形人像压顶
    main_dur = max(total - intro, 0.1)

    # 素材轨：每段素材单独铺到纯色底上，再按时间顺序拼成一条整轨。
    # （关键：不要把 N 路素材同时喂给一个滤镜图 —— 后出场的素材会被提前解码并
    #  在内存里排队等待，几路视频一起就会把内存撑爆、越跑越慢。）
    pieces, t, k, n = [], 0.0, 0, 0
    for img, (s, e) in zip(images, spans):
        if not img or not Path(img).exists():
            continue
        s, e = max(s - intro, 0.0), min(e - intro, main_dur)
        if e - s < 1.2:
            continue
        if s > t + 0.05:
            pieces.append(_piece_gap(s - t, work / f"p{k:02d}_gap.mp4"))
            k += 1
        pieces.append(_piece_material(Path(img), e - s,
                                      work / f"p{k:02d}_mat.mp4", work))
        k += 1
        t = e
        n += 1
    if main_dur - t > 0.05 or not pieces:
        pieces.append(_piece_gap(max(main_dur - t, 0.1), work / f"p{k:02d}_gap.mp4"))

    track_list = work / "track.txt"
    track_list.write_text("".join(f"file '{p.resolve()}'\n" for p in pieces))
    track = work / "mat_track.mp4"
    subprocess.run([ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0",
                    "-i", str(track_list), "-c", "copy", str(track)],
                   capture_output=True, check=True)

    # 主段：素材轨 + 圆形人像（整条链只叠一次）
    seg_main = work / "seg_main.mp4"
    log(f"  合成：开头 {intro:.1f}s 全屏人像 → {n} 段素材在框内 + 圆形人像压顶…")
    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-progress", str(work / "progress.txt"), "-nostats",
         "-i", str(track), "-ss", f"{intro:.2f}", "-i", str(video),
         "-loop", "1", "-i", str(pmask), "-loop", "1", "-i", str(ring),
         "-filter_complex",
         f"[1:v]scale={d}:{d}:force_original_aspect_ratio=increase,"
         f"crop={d}:{d}:(iw-{d})/2:(ih-{d})*{PERSON_CROP_Y},fps=30,format=rgba[pv];"
         f"[2:v]format=gray[pm];[pv][pm]alphamerge[person];"
         f"[0:v][person]overlay={px}:{py}:shortest=1[pp];"
         f"[pp][3:v]overlay={px - rpad}:{py - rpad}:shortest=1[v]",
         "-map", "[v]", "-map", "1:a?",
         # -t 是硬闸：白框/蒙版是 -loop 1 的无限输入，只靠 shortest 兜不住，
         # 主画面放完后它们还会继续产帧，把成片拖成几十分钟。
         "-t", f"{main_dur:.3f}",
         *VENC,
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(seg_main)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-800:]}")

    # 两段拼接（编码参数一致，可直接流拷贝）
    lst = work / "concat.txt"
    lst.write_text(f"file '{seg_intro.resolve()}'\nfile '{seg_main.resolve()}'\n")
    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"拼接失败: {proc.stderr[-500:]}")
    return out_path
