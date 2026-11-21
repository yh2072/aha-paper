"""The stage is one canvas this app draws on, and nothing else.

What this used to pin: a sandboxed iframe holding a Canvas animation Pi had
written, handed over as `srcdoc` because an opaque-origin `src` never loads in
some embedded browsers. That whole surface is gone -- no model-authored page is
executed any more -- and these tests now hold the stronger property: there is no
frame to sandbox, so there is nothing for a sandbox escape to escape from.
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PLAYER = (WEB / "explainer-player.js").read_text()
WATCH = (WEB / "watch.html").read_text()


class NoExecutedPageTests(unittest.TestCase):
    def test_the_watch_page_embeds_no_frame(self):
        self.assertIsNone(re.search(r"<iframe", WATCH, re.I),
                          "an iframe is a place for someone else's code to run")

    def test_the_player_never_hands_a_document_to_a_frame(self):
        for shape in ("srcdoc", "contentWindow", "postMessage", "loadScene"):
            self.assertNotIn(shape, PLAYER, f"{shape} belongs to the removed Canvas path")

    def test_the_stage_still_draws_on_its_own_canvas(self):
        self.assertIn("getContext('2d')", PLAYER)
        self.assertRegex(WATCH, r"<canvas[^>]*figure-canvas")


class VisualKindTests(unittest.TestCase):
    """Two kinds survive: the paper's own figure, and the paper's own page."""

    def test_every_shipped_kind_is_handled(self):
        for kind in ("'figure'", "'page'"):
            self.assertIn(kind, PLAYER, f"the player stopped handling {kind}")

    def test_no_drawn_picture_kind_is_routed_any_more(self):
        """Both engines that drew something the paper does not contain are gone."""
        for kind in ("==='canvas'", "==='diagram'"):
            self.assertNotIn(kind, PLAYER)


if __name__ == "__main__":
    unittest.main()
