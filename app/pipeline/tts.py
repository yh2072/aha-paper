"""Edge TTS narration, with word timestamps from the same synthesis for guided figures."""
import asyncio
import json
import re
import subprocess
from pathlib import Path
from .. import config, lang
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin

MODEL_TTS = 'edge-tts'
VOICE = 'zh-CN-XiaoxiaoNeural'  # compatibility; runtime settings come from config
_SENT_SPLIT = lang.ZH_SPLIT     # compatibility; the split now comes from the profile


def voice_of(profile=None) -> str:
    """The voice this narration is spoken in: the configured one while it speaks
    the right language, the profile's own otherwise. See lang.voice_for."""
    return lang.voice_for(profile or lang.get(None), config.EDGE_TTS_VOICE)


def split_sentences(text: str, min_len: int | None = None, profile=None) -> list[str]:
    """The narration cut into the units the cursor is driven by.

    Chinese and English end a sentence by different rules, and the English one
    cannot be a regex on its own -- see app/lang.py. Both are lossless:
    ''.join(split_sentences(t)) == t, which synthesize_sentences relies on when
    it sends the whole narration to Edge TTS in one piece.
    """
    return (profile or lang.get(None)).split_narration(text, min_len)


def cache_identity(profile=None):
    """What a cached narration was made with. Anything that would change the
    audio, or change which sentence each duration belongs to, has to be in here.

    The language code is in it even though the voice already implies it today.
    The cached durs list is zipped with a freshly computed sentence split, so a
    change to the split rule that did not change the key would pair every
    sentence with the wrong duration -- and the cursor would drift silently,
    with correct-looking audio. Two languages sharing a voice is enough to
    cause that, so the key does not rely on the voice to encode the language."""
    profile = profile or lang.get(None)
    return f'edge-tts-v1|{profile.code}|{voice_of(profile)}|{config.EDGE_TTS_RATE}'


def duration_of(audio: Path) -> float:
    result = subprocess.run([ffprobe_bin(),'-v','quiet','-show_entries','format=duration',
        '-of','csv=p=0',str(audio)],capture_output=True,text=True,check=True)
    return float(result.stdout.strip())


async def _stream(text: str, mp3: Path, voice: str) -> list[dict]:
    import edge_tts
    events = []
    communicate = edge_tts.Communicate(text, voice,
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


def synthesize_sentences(sentences: list[str], out_path: Path, log=print, profile=None):
    if not sentences or not ''.join(sentences).strip():
        raise ValueError('配音文本不能为空')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mp3 = out_path.with_suffix('.edge.mp3')
    voice = voice_of(profile)
    log(f'    Edge TTS · {voice} · {config.EDGE_TTS_RATE}')
    events = asyncio.run(_stream(''.join(sentences), mp3, voice))
    result = subprocess.run([ffmpeg_bin(),'-y','-v','error','-i',str(mp3),'-ar','24000',
        '-ac','1','-c:a','pcm_s16le',str(out_path)], capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(f'Edge TTS 音频转换失败: {result.stderr[-500:]}')
    durations = sentence_durations(sentences, events, duration_of(out_path))
    out_path.with_suffix('.timestamps.json').write_text(json.dumps(events,ensure_ascii=False))
    mp3.unlink(missing_ok=True)
    return out_path, durations


def synthesize(text: str, out_path: Path, log=print, profile=None) -> Path:
    return synthesize_sentences(split_sentences(text, profile=profile),
                                out_path, log, profile=profile)[0]
