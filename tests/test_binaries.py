"""Finding ffmpeg, ffprobe and node.

The reason this module exists is packaging: an .app bundle carries its own
ffmpeg so the user does not have to install one, and a bare "ffmpeg" in a
subprocess list can never find it. So the tests that matter are the ones about
precedence, and the one that proves no call site writes the bare name any more.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import bin as binaries, config

VARS = ("AHA_FFMPEG", "AHA_FFPROBE", "AHA_NODE", "AHA_BIN_DIR")


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if k not in VARS}
        self.env = patch.dict(os.environ, clean, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_path_is_the_default(self):
        """Nothing set is the development case, and it must keep working."""
        self.assertTrue(binaries.ffmpeg().endswith("ffmpeg"))

    def test_a_bundled_directory_wins_over_path(self):
        """This is the whole point: the copy inside the bundle, not the one the
        user may or may not have installed."""
        with tempfile.TemporaryDirectory() as directory:
            shipped = Path(directory) / "ffmpeg"
            shipped.write_text("")
            with patch.dict(os.environ, {"AHA_BIN_DIR": directory}):
                self.assertEqual(binaries.ffmpeg(), str(shipped))

    def test_an_explicit_override_wins_over_the_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(directory) / "ffmpeg"
            bundled.write_text("")
            picked = Path(directory) / "my-ffmpeg"
            picked.write_text("")
            with patch.dict(os.environ, {"AHA_BIN_DIR": directory,
                                         "AHA_FFMPEG": str(picked)}):
                self.assertEqual(binaries.ffmpeg(), str(picked))

    def test_a_bundle_without_the_program_falls_through_to_path(self):
        """A build that ships ffmpeg but not node must still find node."""
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"AHA_BIN_DIR": directory}):
                self.assertTrue(binaries.node().endswith("node"))

    def test_an_override_pointing_nowhere_is_not_silently_ignored(self):
        """Falling back to PATH here would hide a broken build: the bundle would
        look fine while quietly using whatever the machine happens to have."""
        with patch.dict(os.environ, {"AHA_FFMPEG": "/nope/ffmpeg"}):
            with self.assertRaises(RuntimeError):
                binaries.ffmpeg()

    def test_nothing_is_cached_between_calls(self):
        """The desktop shell sets these before starting the server; a cache would
        freeze whatever the environment looked like at import time."""
        with tempfile.TemporaryDirectory() as directory:
            shipped = Path(directory) / "ffprobe"
            shipped.write_text("")
            first = binaries.ffprobe()
            with patch.dict(os.environ, {"AHA_BIN_DIR": directory}):
                self.assertEqual(binaries.ffprobe(), str(shipped))
            self.assertEqual(binaries.ffprobe(), first)

    def test_a_missing_program_names_itself_and_its_job(self):
        with patch.object(binaries, "_find", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
                binaries.ffmpeg()

    def test_missing_lists_what_is_absent_without_raising(self):
        with patch.object(binaries, "_find", return_value=None):
            self.assertEqual(set(binaries.missing()), set(binaries.PROGRAMS))
        self.assertEqual(binaries.missing(), [])


class CallSiteTests(unittest.TestCase):
    """The refactor is only as good as its coverage of the call sites."""

    BARE = re.compile(r'\[\s*["\'](ffmpeg|ffprobe|node)["\']')

    def test_no_module_shells_out_to_a_bare_program_name(self):
        offenders = []
        for path in sorted((config.ROOT / "app").rglob("*.py")):
            if path.name == "bin.py":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if self.BARE.search(line):
                    offenders.append(f"{path.relative_to(config.ROOT)}:{number}")
        self.assertEqual(offenders, [], "these would never find a bundled copy")

    def test_the_health_endpoint_reports_what_is_missing(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch.object(config, "ACCESS_PASSWORD", ""):
            body = TestClient(app).get("/api/health").json()
        self.assertIn("missing_tools", body)
        self.assertIsInstance(body["missing_tools"], list)


class ProviderBridgeTests(unittest.TestCase):
    def test_the_provider_cli_runs_through_the_resolver(self):
        """So a desktop build can hand it Electron's own Node and the user
        installs nothing."""
        source = (config.ROOT / "app" / "pi_models.py").read_text()
        self.assertIn("binaries.node()", source)
        self.assertNotIn("['node'", source)


if __name__ == "__main__":
    unittest.main()
