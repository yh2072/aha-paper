"""MuseTalk 数字人：只对非讲图时段做唇形同步推理（省 2/3 时间），自动合成角标。

依赖 tools/MuseTalk-Metal（Apple Silicon 移植）+ avatar/ 下的用户视频。
"""
import os
import subprocess
from pathlib import Path

from .. import config
from . import tts

MUSETALK_DIR = config.ROOT / "tools" / "MuseTalk-Metal"
AVATAR_SRC = Path(os.getenv("AVATAR_VIDEO", str(config.ROOT / "avatar" / "yuqi_480.mp4")))


AVATAR_DIR = config.ROOT / "avatar"
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")


def photo_source() -> Path | None:
    """avatar/ 下的单张照片：没有口播视频时，用照片也能做数字人。"""
    for p in sorted(AVATAR_DIR.glob("*")):
        if p.suffix.lower() in PHOTO_EXT and not p.name.startswith("."):
            return p
    return None


def _still_video(photo: Path, seconds: float, out_mp4: Path, log=print) -> Path:
    """照片 → 静帧视频（480 宽 / 25fps），作为 MuseTalk 的驱动素材。"""
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(photo), "-t", f"{seconds:.2f}",
         "-vf", "scale=480:-2,pad=ceil(iw/2)*2:ceil(ih/2)*2", "-r", "25",
         "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", str(out_mp4)],
        capture_output=True, check=True)
    log(f"  照片→静帧视频（{seconds:.0f}s）：{photo.name}")
    return out_mp4


def available() -> bool:
    if not config.AVATAR_ENABLED:      # 总开关关掉时，所有自动排队一律不发生
        return False
    has_model = (MUSETALK_DIR / "models" / "musetalkV15" / "unet.pth").exists()
    return has_model and (AVATAR_SRC.exists() or photo_source() is not None)


def _source_stamp() -> str:
    """驱动素材指纹：换了视频或照片，推理缓存自动失效。"""
    src = AVATAR_SRC if AVATAR_SRC.exists() else photo_source()
    return f"{src}:{src.stat().st_mtime}" if src else "none"


def _dur(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def plan_segments(proj_dir: Path, scenes: list[dict]) -> list[dict]:
    """非讲图场景规划：span=场景全长（含尾部停顿），合成时定格末帧补空隙。"""
    segments, t, off = [], 0.0, 0.0
    for i, sc in enumerate(scenes):
        seg_mp4 = proj_dir / "tts_work" / f"seg_{i:02d}.mp4"
        wav = proj_dir / "tts_work" / f"seg_{i:02d}.wav"
        if not seg_mp4.exists() or not wav.exists():
            return []
        span = _dur(seg_mp4)
        if not sc.get("figure_path"):
            wd = _dur(wav)
            segments.append({"scene": i, "start": t, "span": span,
                             "clip_off": off, "clip_dur": wd, "wavs": [wav]})
            off += wd
        t += span
    return segments


def generate(proj_dir: Path, scenes: list[dict], log=print) -> tuple[Path, list[dict]]:
    """拼非讲图音频 → 裁短源视频 → MuseTalk 推理一次 → 返回 (口播视频, 分段表)。"""
    segments = plan_segments(proj_dir, scenes)
    if not segments:
        raise RuntimeError("分段规划失败（缺少 tts_work 分段文件）")
    work = proj_dir / "musetalk_work"
    work.mkdir(exist_ok=True)

    # 1. 拼接非讲图配音（同参 wav 流拷贝拼接；不含停顿 → 与历史推理缓存兼容）
    concat_list = work / "concat.txt"
    concat_list.write_text("".join(
        f"file '{w.resolve()}'\n" for s in segments for w in s["wavs"]))
    nonfig_wav = work / "nonfig.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i",
                    str(concat_list), "-c", "copy", str(nonfig_wav)],
                   capture_output=True, check=True)
    total = _dur(nonfig_wav)

    # 结果缓存：配音内容和源视频没变 → 直接复用上次的推理产物
    import hashlib  # noqa: PLC0415
    key = hashlib.md5(nonfig_wav.read_bytes()
                      + str(_source_stamp()).encode()).hexdigest()
    key_f = work / "clip.key"
    cached = sorted((work / "results").rglob("*.mp4"),
                    key=lambda p: p.stat().st_mtime) if (work / "results").exists() else []
    cached = [p for p in cached if not p.name.startswith("temp_")]
    if cached and key_f.exists() and key_f.read_text() == key:
        log("  （复用缓存的数字人推理结果）")
        return cached[-1], segments
    log(f"  数字人推理：{len(segments)} 段非讲图，共 {total:.0f}s（讲图时段跳过）")

    # 2. 驱动素材：有口播视频就裁到音频长度；只有照片就先做成静帧视频
    src = work / "src.mp4"
    if AVATAR_SRC.exists():
        subprocess.run(["ffmpeg", "-y", "-t", f"{total + 2:.2f}", "-i", str(AVATAR_SRC),
                        "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                        str(src)], capture_output=True, check=True)
    else:
        _still_video(photo_source(), total + 2, src, log=log)

    # 3. MuseTalk 推理（480p / batch1 / TAESD，内存友好）
    yaml = work / "task.yaml"
    yaml.write_text(f'task_0:\n  video_path: "{src.resolve()}"\n'
                    f'  audio_path: "{nonfig_wav.resolve()}"\n  bbox_shift: -7\n')
    env = dict(os.environ, MUSETALK_BLEND_CV2="1", MUSETALK_TAESD="1",
               PYTHONPATH=str(MUSETALK_DIR))
    result_dir = work / "results"
    inf_log = work / "inference.log"  # 实时进度：tail 这个文件能看到 tqdm 百分比
    with open(inf_log, "w") as lf:
        proc = subprocess.run(
            [str(MUSETALK_DIR / ".venv" / "bin" / "python"), "scripts/inference.py",
             "--inference_config", str(yaml.resolve()),
             "--result_dir", str(result_dir.resolve()), "--version", "v15",
             "--unet_model_path", "models/musetalkV15/unet.pth",
             "--unet_config", "models/musetalkV15/musetalk.json",
             "--bbox_shift", "-7", "--batch_size", "1"],
            cwd=MUSETALK_DIR, env=env, stdout=lf, stderr=subprocess.STDOUT,
            timeout=7200)
    outs = sorted(result_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
    outs = [p for p in outs if not p.name.startswith("temp_")]
    if proc.returncode != 0 or not outs:
        tail = inf_log.read_text()[-400:] if inf_log.exists() else ""
        raise RuntimeError(f"MuseTalk 推理失败: {tail}")
    key_f.write_text(key)
    log(f"  数字人推理完成: {outs[-1].name}")
    return outs[-1], segments
