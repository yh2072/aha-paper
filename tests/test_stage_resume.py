"""A chapter that has not been given its visual must not pass as finished work.

The bug this pins: the stage's resume check only asked whether a file existed at
code_path. A rejected scene therefore looked complete on the next run, the stage
was skipped forever, and the project reported 深度互动讲解完成 ✓ with static
chapters.

The Canvas engine that wrote those pages is gone. The same trap remains, aimed
the other way: a `code/scene_NN.html` an old run left on disk is now exactly the
thing that must *not* count, or a project built by the old engine would never be
rebuilt into the paper-reading view.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app import jobs
from app.pipeline import deep_script

STALE_CANVAS = ("<!doctype html><meta charset=\"utf-8\"><canvas id=film></canvas>"
                "<script>function draw(ctx,t,duration){}</script>")


def scene_with(directory, kind, name, body='{}'):
    path = Path(directory) / name
    path.write_text(body)
    return {kind: str(path)}


def meta(scenes, profile=deep_script.PROFILE):
    return {'storyboard': {'scenes': scenes}, 'script_profile': profile}


class ResumeTests(unittest.TestCase):
    def test_a_figure_chapter_needs_nothing_else(self):
        self.assertTrue(jobs._code_done(None, meta([{'figure_path': '/x/fig.png'}])))

    def test_a_chapter_reading_the_paper_counts_as_done(self):
        with TemporaryDirectory() as directory:
            scenes = [scene_with(directory, 'page_plan', 'seg_00.pages.json'),
                      {'figure_path': '/x/fig.png'}]
            self.assertTrue(jobs._code_done(None, meta(scenes)))

    def test_a_schematic_an_older_run_left_behind_does_not_count(self):
        """The narrated schematic is gone with the Canvas engine; a chapter that
        still has one must be rebuilt into the paper-reading view."""
        with TemporaryDirectory() as directory:
            self.assertFalse(jobs._code_done(
                None, meta([scene_with(directory, 'cue_plan_path', 'plan.json')])))

    def test_a_canvas_page_left_by_the_old_engine_does_not_count(self):
        """The whole reason this check still exists. Every project built before the
        paper-reading view has these files; they must send the stage back."""
        with TemporaryDirectory() as directory:
            scenes = [scene_with(directory, 'code_path', 'scene_00.html', STALE_CANVAS)]
            self.assertFalse(jobs._code_done(None, meta(scenes)))

    def test_a_plan_whose_file_is_gone_does_not_count(self):
        with TemporaryDirectory() as directory:
            scenes = [scene_with(directory, 'page_plan', 'seg_00.pages.json')]
            Path(scenes[0]['page_plan']).unlink()
            self.assertFalse(jobs._code_done(None, meta(scenes)))

    def test_a_chapter_with_nothing_at_all_does_not_count(self):
        self.assertFalse(jobs._code_done(None, meta([{'text': '一段旁白。'}])))

    def test_a_project_without_a_storyboard_is_not_done(self):
        self.assertFalse(jobs._code_done(None, {}))


if __name__ == '__main__':
    unittest.main()
