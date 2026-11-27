"""The icon cover: optional AI art must never cost the run its last step."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, jobs, llm, main, studio_settings
from app.pipeline import art_cover, icon_cover


class RenderTests(unittest.TestCase):
    def test_every_vendored_icon_renders_something(self):
        for name in icon_cover.icons():
            with self.subTest(name):
                alpha = icon_cover.render(name, 48).getchannel('A')
                self.assertGreater(alpha.getbbox() and sum(alpha.histogram()[128:]), 20)

    def test_a_half_circle_arc_ends_where_it_says(self):
        (points, closed), = icon_cover.path_lines('M2 12A10 10 0 0 1 22 12')
        self.assertFalse(closed)
        self.assertAlmostEqual(points[-1][0], 22, places=6)
        self.assertAlmostEqual(min(y for _, y in points), 2, places=1)  # goes over the top

    def test_packed_arc_flags_and_relative_moves_parse(self):
        (points, _), = icon_cover.path_lines('m4 4a1 1 0 011 1h2')
        self.assertAlmostEqual(points[-1][0], 7)
        self.assertAlmostEqual(points[-1][1], 5)

    def test_an_unknown_element_is_refused_rather_than_drawn_wrong(self):
        with self.assertRaises(ValueError):
            icon_cover.shape_lines('text', {})


class ChoiceTests(unittest.TestCase):
    meta = {'paper_title': 'A survey on LLM-based multi-agent systems'}

    def test_the_models_pick_is_used_when_it_is_in_the_list(self):
        with patch.object(llm, 'chat_json', return_value={'icon': 'network'}):
            self.assertEqual(icon_cover.choose_icon(self.meta, log=lambda _: None), 'network')

    def test_an_invented_name_or_a_failure_falls_back(self):
        with patch.object(llm, 'chat_json', return_value={'icon': 'robot-octopus'}):
            self.assertEqual(icon_cover.choose_icon(self.meta, log=lambda _: None), icon_cover.FALLBACK)
        with patch.object(llm, 'chat_json', side_effect=RuntimeError('HTTP 500')):
            self.assertEqual(icon_cover.choose_icon(self.meta, log=lambda _: None), icon_cover.FALLBACK)


class FakeProject:
    def __init__(self, directory):
        self.dir, self.meta, self.lines = Path(directory), {'engine': 'pi-canvas', 'title': '一篇论文'}, []

    def load(self):
        return dict(self.meta)

    def save(self, **values):
        self.meta.update(values)
        return dict(self.meta)

    def log(self, line):
        self.lines.append(line)


class CoverStageTests(unittest.TestCase):
    def stage(self, ai_cover, connected, art=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        proj = FakeProject(directory.name)
        with patch.object(config, 'AI_COVER', ai_cover), \
                patch.object(jobs.pi_models, 'check', return_value={'configured': connected}), \
                patch.object(art_cover, 'generate', side_effect=art or AssertionError('AI cover was not wanted')), \
                patch.object(icon_cover, 'choose_icon', return_value='atom'):
            jobs._st_cover(proj, {})
            done = jobs._cover_done(proj, proj.meta)
        return proj, done

    def test_switched_off_never_calls_the_image_model(self):
        proj, done = self.stage(ai_cover=False, connected=True)
        self.assertEqual(proj.meta['cover_engine'], 'icon')
        self.assertTrue((proj.dir / 'images' / 'cover.png').exists())
        self.assertTrue(done)

    def test_no_image_provider_gives_an_icon_cover_not_a_failed_run(self):
        proj, _ = self.stage(ai_cover=True, connected=False)
        self.assertEqual(proj.meta['cover_engine'], 'icon')
        self.assertTrue(any('未连接' in line for line in proj.lines))

    def test_a_failing_image_api_falls_back_to_the_icon(self):
        proj, done = self.stage(ai_cover=True, connected=True, art=RuntimeError('HTTP 402'))
        self.assertEqual(proj.meta['cover_engine'], 'icon')
        self.assertTrue(any('HTTP 402' in line for line in proj.lines))
        self.assertFalse(done)  # AI covers are wanted and possible: try again next run

    def test_an_ai_cover_is_used_when_it_works(self):
        def draw(meta, out, log):
            out.mkdir(parents=True, exist_ok=True)
            (out / 'cover.png').write_bytes(b'png')
            return 'cover.png'
        proj, done = self.stage(ai_cover=True, connected=True, art=draw)
        self.assertEqual(proj.meta['cover_engine'], 'ai-image')
        self.assertTrue(done)


class SettingsTests(unittest.TestCase):
    def test_both_switches_reach_save_settings_through_the_api_model(self):
        """Without fields on the model, pydantic dropped them before they were saved."""
        body = main.StudioSettings(ai_cover=False, script_audit=True).model_dump(exclude_none=True)
        self.assertEqual(body, {'ai_cover': False, 'script_audit': True})

    def test_the_switch_is_written_to_the_env_file(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, 'ENV_FILE', Path(directory) / '.env'), \
                patch.object(config, 'AI_COVER', True), patch.dict('os.environ', {}):
            studio_settings.save_settings({'ai_cover': False})
            self.assertIn("AHA_AI_COVER='0'", (Path(directory) / '.env').read_text())
            self.assertFalse(config.AI_COVER)


if __name__ == '__main__':
    unittest.main()
