"""The override layer has to actually win.

web/refine.css is loaded last and repaints everything. That works only where it
is at least as specific as the sheet it overrides, and home.css writes its
colours as `.aha-home .thing` -- two classes -- while the natural thing to write
in an override is `.thing`. One class loses, whatever the load order, and the
result is invisible until you reach the state that shows it: the primary button
on a project card, the primary button inside a dialog, a toast.

Twelve rules were stranded that way after the repaint. This test is the check
that found them, kept, because the trap is structural and will be walked into
again by anyone adding a colour.
"""
import re
import unittest
from pathlib import Path

from app import config

WEB = config.ROOT / "web"
RULE = re.compile(r"([^{}]+)\{([^}]*)\}")
COLOUR = re.compile(r"(?:background|color|border-color)\s*:\s*(#[0-9a-fA-F]{3,8})")


def specificity(selector: str) -> tuple[int, int, int]:
    """Enough of the cascade to compare two class-based selectors."""
    ids = selector.count("#")
    classes = len(re.findall(r"\.[a-zA-Z-]+|\[", selector))
    return (ids, classes, 0)


COMMENT = re.compile(r"/\*.*?\*/", re.S)


def rules(sheet: str) -> list[tuple[str, str]]:
    # Comments first. Without this a rule that follows one is read as a selector
    # with the whole comment glued to the front, and matches nothing -- which
    # made this check silently pass over every documented rule in refine.css.
    sheet = COMMENT.sub("\n", sheet)
    out = []
    for selectors, body in RULE.findall(sheet):
        for selector in selectors.split(","):
            out.append((selector.strip(), body))
    return out


class OverrideTests(unittest.TestCase):
    def test_every_prefixed_colour_rule_is_out_specified(self):
        home = (WEB / "home.css").read_text()
        refine = rules((WEB / "refine.css").read_text())

        stranded = []
        for selector, body in rules(home):
            if not selector.startswith(".aha-home ") or not COLOUR.search(body):
                continue
            tail = selector.replace(".aha-home ", "", 1)
            if not any(other in (selector, tail) and specificity(other) >= specificity(selector)
                       for other, _ in refine):
                stranded.append(f"{selector}  ->  {' '.join(sorted(set(COLOUR.findall(body))))}")

        self.assertEqual(stranded, [], "these keep the old palette whatever refine.css says")

    def test_the_palette_is_defined_in_one_place(self):
        """A hard-coded colour in the override layer is a colour that will not
        move the next time the palette does."""
        refine = (WEB / "refine.css").read_text()
        body = refine[refine.index("/* ---------- ground ----------"):]
        literals = {c for c in re.findall(r"#[0-9a-fA-F]{3,8}", body)}
        # Tints that exist only as one rule's wash are allowed; what must not
        # appear is a second copy of a token's own value.
        tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,8})", refine))
        duplicated = sorted(c for c in literals if c in set(tokens.values()))
        self.assertEqual(duplicated, [], "use the token, not its value")


class ContrastTests(unittest.TestCase):
    """No pure black and no pure white: the palette's first rule, and the one a
    later edit is most likely to undo by reaching for #fff out of habit."""

    def test_the_ground_and_the_ink_are_never_neutral(self):
        refine = (WEB / "refine.css").read_text()
        tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", refine))
        for name in ("paper", "card", "ink", "panel"):
            value = tokens[name].lower()
            self.assertNotIn(value, ("#ffffff", "#000000"), name)
            red, green, blue = (int(value[i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreater(max(red, green, blue) - min(red, green, blue), 2,
                               f"--{name} is a neutral grey")


if __name__ == "__main__":
    unittest.main()
