import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import config, jobs, studio_settings
from app.pipeline import tts

class NarrationTests(unittest.TestCase):
    def test_real_boundaries_drive_sentence_durations(self):
        events=[{'text':'第一句','start':0.1},{'text':'第二句','start':1.6}]
        self.assertEqual(tts.sentence_durations(['第一句。','第二句。'],events,3.1),[1.6,1.5])
    def test_missing_boundaries_fail_instead_of_estimating(self):
        with self.assertRaises(RuntimeError):tts.sentence_durations(['测试。'],[],1)
    def test_voice_or_rate_invalidates_audio_cache(self):
        old=tts.cache_identity()
        with patch.object(config,'EDGE_TTS_RATE','+20%'):
            self.assertNotEqual(old,tts.cache_identity())

class OrchestrationTests(unittest.TestCase):
    def test_full_generation_and_render_share_one_tracking_entry(self):
        with patch.object(jobs,'_run_generation') as generate,patch.object(jobs,'_run_tts_video') as render,patch.object(jobs.Project,'load',return_value={'state':'ready'}):
            generate.__wrapped__ = unittest.mock.Mock()
            render.__wrapped__ = unittest.mock.Mock()
            jobs._run_full_video.__wrapped__('sample')
            generate.__wrapped__.assert_called_once_with('sample')
            render.__wrapped__.assert_called_once_with('sample')
    def test_generation_failure_does_not_start_render(self):
        with patch.object(jobs,'_run_generation') as generate,patch.object(jobs,'_run_tts_video') as render,patch.object(jobs.Project,'load',return_value={'state':'error'}):
            generate.__wrapped__ = unittest.mock.Mock()
            render.__wrapped__ = unittest.mock.Mock()
            jobs._run_full_video.__wrapped__('sample')
            render.__wrapped__.assert_not_called()
    def test_an_unconnected_provider_does_not_queue_billable_work(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(config,'DATA_DIR',Path(directory)),\
             patch.object(jobs.pi_models,'check',return_value={'configured':False}),patch.object(jobs,'_submit') as submit:
            p=jobs.Project('sample');p.dir.mkdir();p.save(id='sample')
            with self.assertRaisesRegex(ValueError,'连接供应商'):jobs.start_full_video('sample')
            submit.assert_not_called()
    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):jobs.Project('../outside')

class SettingsTests(unittest.TestCase):
    def test_settings_hold_choices_only_never_a_credential(self):
        """Keys go to Pi's store through the provider login, never through this form."""
        with tempfile.TemporaryDirectory() as directory,patch.object(config,'ROOT',Path(directory)):
            public=studio_settings.save_settings({'voice':'zh-CN-YunxiNeural'})
            self.assertNotIn('api_key',studio_settings.save_settings.__doc__ or '')
            written=(Path(directory)/'.env').read_text()
            self.assertIn('EDGE_TTS_VOICE',written)
            self.assertNotIn('API_KEY',written)
            self.assertTrue(all('key' not in k.lower() for k in public))
    def test_invalid_settings_are_checked_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(config,'ROOT',Path(directory)):
            with self.assertRaises(ValueError):studio_settings.save_settings({'model_cover':'good/model','rate':'broken'})
            self.assertFalse((Path(directory)/'.env').exists())
    def test_uses_report_their_provider_and_connection(self):
        rows={u['use']:u for u in studio_settings.public_settings()['uses']}
        self.assertEqual(set(rows),{'language','image'})
        self.assertEqual(rows['image']['provider'],config.use_provider('image'))

if __name__=='__main__':unittest.main()
