"""Speech providers: the voice may come from anywhere, the timing may not be guessed.

The fake provider below returns real PCM, so the stitching path runs end to end
through ffmpeg without a network or a key.
"""
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from app import config, lang, studio_settings
from app.pipeline import speech, tts


def tone(seconds: float, rate: int = 24000) -> bytes:
    return b'\x10\x00' * int(seconds * rate)


class FakeStitched(speech.Provider):
    """Audio only, one second per character of normalised text -- easy to assert on."""
    id, name = 'fake', 'Fake'
    voices = (speech.Voice('v1', 'V1'),)

    def __init__(self):
        self.asked = []

    def credential(self):
        return {'api_key': 'k'}

    def synthesize(self, text, voice, model, credential, rate='+0%'):
        self.asked.append(text)
        return speech.Clip(tone(0.1 * len(tts._norm(text))),
                           input_args=('-f', 's16le', '-ar', '24000', '-ac', '1'))


class ProviderChoiceTests(unittest.TestCase):
    def test_default_is_edge_and_its_cache_key_is_unchanged(self):
        """Existing narration caches were keyed this way; they must stay valid."""
        with patch.object(config, 'TTS_PROVIDER', 'edge'):
            self.assertTrue(tts.cache_identity(lang.ZH).startswith('edge-tts-v1|zh|zh-CN-'))

    def test_unknown_provider_falls_back_to_edge(self):
        self.assertIs(speech.get('no-such-thing'), speech.PROVIDERS['edge'])

    def test_multilingual_voice_is_kept_across_languages(self):
        gemini = speech.PROVIDERS['google']
        self.assertEqual(gemini.voice_for(lang.EN, 'Puck'), 'Puck')
        self.assertEqual(gemini.voice_for(lang.ZH, 'Puck'), 'Puck')

    def test_edge_voice_still_hands_over_to_the_narration_language(self):
        self.assertTrue(speech.PROVIDERS['edge'].voice_for(lang.EN, 'zh-CN-YunxiNeural').startswith('en-'))

    def test_cloned_voice_ids_are_allowed_only_where_the_provider_allows_them(self):
        self.assertTrue(speech.PROVIDERS['elevenlabs'].valid_voice('myClonedVoice123'))
        self.assertFalse(speech.PROVIDERS['openai'].valid_voice('myClonedVoice123'))
        self.assertEqual(speech.PROVIDERS['openai'].voice_for(lang.ZH, 'myClonedVoice123'), 'coral')

    def test_a_model_from_another_provider_is_not_sent(self):
        self.assertEqual(speech.PROVIDERS['google'].model_for('tts-1'), 'gemini-2.5-flash-preview-tts')
        self.assertEqual(speech.PROVIDERS['google'].model_for('gemini-9-tts'), 'gemini-9-tts')

    def test_provider_voice_and_model_all_change_the_cache_key(self):
        with patch.object(config, 'TTS_PROVIDER', 'openai'), patch.object(config, 'TTS_VOICE', 'nova'):
            nova = tts.cache_identity(lang.ZH)
            with patch.object(config, 'TTS_VOICE', 'onyx'):
                self.assertNotEqual(nova, tts.cache_identity(lang.ZH))
            with patch.object(config, 'TTS_MODEL', 'tts-1'):
                self.assertNotEqual(nova, tts.cache_identity(lang.ZH))
        with patch.object(config, 'TTS_PROVIDER', 'edge'):
            self.assertNotEqual(nova, tts.cache_identity(lang.ZH))


class StitchingTests(unittest.TestCase):
    def run_fake(self, sentences, stale_timestamps=False):
        fake = FakeStitched()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out = Path(directory.name) / 'seg.wav'
        if stale_timestamps:
            out.with_suffix('.timestamps.json').write_text('[]')
        with patch.object(tts, 'provider', return_value=fake), patch.object(tts, 'pause_after', return_value=0.0), \
                patch.object(config, 'EDGE_TTS_RATE', '+0%'):
            _, durations = tts.synthesize_sentences(sentences, out, log=lambda _: None)
        return fake, out, durations

    def test_each_sentence_duration_is_its_own_clip(self):
        fake, out, durations = self.run_fake(['第一句话。', '第二句。'])
        self.assertEqual(fake.asked, ['第一句话。', '第二句。'])
        for got, want in zip(durations, [0.4, 0.3]):
            self.assertAlmostEqual(got, want, places=3)
        with wave.open(str(out)) as audio:
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), sum(durations), places=3)

    def test_punctuation_only_fragments_are_not_sent(self):
        fake, _, durations = self.run_fake(['你好。', '……'])
        self.assertEqual(fake.asked, ['你好。'])
        self.assertEqual(durations[1], 0)

    def test_stale_word_timestamps_from_an_earlier_take_are_removed(self):
        """explainer.py would read them as this audio's timing."""
        _, out, _ = self.run_fake(['一句。'], stale_timestamps=True)
        self.assertFalse(out.with_suffix('.timestamps.json').exists())

    def test_pauses_count_into_the_sentence_before_them(self):
        fake = FakeStitched()
        with tempfile.TemporaryDirectory() as directory, patch.object(tts, 'provider', return_value=fake), \
                patch.object(tts, 'pause_after', side_effect=lambda s, f: 0.5 if f else 0.0), \
                patch.object(config, 'EDGE_TTS_RATE', '+0%'):
            _, durations = tts.synthesize_sentences(['一二。', '三。'], Path(directory) / 's.wav', log=lambda _: None)
        self.assertAlmostEqual(durations[0], 0.7, places=3)
        self.assertAlmostEqual(durations[1], 0.1, places=3)

    def test_rate_is_applied_when_the_provider_cannot(self):
        fake = FakeStitched()
        with tempfile.TemporaryDirectory() as directory, patch.object(tts, 'provider', return_value=fake), \
                patch.object(tts, 'pause_after', return_value=0.0), patch.object(config, 'EDGE_TTS_RATE', '+25%'):
            _, durations = tts.synthesize_sentences(['一二三四五。'], Path(directory) / 's.wav', log=lambda _: None)
        self.assertAlmostEqual(durations[0], 0.5 / 1.25, places=2)

    def test_provider_errors_surface_as_job_errors(self):
        class Broken(FakeStitched):
            def synthesize(self, *a, **k):
                raise speech.SpeechError('Fake 语音合成失败（HTTP 401）：bad key')
        with tempfile.TemporaryDirectory() as directory, patch.object(tts, 'provider', return_value=Broken()):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 401'):
                tts.synthesize_sentences(['一句。'], Path(directory) / 's.wav', log=lambda _: None)


class TimestampedTakeTests(unittest.TestCase):
    def test_character_timestamps_drive_sentence_durations(self):
        """ElevenLabs returns characters, not words; the aligner only needs text and times."""
        events = [{'text': c, 'start': i * 0.25} for i, c in enumerate('第一句第二句')]
        self.assertEqual(tts.sentence_durations(['第一句。', '第二句。'], events, 2.0), [0.75, 1.25])


class SpeechSettingsTests(unittest.TestCase):
    def save(self, values):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = Path(directory.name) / '.env'
        with patch.object(config, 'ENV_FILE', env), patch.object(config, 'TTS_PROVIDER', 'edge'), \
                patch.object(config, 'TTS_VOICE', ''), patch.object(config, 'TTS_MODEL', ''):
            studio_settings.save_settings(values)
            return env.read_text() if env.exists() else ''

    def test_a_non_edge_voice_goes_to_tts_voice_and_edge_keeps_its_own(self):
        written = self.save({'tts_provider': 'openai', 'tts_model': 'tts-1', 'voice': 'nova'})
        self.assertIn("TTS_VOICE='nova'", written)
        self.assertNotIn('EDGE_TTS_VOICE', written)

    def test_a_voice_is_checked_against_the_provider_it_is_saved_with(self):
        with self.assertRaises(ValueError):
            self.save({'tts_provider': 'openai', 'voice': 'zh-CN-XiaoxiaoNeural'})
        with self.assertRaises(ValueError):
            self.save({'tts_provider': 'nonsense'})

    def test_a_blank_model_is_allowed(self):
        self.save({'tts_provider': 'edge', 'tts_model': '', 'voice': 'zh-CN-YunxiNeural'})


class OwnKeyStoreTests(unittest.TestCase):
    def test_a_key_is_stored_privately_and_never_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(speech.tenant, 'credential_file', return_value=Path(directory) / 'credentials.json'), \
                patch.dict('os.environ', {'ELEVENLABS_API_KEY': ''}):
            status = speech.store_key('elevenlabs', 'sk_secret_value_123')
            stored = Path(directory) / 'speech-credentials.json'
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('sk_secret_value_123', json.dumps(status))
            self.assertNotIn('sk_secret_value_123', json.dumps(speech.catalog()))
            self.assertTrue(speech.PROVIDERS['elevenlabs'].status()['configured'])
            speech.forget_key('elevenlabs')
            self.assertFalse(speech.PROVIDERS['elevenlabs'].status()['configured'])

    def test_pi_backed_providers_do_not_take_a_key_here(self):
        with self.assertRaises(speech.SpeechError):
            speech.store_key('openai', 'sk-whatever-123')


if __name__ == '__main__':
    unittest.main()
