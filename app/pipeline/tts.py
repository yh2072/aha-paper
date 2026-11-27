"""Narration: the script turned into audio, with a real duration for every sentence.

Which service speaks is a setting (TTS_PROVIDER, see speech.py). How the
durations are obtained depends on what that service returns:

- word or character timestamps (Edge, ElevenLabs): one continuous take of the
  whole chapter, cut at the timestamps -- the way this module always worked;
- audio only (OpenAI, Gemini, MiniMax): one clip per sentence, stitched, each
  clip's length is that sentence's duration.

Either way nothing is estimated: a cursor driven by a guess drifts silently
with correct-sounding audio, which is the bug this module exists to prevent.
"""
import json
import re
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .. import config, lang
from ..bin import ffmpeg as ffmpeg_bin, ffprobe as ffprobe_bin
from . import speech

MODEL_TTS = 'edge-tts'
VOICE = 'zh-CN-XiaoxiaoNeural'  # compatibility; runtime settings come from config
_SENT_SPLIT = lang.ZH_SPLIT     # compatibility; the split now comes from the profile

SAMPLE_RATE = 24000
PARALLEL_REQUESTS = 4           # per-sentence clips in flight at once


def provider() -> speech.Provider:
    return speech.get(config.setting('TTS_PROVIDER'))


def voice_of(profile=None) -> str:
    """The voice this narration is spoken in: the configured one while it can
    speak the language, the provider's default for it otherwise."""
    current = provider()
    return current.voice_for(profile or lang.get(None), config.setting(current.voice_setting))


def model_of() -> str:
    return provider().model_for(config.setting('TTS_MODEL'))


def split_sentences(text: str, min_len: int | None = None, profile=None) -> list[str]:
    """The narration cut into the units the cursor is driven by.

    Chinese and English end a sentence by different rules, and the English one
    cannot be a regex on its own -- see app/lang.py. Both are lossless:
    ''.join(split_sentences(t)) == t, which synthesize_sentences relies on when
    it sends the whole narration to a timestamped provider in one piece.
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
    current, rate = provider(), config.setting("EDGE_TTS_RATE")
    if current.id == 'edge':
        # Unchanged from before providers existed, so existing narration caches stay valid.
        return f'edge-tts-v1|{profile.code}|{voice_of(profile)}|{rate}'
    identity = f'{current.id}-v1|{profile.code}|{model_of()}|{voice_of(profile)}|{rate}'
    # Stitched narration has the pauses inside every duration; a take does not.
    return identity if current.timestamps else f'{identity}|pause-{PAUSE_RULES_VERSION}'


def duration_of(audio: Path) -> float:
    result = subprocess.run([ffprobe_bin(),'-v','quiet','-show_entries','format=duration',
        '-of','csv=p=0',str(audio)],capture_output=True,text=True,check=True)
    return float(result.stdout.strip())


def _norm(text):
    return ''.join(c for c in text if c.isalnum()).lower()


def sentence_durations(sentences: list[str], events: list[dict], total: float,
                       source_name: str = 'Edge TTS') -> list[float]:
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
        raise RuntimeError(f'{source_name} 没有返回可对齐的词时间戳，请重试配音')
    starts, offset = [0.0], 0
    for sent in sentences[:-1]:
        offset += len(_norm(sent))
        start = next((t for pos,t in words if pos >= offset), None)
        if start is None:
            raise RuntimeError(f'{source_name} 时间戳不完整，无法精确驱动光标')
        starts.append(start)
    return [b-a for a,b in zip(starts, starts[1:]+[total])]


# ── stitching per-sentence clips ─────────────────────────────────────────────

# Bump when pause_after changes: the pauses are inside every cached duration.
PAUSE_RULES_VERSION = 1


def pause_after(sentence: str, following: str | None) -> float:
    """Seconds of silence after one sentence's clip, when clips are stitched.

    Only used for providers without timestamps. A single take breathes on its
    own; separately synthesized sentences butt together with whatever silence
    each clip happens to carry, which reads as either rushed or robotic.

    The pause is counted into this sentence's duration, so the cursor moves on
    exactly when the next sentence starts speaking.

    sentence:  this sentence, exactly as split (may end in whitespace or a newline)
    following: the next sentence, or None if this is the chapter's last
    """
    # TODO: a rhythm by sentence ending and paragraph break. Until then clips are
    # joined with only the silence each one already carries.
    return 0.0


def _to_pcm(clip: speech.Clip, tempo: float = 1.0) -> bytes:
    """Any clip to 24 kHz mono s16le, with the rate applied if the provider could not."""
    command = [ffmpeg_bin(), '-v', 'error', *clip.input_args, '-i', 'pipe:0']
    if abs(tempo - 1) > 1e-6:
        command += ['-af', f'atempo={tempo:.4f}']
    command += ['-ar', str(SAMPLE_RATE), '-ac', '1', '-f', 's16le', 'pipe:1']
    result = subprocess.run(command, input=clip.audio, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'语音音频转换失败: {result.stderr.decode(errors="replace")[-500:]}')
    return result.stdout


def _write_wav(path: Path, pcm: bytes):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)


def _seconds(pcm: bytes) -> float:
    return len(pcm) / 2 / SAMPLE_RATE


def _whole_take(current, sentences, out_path, voice, model, rate, credential):
    clip = current.synthesize(''.join(sentences), voice, model, credential, rate)
    tempo = 1.0 if current.native_rate else speech._rate_factor(rate)
    pcm = _to_pcm(clip, tempo)
    _write_wav(out_path, pcm)
    # atempo stretches time uniformly, so the timestamps stretch with it.
    events = [{**e, 'start': e['start'] / tempo, 'duration': e.get('duration', 0) / tempo}
              for e in (clip.events or [])]
    durations = sentence_durations(sentences, events, _seconds(pcm), current.name)
    out_path.with_suffix('.timestamps.json').write_text(json.dumps(events, ensure_ascii=False))
    return durations


def _per_sentence(current, sentences, out_path, voice, model, rate, credential, log):
    # A stale word-timestamp file from an earlier Edge take would be read by
    # explainer.py as this audio's timing. Remove it before anything else.
    out_path.with_suffix('.timestamps.json').unlink(missing_ok=True)
    tempo = speech._rate_factor(rate)
    spoken = [s.strip() for s in sentences]

    def one(text):
        # Punctuation-only fragments carry no speech; asking for them costs a
        # request and some providers reject an empty utterance.
        return current.synthesize(text, voice, model, credential, rate) if _norm(text) else None

    # The credential was resolved by the caller on the job's thread; these
    # workers only make HTTP calls and never read workspace state.
    with ThreadPoolExecutor(PARALLEL_REQUESTS) as pool:
        clips = list(pool.map(one, spoken))
    log(f'    {current.name} 逐句合成 {sum(c is not None for c in clips)} 句')
    pcm, durations = bytearray(), []
    for i, (sentence, clip) in enumerate(zip(sentences, clips)):
        piece = _to_pcm(clip, tempo) if clip else b''
        following = sentences[i + 1] if i + 1 < len(sentences) else None
        piece += b'\0\0' * int(round(max(pause_after(sentence, following), 0) * SAMPLE_RATE))
        durations.append(_seconds(piece))
        pcm.extend(piece)
    _write_wav(out_path, bytes(pcm))
    return durations


def synthesize_sentences(sentences: list[str], out_path: Path, log=print, profile=None):
    if not sentences or not ''.join(sentences).strip():
        raise ValueError('配音文本不能为空')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    current, voice, model = provider(), voice_of(profile), model_of()
    rate = config.setting('EDGE_TTS_RATE')
    log(f'    {current.name} · {voice}' + (f' · {model}' if model else '') + f' · {rate}')
    # Resolved here, on the job's thread, where the workspace is bound.
    credential = current.credential()
    try:
        if current.timestamps:
            durations = _whole_take(current, sentences, out_path, voice, model, rate, credential)
        else:
            durations = _per_sentence(current, sentences, out_path, voice, model, rate, credential, log)
    except speech.SpeechError as error:
        raise RuntimeError(str(error)) from error
    return out_path, durations


def synthesize(text: str, out_path: Path, log=print, profile=None) -> Path:
    return synthesize_sentences(split_sentences(text, profile=profile),
                                out_path, log, profile=profile)[0]
