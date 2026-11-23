"""Edge TTS narration, with word timestamps from the same synthesis for guided figures."""
import asyncio
import json
import re
import subprocess
from pathlib import Path
from .. import config
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin

MODEL_TTS = 'edge-tts'
VOICE = 'zh-CN-XiaoxiaoNeural'  # compatibility; runtime settings come from config
_SENT_SPLIT = re.compile(r'(?<=[。！？!?；;])')


def split_sentences(text: str, min_len: int = 6) -> list[str]:
    merged = []
    for part in (s for s in _SENT_SPLIT.split(text.strip()) if s.strip()):
        if merged and (len(part.strip()) < min_len or len(merged[-1].strip()) < min_len):
            merged[-1] += part
        else:
            merged.append(part)
    return merged


def cache_identity():
    return f'edge-tts-v1|{config.EDGE_TTS_VOICE}|{config.EDGE_TTS_RATE}'


def duration_of(audio: Path) -> float:
    result = subprocess.run([ffprobe_bin(),'-v','quiet','-show_entries','format=duration',
        '-of','csv=p=0',str(audio)],capture_output=True,text=True,check=True)
    return float(result.stdout.strip())


async def _stream(text: str, mp3: Path) -> list[dict]:
    import edge_tts
    events = []
    communicate = edge_tts.Communicate(text, config.EDGE_TTS_VOICE,
        rate=config.EDGE_TTS_RATE, boundary='WordBoundary')
    with mp3.open('wb') as stream:
        async for event in communicate.stream():
            if event['type'] == 'audio':
                stream.write(event['data'])
            elif event['type'] == 'WordBoundary':
                events.append({'text':event['text'],'start':event['offset']/1e7,
                               'duration':event['duration']/1e7})
    return events


def _norm(text):
    return ''.join(c for c in text if c.isalnum()).lower()


def sentence_durations(sentences: list[str], events: list[dict], total: float) -> list[float]:
    # Align against original characters, not estimated speaking speed.
    source = _norm(''.join(sentences))
    words, cursor = [], 0
    for event in events:
        word = _norm(event['text'])
        if not word:
            continue
        pos = source.find(word, cursor)
        if pos < 0:
            continue
        words.append((pos, event['start']))
        cursor = pos + len(word)
    if not words:
        raise RuntimeError('Edge TTS 没有返回可对齐的词时间戳，请重试配音')
    starts, offset = [0.0], 0
    for sent in sentences[:-1]:
        offset += len(_norm(sent))
        start = next((t for pos,t in words if pos >= offset), None)
        if start is None:
            raise RuntimeError('Edge TTS 时间戳不完整，无法精确驱动光标')
        starts.append(start)
    return [b-a for a,b in zip(starts, starts[1:]+[total])]


def synthesize_sentences(sentences: list[str], out_path: Path, log=print):
    if not sentences or not ''.join(sentences).strip():
        raise ValueError('配音文本不能为空')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mp3 = out_path.with_suffix('.edge.mp3')
    log(f'    Edge TTS · {config.EDGE_TTS_VOICE} · {config.EDGE_TTS_RATE}')
    events = asyncio.run(_stream(''.join(sentences), mp3))
    result = subprocess.run([ffmpeg_bin(),'-y','-v','error','-i',str(mp3),'-ar','24000',
        '-ac','1','-c:a','pcm_s16le',str(out_path)], capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(f'Edge TTS 音频转换失败: {result.stderr[-500:]}')
    durations = sentence_durations(sentences, events, duration_of(out_path))
    out_path.with_suffix('.timestamps.json').write_text(json.dumps(events,ensure_ascii=False))
    mp3.unlink(missing_ok=True)
    return out_path, durations


def synthesize(text: str, out_path: Path, log=print) -> Path:
    return synthesize_sentences(split_sentences(text), out_path, log)[0]
