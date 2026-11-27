"""Speech providers: who turns the narration into audio.

A provider comes in one of two shapes, decided by what it can say about timing,
because timing is what the cursor runs on:

- timestamps=True: the whole narration goes out in one request and comes back
  with word or character start times (Edge, ElevenLabs). One continuous take,
  the best prosody, and clause-level cues inside a sentence.
- timestamps=False: the provider returns audio and nothing else (OpenAI, Gemini,
  MiniMax). tts.py then asks for one clip per sentence and measures each clip,
  so every duration is still a real one -- never an estimate from character
  counts. The cursor moves per sentence rather than per clause.

Credentials: a provider that Pi's registry already knows (openai, google,
minimax) reuses the connection the user made under "Providers", so one key
serves the script and the voice. A provider Pi does not know (ElevenLabs) keeps
its key in a small store of its own beside Pi's, per workspace, mode 600. In
both cases the key stays on the server: catalog() reports *whether* a provider
is connected, never with what.

Nothing in here reads tenant state from a worker thread. tts.py resolves the
credential on the job's own thread and passes it in, because the workspace is a
ContextVar and a fresh thread would see the operator's instead.
"""
import asyncio
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .. import lang, pi_models, tenant


class SpeechError(RuntimeError):
    """A synthesis failure the user can act on: a key, a quota, a voice ID."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    lang: str | None = None          # None: the voice speaks any language


@dataclass
class Clip:
    """One synthesis result. ``input_args`` tells ffmpeg how to read ``audio``
    when it is not a self-describing container (raw PCM from Gemini)."""
    audio: bytes
    input_args: tuple = ()
    events: list | None = None       # [{'text','start','duration'}] in seconds


VOICE_ID = re.compile(r'[A-Za-z0-9_.\-]{1,80}')
MODEL_ID = re.compile(r'[A-Za-z0-9_.:\-]{1,80}')


class Provider:
    id = ''
    name = ''
    timestamps = False       # returns word/char times for a whole take
    native_rate = False      # applies the rate itself; otherwise ffmpeg atempo does
    custom_voice = False     # accepts voice IDs outside the list (cloned voices)
    voice_setting = 'TTS_VOICE'
    pi_ids: tuple = ()       # Pi providers whose credential this one reuses
    key_env = ''             # its own credential, for a provider Pi does not know
    default_base = ''
    models: tuple = ()       # suggestions; the first is the default
    voices: tuple = ()
    note = ''

    # -- voices and models -------------------------------------------------
    def default_voice(self, profile) -> str:
        fitting = [v for v in self.voices if v.lang in (None, profile.code)]
        return (fitting or self.voices)[0].id

    def voice_for(self, profile, configured: str | None) -> str:
        """The configured voice while it can speak this language, else a default.

        A listed voice tagged with another language hands over, exactly as Edge's
        zh-CN voices do for English narration. An unlisted ID is a cloned voice
        on a provider that allows them: it is the user's, and kept."""
        known = {v.id: v for v in self.voices}
        if configured in known:
            return configured if known[configured].lang in (None, profile.code) else self.default_voice(profile)
        if configured and self.custom_voice and VOICE_ID.fullmatch(configured):
            return configured
        return self.default_voice(profile)

    def valid_voice(self, voice: str) -> bool:
        return voice in {v.id for v in self.voices} or bool(self.custom_voice and VOICE_ID.fullmatch(voice))

    def model_for(self, configured: str | None) -> str:
        """The configured model, unless it plainly belongs to another provider.

        Models are free text (catalogs move faster than this list), so the only
        thing that can be told for sure is "that is OpenAI's model and this is
        Gemini" -- which is the mistake a provider switch in .env would make."""
        if not self.models:
            return ''
        if not configured:
            return self.models[0]
        foreign = {m for p in PROVIDERS.values() if p is not self for m in p.models}
        return self.models[0] if configured in foreign and configured not in self.models else configured

    # -- credentials ---------------------------------------------------------
    def status(self) -> dict:
        """Connected or not, and from where. Display-safe: no secret in it."""
        if not self.pi_ids and not self.key_env:
            return {'configured': True, 'source': ''}
        for pid in self.pi_ids:
            try:
                check = pi_models.check(pid)
            except pi_models.ProviderError:
                continue
            if check.get('configured'):
                return {'configured': True, 'source': check.get('source', ''), 'via': pid}
        if self.key_env:
            if _stored_keys().get(self.id):
                return {'configured': True, 'source': 'stored credential'}
            if os.getenv(self.key_env):
                return {'configured': True, 'source': self.key_env}
        return {'configured': False, 'source': ''}

    def credential(self) -> dict:
        """Endpoint and key, server-side only. Call on the job's own thread."""
        if not self.pi_ids and not self.key_env:
            return {}
        for pid in self.pi_ids:
            try:
                if not pi_models.check(pid).get('configured'):
                    continue
                resolved = pi_models.resolve(pid)
            except pi_models.ProviderError:
                continue
            return {'api_key': resolved.get('api_key', ''), 'base_url': resolved.get('base_url', ''), 'via': pid}
        if self.key_env:
            key = _stored_keys().get(self.id) or os.getenv(self.key_env, '')
            if key:
                return {'api_key': key, 'base_url': ''}
        wanted = ' / '.join(self.pi_ids) if self.pi_ids else self.name
        raise SpeechError(f'语音供应商 {self.name} 未连接：请先在设置中连接 {wanted}')

    # -- synthesis -------------------------------------------------------------
    def synthesize(self, text: str, voice: str, model: str, credential: dict, rate: str = '+0%') -> Clip:
        raise NotImplementedError

    def describe(self) -> dict:
        state = self.status()
        return {'id': self.id, 'name': self.name, 'timestamps': self.timestamps,
                'custom_voice': self.custom_voice, 'needs_own_key': bool(self.key_env),
                'pi_providers': list(self.pi_ids), 'models': list(self.models),
                'voices': [{'id': v.id, 'label': v.label, 'lang': v.lang} for v in self.voices],
                'note': self.note, **state}

    # -- shared HTTP -------------------------------------------------------------
    def _post(self, url: str, *, headers: dict, payload: dict, timeout: float = 120) -> httpx.Response:
        """POST with a short retry on throttling and transient server errors.

        Per-sentence synthesis makes many small requests in parallel, which is
        exactly what trips a rate limit; one retry with backoff absorbs that
        without turning a real failure (bad key, unknown voice) into a long hang."""
        for attempt in range(3):
            try:
                response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            except httpx.TransportError as error:
                if attempt == 2:
                    raise SpeechError(f'{self.name} 网络错误：{error}') from error
                time.sleep(1.5 * 2 ** attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * 2 ** attempt)
                continue
            if response.status_code >= 400:
                raise SpeechError(f'{self.name} 语音合成失败（HTTP {response.status_code}）：{_detail(response)}')
            return response
        raise SpeechError(f'{self.name} 语音合成失败')


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        error = body.get('error') or body.get('detail') or body.get('base_resp') or body
        if isinstance(error, dict):
            error = error.get('message') or error.get('status_msg') or error.get('status') or json.dumps(error, ensure_ascii=False)
        return str(error)[:200]
    return str(body)[:200]


def _rate_factor(rate: str) -> float:
    """'+10%' -> 1.1. Validated upstream to -50%..+50%."""
    match = re.fullmatch(r'([+-]\d{1,2})%', rate or '+0%')
    return 1 + int(match.group(1)) / 100 if match else 1.0


# ── Edge ─────────────────────────────────────────────────────────────────────

class Edge(Provider):
    id, name = 'edge', 'Edge TTS'
    timestamps = native_rate = True
    voice_setting = 'EDGE_TTS_VOICE'
    voices = (Voice('zh-CN-XiaoxiaoNeural', '晓晓 · 自然女声', 'zh'),
              Voice('zh-CN-YunxiNeural', '云希 · 清朗男声', 'zh'),
              Voice('zh-CN-XiaoyiNeural', '晓伊 · 温柔女声', 'zh'),
              Voice('zh-CN-YunjianNeural', '云健 · 稳重男声', 'zh'),
              Voice('en-US-AriaNeural', 'Aria · English', 'en'))
    note = 'Edge TTS 不需要 Key，但需要联网。'

    def voice_for(self, profile, configured):
        # Edge names every voice '<lang>-<REGION>-<Name>'; lang.voice_for owns that rule.
        return lang.voice_for(profile, configured)

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        return asyncio.run(self._stream(text, voice, rate))

    @staticmethod
    async def _stream(text, voice, rate):
        import edge_tts
        events, audio = [], bytearray()
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary='WordBoundary')
        async for event in communicate.stream():
            if event['type'] == 'audio':
                audio.extend(event['data'])
            elif event['type'] == 'WordBoundary':
                events.append({'text': event['text'], 'start': event['offset'] / 1e7,
                               'duration': event['duration'] / 1e7})
        return Clip(bytes(audio), events=events)


# ── OpenAI ───────────────────────────────────────────────────────────────────

class OpenAI(Provider):
    id, name = 'openai', 'OpenAI'
    pi_ids = ('openai',)
    default_base = 'https://api.openai.com/v1'
    models = ('gpt-4o-mini-tts', 'tts-1-hd', 'tts-1')
    voices = tuple(Voice(v, v.capitalize()) for v in
                   ('coral', 'alloy', 'ash', 'ballad', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer', 'verse'))
    note = '复用「供应商」里的 OpenAI 连接；逐句合成，光标按句移动。'

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        base = (credential.get('base_url') or self.default_base).rstrip('/')
        response = self._post(base + '/audio/speech',
                              headers={'Authorization': 'Bearer ' + credential['api_key']},
                              payload={'model': model, 'voice': voice, 'input': text, 'response_format': 'mp3'})
        return Clip(response.content)


# ── Google Gemini ──────────────────────────────────────────────────────────────

class Gemini(Provider):
    id, name = 'google', 'Google Gemini'
    pi_ids = ('google',)
    default_base = 'https://generativelanguage.googleapis.com/v1beta'
    models = ('gemini-2.5-flash-preview-tts', 'gemini-2.5-pro-preview-tts')
    voices = tuple(Voice(v, f'{v} · {d}') for v, d in (
        ('Kore', 'firm'), ('Puck', 'upbeat'), ('Charon', 'informative'), ('Aoede', 'breezy'),
        ('Leda', 'youthful'), ('Orus', 'firm'), ('Zephyr', 'bright'), ('Sulafat', 'warm'),
        ('Achird', 'friendly'), ('Iapetus', 'clear')))
    note = '复用「供应商」里的 Google 连接；逐句合成，光标按句移动。'

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        base = (credential.get('base_url') or self.default_base).rstrip('/')
        response = self._post(f'{base}/models/{model}:generateContent',
                              headers={'x-goog-api-key': credential['api_key']},
                              payload={'contents': [{'parts': [{'text': text}]}],
                                       'generationConfig': {'responseModalities': ['AUDIO'],
                                           'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}}})
        try:
            part = next(p for p in response.json()['candidates'][0]['content']['parts'] if 'inlineData' in p)
        except (KeyError, IndexError, StopIteration, ValueError) as error:
            raise SpeechError(f'Gemini 没有返回音频：{_detail(response)}') from error
        mime = part['inlineData'].get('mimeType', '')
        sample_rate = (re.search(r'rate=(\d+)', mime) or [None, '24000'])[1]
        # Raw little-endian PCM: ffmpeg cannot sniff it, so it is told.
        return Clip(base64.b64decode(part['inlineData']['data']),
                    input_args=('-f', 's16le', '-ar', sample_rate, '-ac', '1'))


# ── ElevenLabs ─────────────────────────────────────────────────────────────────

class ElevenLabs(Provider):
    id, name = 'elevenlabs', 'ElevenLabs'
    timestamps = True
    custom_voice = True
    key_env = 'ELEVENLABS_API_KEY'
    default_base = 'https://api.elevenlabs.io/v1'
    models = ('eleven_multilingual_v2', 'eleven_turbo_v2_5', 'eleven_flash_v2_5')
    voices = (Voice('JBFqnCBsd6RMkjVDRZzb', 'George'), Voice('21m00Tcm4TlvDq8ikWAM', 'Rachel'),
              Voice('EXAVITQu4vr4xnSDxMaL', 'Sarah'), Voice('pNInz6obpgDQGcFmaJgB', 'Adam'),
              Voice('nPczCjzI2devNBz1zQrb', 'Brian'), Voice('XB0fDUnXU5powFXDhCwa', 'Charlotte'),
              Voice('pFZP5JQG7iQjIQuC4Bku', 'Lily'), Voice('onwK4e9ZLuTAKqWW03F9', 'Daniel'))
    note = '需要 ElevenLabs 自己的 Key；返回逐字时间戳，可整段合成。也可填克隆音色 ID。'

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        response = self._post(f'{self.default_base}/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128',
                              headers={'xi-api-key': credential['api_key']},
                              payload={'text': text, 'model_id': model})
        try:
            body = response.json()
            audio = base64.b64decode(body['audio_base64'])
            alignment = body.get('alignment') or body['normalized_alignment']
            chars = alignment['characters']
            starts = alignment['character_start_times_seconds']
            ends = alignment['character_end_times_seconds']
        except (KeyError, TypeError, ValueError) as error:
            raise SpeechError(f'ElevenLabs 没有返回时间戳：{_detail(response)}') from error
        # Character events are a valid granularity for both aligners in tts.py
        # and cue_alignment.py: they normalise and match text, not word counts.
        events = [{'text': c, 'start': s, 'duration': max(e - s, 0)}
                  for c, s, e in zip(chars, starts, ends) if c.strip()]
        return Clip(audio, events=events)


# ── MiniMax ────────────────────────────────────────────────────────────────────

class MiniMax(Provider):
    id, name = 'minimax', 'MiniMax'
    pi_ids = ('minimax', 'minimax-cn')
    custom_voice = True
    models = ('speech-02-hd', 'speech-02-turbo')
    voices = (Voice('female-shaonv', '少女'), Voice('female-yujie', '御姐'),
              Voice('female-chengshu', '成熟女性'), Voice('male-qn-qingse', '青涩青年'),
              Voice('male-qn-jingying', '精英青年'), Voice('presenter_female', '女性主持人'),
              Voice('presenter_male', '男性主持人'), Voice('audiobook_female_1', '有声书女声'),
              Voice('audiobook_male_1', '有声书男声'))
    note = '复用「供应商」里的 MiniMax 连接；中文音色丰富，逐句合成。'

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        # Pi's MiniMax endpoint is its chat API (…/anthropic or …/v1); speech is
        # on the same host under /v1/t2a_v2.
        parts = urlsplit(credential.get('base_url') or '')
        host = f'{parts.scheme}://{parts.netloc}' if parts.netloc else (
            'https://api.minimaxi.com' if credential.get('via') == 'minimax-cn' else 'https://api.minimax.io')
        response = self._post(host + '/v1/t2a_v2',
                              headers={'Authorization': 'Bearer ' + credential['api_key']},
                              payload={'model': model, 'text': text, 'stream': False,
                                       'voice_setting': {'voice_id': voice, 'speed': 1, 'vol': 1, 'pitch': 0},
                                       'audio_setting': {'sample_rate': 32000, 'bitrate': 128000,
                                                         'format': 'mp3', 'channel': 1}})
        body = response.json()
        status = (body.get('base_resp') or {})
        if status.get('status_code') not in (0, None):
            raise SpeechError(f'MiniMax 语音合成失败：{status.get("status_msg") or status.get("status_code")}')
        try:
            return Clip(bytes.fromhex(body['data']['audio']))
        except (KeyError, TypeError, ValueError) as error:
            raise SpeechError(f'MiniMax 没有返回音频：{_detail(response)}') from error


# ── registry ───────────────────────────────────────────────────────────────────

PROVIDERS = {p.id: p for p in (Edge(), OpenAI(), Gemini(), ElevenLabs(), MiniMax())}
DEFAULT = 'edge'


def get(provider_id: str | None) -> Provider:
    """The provider by ID. An unknown one (a stale .env) narrates with Edge
    rather than failing a whole job over a setting the UI would not offer."""
    return PROVIDERS.get(provider_id or DEFAULT) or PROVIDERS[DEFAULT]


def catalog() -> list[dict]:
    return [p.describe() for p in PROVIDERS.values()]


# ── own-key store, for providers Pi does not know ────────────────────────────────

def _key_file():
    # Beside Pi's credential store, so each workspace has its own exactly as it
    # does for Pi -- see tenant.credential_file.
    return tenant.credential_file().with_name('speech-credentials.json')


def _stored_keys() -> dict:
    path = _key_file()
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_keys(keys: dict):
    path = _key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(keys), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def store_key(provider_id: str, api_key: str) -> dict:
    provider = PROVIDERS.get(provider_id)
    if not provider or not provider.key_env:
        raise SpeechError('该语音供应商使用「供应商」里的连接，不单独保存 Key')
    api_key = (api_key or '').strip()
    if not api_key or not re.fullmatch(r'[\x21-\x7E]{8,256}', api_key):
        raise SpeechError('API Key 格式无效')
    _write_keys({**_stored_keys(), provider_id: api_key})
    return {'id': provider_id, **provider.status()}


def forget_key(provider_id: str) -> dict:
    keys = _stored_keys()
    keys.pop(provider_id, None)
    _write_keys(keys)
    return {'id': provider_id, **get(provider_id).status()}
