"""把分镜场景对齐到口播视频的时间轴。

优先级：
1. faster-whisper（若已安装）：按转写词级时间戳做比例映射，最准
2. 兜底：ffmpeg silencedetect 找到实际说话区间，按各场景字数比例分配
"""
import json
import re
import subprocess
from pathlib import Path


def _ffprobe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video)],
        capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def _speech_span(video: Path, duration: float) -> tuple[float, float]:
    """用静音检测估计开头/结尾的留白，返回实际说话的 (start, end)。"""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(video), "-af", "silencedetect=noise=-35dB:d=0.45",
         "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    speech_start = ends[0] if starts and starts[0] < 0.3 and ends else 0.0
    speech_end = starts[-1] if starts and starts[-1] > duration - 3 else duration
    return min(speech_start, duration * 0.2), max(speech_end, duration * 0.8)


def _proportional(scenes: list[dict], t0: float, t1: float) -> list[tuple[float, float]]:
    counts = [max(len(s["text"]), 1) for s in scenes]
    total = sum(counts)
    spans, cursor = [], t0
    for c in counts:
        dur = (t1 - t0) * c / total
        spans.append((cursor, cursor + dur))
        cursor += dur
    return spans


def _try_whisper(video: Path, scenes: list[dict], log) -> list[tuple[float, float]] | None:
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError:
        return None
    try:
        log("  使用 faster-whisper 做词级对齐…")
        model = WhisperModel("small", compute_type="int8")
        segments, _ = model.transcribe(str(video), language="zh", word_timestamps=True)
        words = [w for seg in segments for w in seg.words]
        if len(words) < 10:
            return None
        # 场景边界按“累计字数占比”映射到转写词流的时间轴上
        transcript_chars = sum(len(w.word.strip()) for w in words)
        counts = [max(len(s["text"]), 1) for s in scenes]
        total = sum(counts)
        spans, acc_chars, wi, cum = [], 0, 0, 0
        start_t = words[0].start
        for c in counts:
            acc_chars += c
            target = transcript_chars * acc_chars / total
            while wi < len(words) and cum < target:
                cum += len(words[wi].word.strip())
                wi += 1
            end_t = words[min(wi, len(words) - 1)].end
            spans.append((start_t, end_t))
            start_t = end_t
        return spans
    except Exception as e:  # noqa: BLE001
        log(f"  whisper 对齐失败，退回比例对齐: {e}")
        return None


def align_scenes(video: Path, scenes: list[dict], log=print) -> list[tuple[float, float]]:
    duration = _ffprobe_duration(video)
    spans = _try_whisper(video, scenes, log)
    if spans is None:
        t0, t1 = _speech_span(video, duration)
        log(f"  比例对齐：说话区间 {t0:.1f}s ~ {t1:.1f}s / 总长 {duration:.1f}s")
        spans = _proportional(scenes, t0, t1)
    return [(round(s, 2), round(min(e, duration), 2)) for s, e in spans]
