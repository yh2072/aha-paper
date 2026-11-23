"""What has to be true before this can be handed to someone as an app.

A packaged bundle is read-only, and on macOS writing inside a signed bundle
invalidates its signature — so the first setting the user saves would break the
app's own code signature. Everything writable therefore has to resolve outside
the bundle, and that is a property of the code, not of the build config.

These tests run the real interpreter in a subprocess rather than reloading
modules in-process, because the paths are decided at import time and that is
exactly the thing being checked.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import config

ROOT = config.ROOT
PROBE = ("import json;from app import config;"
         "print(json.dumps({'state':str(config.STATE_DIR),'data':str(config.DATA_DIR),"
         "'env':str(config.ENV_FILE),'root':str(config.ROOT)}))")


def resolve(state_dir: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "AHA_STATE_DIR"}
    if state_dir:
        env["AHA_STATE_DIR"] = state_dir
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout.strip().splitlines()[-1])


class StateDirTests(unittest.TestCase):
    def test_a_checkout_keeps_everything_where_it_was(self):
        """Unset is the development case. A developer's existing data/ and .env
        must stay the ones they see."""
        paths = resolve(None)
        self.assertEqual(paths["state"], paths["root"])
        self.assertEqual(paths["data"], str(ROOT / "data"))
        self.assertEqual(paths["env"], str(ROOT / ".env"))

    def test_the_state_dir_moves_the_papers_and_the_env_together(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve(directory)
            self.assertEqual(paths["data"], str(Path(directory) / "data"))
            self.assertEqual(paths["env"], str(Path(directory) / ".env"))

    def test_the_code_root_does_not_move_with_it(self):
        """web/, models/ and scripts/ stay in the bundle; only the user's things
        move. Conflating the two would send the figure detector looking for its
        weights in the application-data directory."""
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve(directory)
            self.assertEqual(paths["root"], str(ROOT))
            self.assertNotEqual(paths["root"], paths["state"])

    def test_the_data_directory_is_created_even_when_its_parent_is_new(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory) / "never-existed"
            resolve(str(fresh))
            self.assertTrue((fresh / "data").is_dir())


class NothingWritableUnderTheBundleTests(unittest.TestCase):
    WRITABLE = re.compile(r'(config\.)?ROOT\s*/\s*[\'"]\.?(data|env|runtime)')

    def test_no_module_joins_the_code_root_with_a_writable_name(self):
        offenders = []
        for path in sorted((ROOT / "app").rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if self.WRITABLE.search(line) and "STATE_DIR" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}  {line.strip()}")
        self.assertEqual(offenders, [], "these would write inside a signed bundle")

    def test_the_provider_cli_follows_the_state_dir_too(self):
        """The credential store is the other thing that must not land in the
        bundle, and it is created by JavaScript, not Python."""
        source = (ROOT / "scripts" / "pi-auth.mjs").read_text()
        self.assertIn("AHA_STATE_DIR", source)
        self.assertNotIn("path.join(ROOT, '.runtime'", source)


class ShellContractTests(unittest.TestCase):
    """The shell is the only thing that knows the platform's conventions."""

    SHELL = ROOT / "desktop" / "main.cjs"

    def test_the_shell_hands_the_server_a_state_directory(self):
        source = self.SHELL.read_text()
        self.assertIn("AHA_STATE_DIR", source)
        self.assertIn("PI_CREDENTIAL_FILE", source)

    def test_the_shell_only_relocates_when_packaged(self):
        """From a checkout it must stay in the checkout, or `npm run desktop`
        would quietly stop showing a developer their own papers."""
        self.assertIn("app.isPackaged", self.SHELL.read_text())

    def test_the_shell_gives_the_server_its_own_node(self):
        self.assertIn("ELECTRON_RUN_AS_NODE", self.SHELL.read_text())


class BuildConfigTests(unittest.TestCase):
    """Decisions that are invisible until a build fails on someone else's Mac.

    Asserted as text because the project has no YAML parser, and adding a
    dependency to check a build file would be a poor trade.
    """

    CONFIG = (ROOT / "electron-builder.yml").read_text()
    SHELL = (ROOT / "desktop" / "main.cjs").read_text()

    def test_asar_is_off(self):
        """An asar archive is visible only to Node's patched fs. CPython reads
        app/, web/ and models/, and would find none of it."""
        self.assertRegex(self.CONFIG, r"(?m)^asar:\s*false\b")

    def test_the_runtime_lands_where_the_shell_looks_for_it(self):
        """extraResources `to:` and the shell's lookup are one contract written
        in two files; a rename on either side produces a build that starts and
        then cannot find its own interpreter."""
        self.assertRegex(self.CONFIG, r"to:\s*python\b")
        self.assertRegex(self.CONFIG, r"to:\s*bin\b")
        self.assertIn("process.resourcesPath || '', 'python'", self.SHELL)
        self.assertIn("process.resourcesPath || '', 'bin'", self.SHELL)

    def test_the_users_papers_are_not_shipped_inside_the_app(self):
        for excluded in ("!data/**", "!tests/**", "!runtime/**"):
            self.assertIn(excluded, self.CONFIG)

    def test_the_hardened_runtime_can_load_the_bundled_binaries(self):
        """Every wheel carries a native .so Apple never signed. Without this
        entitlement the app dies on `import onnxruntime`."""
        plist = (ROOT / "build" / "entitlements.mac.plist").read_text()
        self.assertIn("com.apple.security.cs.disable-library-validation", plist)

    def test_the_icon_exists_and_is_square(self):
        from PIL import Image
        with Image.open(ROOT / "build" / "icon.png") as image:
            self.assertEqual(image.size, (1024, 1024))


if __name__ == "__main__":
    unittest.main()
