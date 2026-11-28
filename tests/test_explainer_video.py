"""The explainer as an MP4: the same states as the player, timed by the narration."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import jobs
from app.bin import ffmpeg, ffprobe
from app.pipeline import explainer_video as ev


def project(directory: Path, seconds: float = 2.0) -> Path:
    """A two-chapter explainer: a page with a highlight, then a figure with a pointer."""
    (directory / 'pages').mkdir()
    (directory / 'figures').mkdir()
    Image.new('RGB', (600, 800), 'white').save(directory / 'pages' / 'page_01.png')
    Image.new('RGB', (800, 500), (220, 230, 240)).save(directory / 'figures' / 'fig_01.png')
    subprocess.run([ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i', f'anullsrc=r=24000:cl=mono',
                    '-t', str(seconds), str(directory / 'narration.mp3')], check=True)
    half = seconds / 2
    manifest = {'duration': seconds, 'audio': 'narration.mp3', 'segments': [
        {'title': '一', 'start': 0, 'end': half, 'visual': {'kind': 'page', 'pages': {'1': 'pages/page_01.png'}},
         'cues': [{'text': '第一句。', 'start': 0, 'end': half / 2, 'highlight': None},
                  {'text': '\n\n第二句，紧跟在一个段落换行之后。', 'start': half / 2, 'end': half,
                   'highlight': {'page': 1, 'rects': [[.1, .3, .5, .02]], 'keys': [{'rects': [[.1, .3, .1, .02]]}]}}]},
        {'title': '二', 'start': half, 'end': seconds, 'visual': {'kind': 'figure', 'url': 'figures/fig_01.png'},
         'cues': [{'text': '看左上角。', 'start': 0, 'end': half, 'region': [.05, .05, .3, .3]}]}]}
    (directory / 'experience.json').write_text(json.dumps(manifest, ensure_ascii=False))
    return directory


class PathTests(unittest.TestCase):
    def test_studio_and_bundle_urls_both_resolve_into_the_project(self):
        base = Path('/data/p')
        self.assertEqual(ev.local_path(base, '/files/p/pages/page%2002.png'), base / 'pages/page 02.png')
        self.assertEqual(ev.local_path(base, 'media/narration.mp3'), base / 'media/narration.mp3')


class LookupTests(unittest.TestCase):
    segments = [{'start': 0, 'end': 5, 'cues': [{'start': 0, 'end': 2}, {'start': 2, 'end': 5}]},
                {'start': 5, 'end': 9, 'cues': [{'start': 0, 'end': 4}]}]

    def test_time_maps_to_segment_and_cue_like_the_player(self):
        self.assertEqual(ev.locate(self.segments, 3.0), (0, 3.0, 1))
        self.assertEqual(ev.locate(self.segments, 6.0)[::2], (1, 0))

    def test_past_the_end_holds_the_last_cue(self):
        self.assertEqual(ev.locate(self.segments, 20.0)[::2], (1, 0))


class FrameTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = project(Path(directory.name), seconds=6)  # page cue 2 runs 1.5-3, figure 3-6
        self.renderer = ev.Renderer(self.dir, json.loads((self.dir / 'experience.json').read_text()))

    def test_a_settled_page_reuses_its_frame(self):
        first = self.renderer.frame(1.5 + ev.SETTLED + .1)
        self.assertTrue(first is self.renderer.frame(1.5 + ev.SETTLED + .2))

    def test_the_marker_shows_on_the_highlighted_cue(self):
        settled = Image.frombytes('RGB', ev.SIZE, self.renderer.frame(1.5 + ev.SETTLED))
        colours = {c for _, c in settled.getcolors(1 << 20)}
        self.assertTrue(any(r > 230 and b < 200 for r, g, b in colours))  # the yellow band

    def test_the_figure_pointer_keeps_moving(self):
        self.assertTrue(self.renderer.frame(3.6) != self.renderer.frame(3.8))


class RenderTests(unittest.TestCase):
    def test_the_mp4_has_video_and_audio_of_the_narrations_length(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            ev.render(project(Path(directory)), out, log=lambda _: None)
            probe = subprocess.run([ffprobe(), '-v', 'error', '-show_entries', 'stream=codec_type,duration',
                                    '-of', 'json', str(out)], capture_output=True, text=True, check=True)
            streams = {s['codec_type']: float(s['duration']) for s in json.loads(probe.stdout)['streams']}
            self.assertEqual(set(streams), {'video', 'audio'})
            self.assertAlmostEqual(streams['video'], 2.0, delta=.1)
            self.assertFalse((Path(directory) / 'out.partial.mp4').exists())


class FailedFrameTests(unittest.TestCase):
    def test_a_frame_that_fails_stops_the_encoder_and_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'out.mp4'
            with patch.object(ev.Renderer, 'frame', side_effect=ValueError("can't measure")):
                with self.assertRaises(ValueError):
                    ev.render(project(Path(directory)), out, log=lambda _: None)
            self.assertEqual([p.name for p in Path(directory).glob('*.mp4')], [])


class JobRoutingTests(unittest.TestCase):
    def test_an_explainer_exports_its_own_recording_not_the_slideshow(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(jobs.config, 'DATA_DIR', Path(directory)):
            proj = jobs.Project('p')
            proj.dir.mkdir(parents=True, exist_ok=True)
            proj.save(engine='pi-canvas', experience_mode='explainer', interactive='experience.json')
            (proj.dir / 'experience.json').write_text('{}')
            with patch.object(ev, 'render') as render, \
                    patch.object(jobs.slideshow, 'render_slideshow', side_effect=AssertionError('slideshow')):
                jobs._run_tts_video.__wrapped__('p', True)
            self.assertEqual(render.call_args.args[1], proj.dir / jobs.EXPLAINER_MP4)
            self.assertEqual(proj.load()['tts_output'], jobs.EXPLAINER_MP4)

    def test_a_queued_export_stays_registered_until_it_runs(self):
        """start_tts_video once carried @_tracked twice: queuing an export released
        its registration at once, so a live export listed as interrupted and a
        second click rendered the same file from a second thread."""
        class Held:  # an executor that queues and never runs
            def submit(self, fn, *args):
                return None
        with patch.object(jobs, '_EXECUTOR', Held()), patch.object(jobs.Project, 'save'):
            try:
                jobs.start_tts_video('p')
                self.assertTrue(jobs._pending('p'))
            finally:
                with jobs._LOCK:
                    jobs._ACTIVE.pop(jobs._slot('p'), None)

    def test_a_second_export_request_while_one_runs_is_ignored(self):
        with patch.object(jobs, '_pending', return_value=True), patch.object(jobs, '_submit') as submit:
            jobs.start_tts_video('p')
        submit.assert_not_called()

    def test_a_failed_export_leaves_the_explainer_finished(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(jobs.config, 'DATA_DIR', Path(directory)):
            proj = jobs.Project('p')
            proj.dir.mkdir(parents=True, exist_ok=True)
            proj.save(engine='pi-canvas', experience_mode='explainer', interactive='experience.json', state='done')
            (proj.dir / 'experience.json').write_text('{}')
            with patch.object(ev, 'render', side_effect=FileNotFoundError('page_02.png')):
                jobs._run_tts_video.__wrapped__('p', True)
            meta = proj.load()
            self.assertEqual(meta['state'], 'done')
            self.assertIn('page_02.png', meta['error'])
            self.assertNotIn('tts_output', meta)


if __name__ == '__main__':
    unittest.main()
