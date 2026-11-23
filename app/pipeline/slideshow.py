"""图片 + TTS 图文成片：每个分镜 = 配图卡片 + 字幕排版 + 配音，拼接成 3:4 视频。"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import anim, figures, tts
from .cover import _body_font as _font  # 霞鹜文楷：字幕/角标温暖手写风
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin

W, H = 1080, 1440  # 3:4 竖版
BG = (250, 244, 230)
INK = (61, 47, 38)
SUB_GRAY = (201, 193, 178)  # 字幕未读态：淡灰
ACCENT = (214, 108, 90)
TAIL_SILENCE = 0.35  # 每段结尾留白秒数


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *img.size], radius=radius, fill=255)
    img = img.convert("RGBA")
    img.putalpha(mask)
    return img


def _trim_uniform_border(img: Image.Image, tol: int = 22, max_frac: float = 0.12) -> Image.Image:
    """裁掉 AI 图四周近似纯色的"纸边"（以四角颜色为参照，最多裁 12%）。"""
    import numpy as np  # noqa: PLC0415
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w = arr.shape[:2]
    corner = (arr[2, 2] + arr[2, w - 3] + arr[h - 3, 2] + arr[h - 3, w - 3]) / 4
    diff = np.abs(arr - corner).mean(axis=2)
    lim_h, lim_w = int(h * max_frac), int(w * max_frac)

    def run(vals, limit):
        n = 0
        for v in vals[:limit]:
            if v < tol:
                n += 1
            else:
                break
        return n

    row_ok = (diff < tol).mean(axis=1)   # 每行有多少比例像素接近边色
    col_ok = (diff < tol).mean(axis=0)
    top = run(list(row_ok > 0.92), lim_h)
    bot = run(list(row_ok[::-1] > 0.92), lim_h)
    left = run(list(col_ok > 0.92), lim_w)
    right = run(list(col_ok[::-1] > 0.92), lim_w)
    if top + bot + left + right == 0:
        return img
    return img.crop((left, top, w - right, h - bot))


def _wrap_cjk(text: str, per_line: int) -> list[str]:
    lines, cur = [], ""
    for ch in text.strip():
        cur += ch
        if len(cur) >= per_line and ch not in "，。！？、；：":
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines


# 素材区 = 整个画面。不再留字幕区，素材通屏铺满。
CARD_BOX = (0, 0, 1080, 1440)
CARD_FIT = (1080, 1440)
TOP_SAFE = 92                   # 角标下沿，避开顶部进度条


def _draw_badge(draw: ImageDraw.ImageDraw, idx: int, total: int):
    badge = f"{idx + 1} / {total}"
    bfont = _font(34)
    bw = draw.textlength(badge, font=bfont)
    y0 = TOP_SAFE  # 右上角，避开进度条
    draw.rounded_rectangle([W - bw - 76, y0, W - 36, y0 + 58], radius=29, fill=ACCENT)
    draw.text((W - bw - 56, y0 + 8), badge, font=bfont, fill=(255, 250, 242))


def badge_layer(idx: int, total: int, out_path: Path) -> Path:
    """透明底的角标图层，用于叠在视频画面之上。"""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_badge(ImageDraw.Draw(layer), idx, total)
    layer.save(out_path)
    return out_path


SUB_SIZE = 52          # 字幕字号
SUB_MAXLINES = 2       # 一句最多折两行，再长就缩字号
SUB_BOTTOM = 96        # 字幕块距画面底部


SUB_MIN_CHARS = 10     # 短于这个字数的句子并进上一句
SUB_MAX_CHARS = 30     # 合并后的上限
SUB_MAX_PER_SCENE = 16  # 每场景最多几条字幕（每条要 2 路图层输入，太多会拖垮滤镜图）


def _merge_short(sents: list[str], durs: list[float]) -> tuple[list[str], list[float]]:
    """把过碎的句子并起来。

    三、四个字的字幕一闪而过既看不清也难看；更实际的原因是每条字幕要占
    2 路 ffmpeg 输入，一个场景几十条会让滤镜图又慢又脆。
    """
    out_s: list[str] = []
    out_d: list[float] = []
    for s, d in zip(sents, durs):
        s = " ".join(s.split())
        if not s:
            if out_d:
                out_d[-1] += d
            continue
        if out_s and (len(s) < SUB_MIN_CHARS or len(out_s[-1]) < SUB_MIN_CHARS) \
                and len(out_s[-1]) + len(s) <= SUB_MAX_CHARS:
            out_s[-1] += s
            out_d[-1] += d
        else:
            out_s.append(s)
            out_d.append(d)
    while len(out_s) > SUB_MAX_PER_SCENE:      # 还是太多 → 挑最短的一对继续并
        i = min(range(len(out_s) - 1), key=lambda k: len(out_s[k]) + len(out_s[k + 1]))
        out_s[i] += out_s[i + 1]
        out_d[i] += out_d[i + 1]
        del out_s[i + 1], out_d[i + 1]
    return out_s, out_d


def subtitle_layers(sentences: list[str], durs: list[float], work: Path,
                    stem: str) -> list[dict]:
    """逐句字幕图层：一次只显示当前这句，压在画面底部。

    素材已经通屏铺满，字幕直接叠在画面上，所以：
    - 底下垫一层半透明深色衬底，否则白字压在浅色画面上会看不清
    - 未读态用半透明白、已读态用纯白 + 描边，卡拉OK擦除时对比才明显
    （之前那版是把整段话一次全铺出来，六七行占掉半屏，才显得像块牛皮癣）
    """
    # Long scientific sentences must wrap into multiple timed captions, never be cut off.
    chunks, times = [], []
    for sentence, duration in zip(sentences, durs):
        parts=[sentence[i:i+34] for i in range(0,len(sentence),34)] or [sentence]
        total=sum(len(part) for part in parts) or 1
        chunks.extend(parts)
        times.extend(duration*len(part)/total for part in parts)
    sentences, durs = _merge_short(chunks, times)
    layers, t0 = [], 0.0
    for j, (sent, d) in enumerate(zip(sentences, durs)):
        s = " ".join(sent.split())
        if not s:
            t0 += d
            continue
        for size in (SUB_SIZE, 46, 40, 34):
            lines = _wrap_cjk(s, max((W - 180) // size, 6))
            if len(lines) <= SUB_MAXLINES:
                break
        lines = lines[:SUB_MAXLINES]
        font = _font(size)
        line_h = int(size * 1.5)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        tw = max(int(probe.textlength(ln, font=font)) for ln in lines)
        pad_x, pad_y = 34, 20
        bw, bh = tw + pad_x * 2, line_h * len(lines) + pad_y * 2
        x0, y0 = (W - bw) // 2, H - SUB_BOTTOM - bh

        # 未读态：衬底 + 半透明白字（整块一张图）
        grey = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grey)
        gd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=22, fill=(38, 30, 24, 150))
        # 已读态：只有文字，透明底，供卡拉OK逐字擦出来
        ink = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        idr = ImageDraw.Draw(ink)
        for k, ln in enumerate(lines):
            lw = int(probe.textlength(ln, font=font))
            lx, ly = (bw - lw) // 2, pad_y + k * line_h
            gd.text((lx, ly), ln, font=font, fill=(255, 253, 248, 120))
            idr.text((lx, ly), ln, font=font, fill=(255, 253, 248, 255),
                     stroke_width=3, stroke_fill=(38, 30, 24, 220))
        gp = work / f"{stem}_sg{j:02d}.png"
        ip = work / f"{stem}_si{j:02d}.png"
        grey.save(gp)
        ink.save(ip)
        layers.append({"grey": gp, "ink": ip, "x": x0, "y": y0, "w": bw, "h": bh,
                       "start": t0, "dur": max(d, 0.05)})
        t0 += d
    return layers


def compose_frame(image_path: Path | None, text: str, idx: int, total: int,
                  out_path: Path, draw_image: bool = True,
                  fill: bool = False) -> Path:
    text = " ".join(text.split())  # 清洗换行/多余空白，Pillow 不接受多行 textlength
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)

    img_bottom = 40
    if image_path and image_path.exists():
        card = Image.new("RGB", CARD_BOX[2:], (255, 253, 248))
        if draw_image:  # 动画场景只画白底，图由循环视频叠加
            img = Image.open(image_path).convert("RGB")
            if fill:  # 手绘方图：裁切满铺，边到边
                img = ImageOps.fit(img, CARD_FIT, method=Image.LANCZOS)
                card.paste(img, (0, 0))
            else:     # 论文图表：完整展示不裁切（先削掉图自带的白边，能大 30%）
                img = _trim_uniform_border(img)
                img = ImageOps.contain(img, CARD_FIT, method=Image.LANCZOS)
                card.paste(img, ((CARD_BOX[2] - img.width) // 2,
                                 (CARD_BOX[3] - img.height) // 2))
        canvas.paste(card, CARD_BOX[:2])
        img_bottom = CARD_BOX[1] + CARD_BOX[3]

    if draw_image:  # 动画场景的角标由独立图层叠加（避免被动画视频盖住）
        _draw_badge(draw, idx, total)

    # 不画字幕：素材通屏展示，字幕会挤掉画面。返回空表 → 卡拉OK滤镜整段跳过。
    canvas.save(out_path)
    return out_path, []


def _video_size(path: Path) -> tuple[int, int]:
    import json  # noqa: PLC0415
    out = subprocess.run(
        [ffprobe_bin(), "-v", "quiet", "-print_format", "json", "-show_streams",
         "-select_streams", "v:0", str(path)], capture_output=True, text=True, check=True)
    st = json.loads(out.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


def render_slideshow(scenes: list[dict], images: list[Path | None],
                     work_dir: Path, out_path: Path, log=print,
                     anim_dir: Path | None = None, profile=None) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    seg_files = []
    import hashlib
    import json as _json
    for i, (scene, img) in enumerate(zip(scenes, images)):
        log(f"  TTS 配音 {i + 1}/{len(scenes)}…")
        fig_path = Path(scene["figure_path"]) if scene.get("figure_path") else None

        # 配音缓存：同一段文稿+音色只合成一次，纯视觉改动重渲染零 TTS 费用
        wav = work_dir / f"seg_{i:02d}.wav"
        key_f = work_dir / f"seg_{i:02d}.key"
        durs_f = work_dir / f"seg_{i:02d}.durs.json"
        key = hashlib.md5(
            f"{tts.cache_identity(profile)}|{bool(fig_path)}|{scene['text']}"
            .encode()).hexdigest()
        cached = wav.exists() and key_f.exists() and key_f.read_text() == key

        if fig_path and fig_path.exists():
            # 讲图场景：逐句配音拿时长 → 每句映射图中区域 → 光标跟着讲解走
            sents = tts.split_sentences(scene["text"], profile=profile)
            if cached and durs_f.exists():
                durs = _json.loads(durs_f.read_text())
                log("    （复用缓存配音）")
            else:
                wav, durs = tts.synthesize_sentences(sents, wav, log=log, profile=profile)
                durs_f.write_text(_json.dumps(durs))
                key_f.write_text(key)
            regions = figures.map_sentences_to_regions(fig_path, sents, log=log)
            overlay_vid = anim.render_guided_pointer(
                fig_path, list(zip(durs, regions)),
                work_dir / f"guided_{i:02d}.mp4", log=log)
        else:
            sents = tts.split_sentences(scene["text"], profile=profile)
            if cached:
                log("    （复用缓存配音）")
                durs = _json.loads(durs_f.read_text()) if durs_f.exists() else None
            else:
                _, durs = tts.synthesize_sentences(sents, wav, log=log, profile=profile)
                durs_f.write_text(_json.dumps(durs))
                key_f.write_text(key)
            if durs is None:
                # 老缓存里没有逐句时长。按字数比例摊到总时长上——字幕对齐够用，
                # 而且不用为了拿时长把已经付过钱的配音重合成一遍。
                tot = tts.duration_of(wav)
                n = sum(len(s) for s in sents) or 1
                durs = [tot * len(s) / n for s in sents]
                durs_f.write_text(_json.dumps(durs))
            overlay_vid = anim_dir / f"anim_{i:02d}.mp4" if anim_dir else None
            overlay_vid = overlay_vid if overlay_vid and overlay_vid.exists() else None

        speech_dur = tts.duration_of(wav)
        dur = speech_dur + TAIL_SILENCE
        seg = work_dir / f"seg_{i:02d}.mp4"

        frame, _ = compose_frame(
            img, scene["text"], i, len(scenes), work_dir / f"frame_{i:02d}.png",
            draw_image=not overlay_vid, fill=(not fig_path) and not overlay_vid)

        cmd = [ffmpeg_bin(), "-y", "-loop", "1", "-i", str(frame)]
        f = ["[0:v]fps=30[b0];"]
        base, nxt = "b0", 1
        if overlay_vid:  # 白卡底帧 + 光标动画 + 角标图层
            badge = badge_layer(i, len(scenes), work_dir / f"badge_{i:02d}.png")
            aw, ah = _video_size(overlay_vid)          # 等比放进卡片
            sc_ = min(CARD_FIT[0] / aw, CARD_FIT[1] / ah)
            ow, oh = int(aw * sc_) // 2 * 2, int(ah * sc_) // 2 * 2
            ox = CARD_BOX[0] + (CARD_BOX[2] - ow) // 2
            oy = CARD_BOX[1] + (CARD_BOX[3] - oh) // 2
            cmd += ["-i", str(overlay_vid), "-loop", "1", "-i", str(badge)]
            f.append(f"[1:v]scale={ow}:{oh}[a];[{base}][a]overlay={ox}:{oy}[t1];"
                     f"[t1][2:v]overlay=0:0[t2];")
            base, nxt = "t2", 3
        aud = nxt
        cmd += ["-i", str(wav)]
        nxt += 1

        # 字幕卡拉OK：逐行按字数比例，随讲解从淡灰擦成正文色。
        # 注意：drawbox 的 w 不支持逐帧 t，擦除必须用 overlay x 表达式滑动白块。
        white_png = work_dir / "_white.png"
        if not white_png.exists():
            Image.new("L", (W, 120), 255).save(white_png)
        subs = subtitle_layers(sents, durs, work_dir, f"f{i:02d}")
        n_sub = len(subs)
        if n_sub:
            cmd += ["-loop", "1", "-framerate", "30", "-i", str(white_png)]
            white_idx = nxt
            nxt += 1
            f.append(f"[{white_idx}:v]split={n_sub}"
                     + "".join(f"[wh{j}]" for j in range(n_sub)) + ";")
        for j, sb in enumerate(subs):
            s0, ld = sb["start"], sb["dur"]
            e0 = s0 + ld
            win = f"between(t,{s0:.3f},{e0:.3f})"   # 一次只亮当前这句
            cmd += ["-loop", "1", "-framerate", "30", "-i", str(sb["grey"]),
                    "-loop", "1", "-framerate", "30", "-i", str(sb["ink"])]
            g_idx, i_idx = nxt, nxt + 1
            nxt += 2
            prog = f"min(max((t-{s0:.3f})/{ld:.3f},0),1)"
            f.append(
                # 未读态（衬底+半透明字）
                f"[{base}][{g_idx}:v]overlay={sb['x']}:{sb['y']}:"
                f"eof_action=repeat:enable='{win}'[g{j}];"
                # 已读态：白块从左滑入当遮罩 → 逐字擦成纯白
                f"color=c=black:s={sb['w']}x{sb['h']}:r=30[ms{j}];"
                f"[ms{j}][wh{j}]overlay=x='-{W}+{sb['w']}*{prog}':y=0[mw{j}];"
                f"[mw{j}]format=gray[mk{j}];"
                f"[{i_idx}:v]format=rgba,split[sc{j}][sa{j}];"
                f"[sa{j}]alphaextract[ae{j}];"
                f"[ae{j}][mk{j}]blend=all_mode=multiply[am{j}];"
                f"[sc{j}][am{j}]alphamerge[rv{j}];"
                f"[g{j}][rv{j}]overlay={sb['x']}:{sb['y']}:"
                f"eof_action=repeat:enable='{win}'[k{j}];")
            base = f"k{j}"
        f.append(f"[{base}]format=yuv420p[v]")

        cmd += ["-filter_complex", "".join(f), "-map", "[v]", "-map", f"{aud}:a",
                "-af", f"apad=pad_dur={TAIL_SILENCE}",
                "-t", f"{dur:.2f}", "-r", "30", "-c:v", "h264_videotoolbox", "-b:v", "6M", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", "-b:a", "160k", str(seg)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 分段失败: {proc.stderr[-500:]}")
        seg_files.append(seg)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{s.name}'\n" for s in seg_files))
    proc = subprocess.run(
        [ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True, cwd=work_dir)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 拼接失败: {proc.stderr[-500:]}")
    return out_path
