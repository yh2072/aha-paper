#!/usr/bin/env python3
"""Every user-facing Chinese string produced by app/ must have an English twin.

Two kinds reach a reader, and both go through web/i18n.js, which matches a
Chinese source string either exactly (DICT) or against a template whose {}
stands for an interpolated value (RULES). An f-string's {value} is therefore
normalised to {} before the lookup -- precisely the shape i18n.js compiles.

  - errors raised in app/, which surface in a toast or on a project card
  - lines written to the run log, which studio.js translates one line at a time
    after splitting off the [HH:MM:SS] stamp and the indentation, so the key is
    the trimmed message

Run it directly; it needs nothing installed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (kind, pattern). Each pattern captures an optional f prefix, the quote, and
# the literal. Only the first line of an implicitly concatenated literal is
# seen, which is deliberate: the dictionary is keyed on whole rendered lines,
# and a continuation that is checked on its own would report a false miss.
SOURCES = (
    ('raised error', re.compile(
        r"""raise\s+(?:ValueError|RuntimeError|HTTPException)\s*\(\s*"""
        r"""(?:\d+\s*,\s*)?(f?)(['"])(.+?)\2""")),
    ('log line', re.compile(r"""\blog\(\s*(f?)(['"])(.+?)\2""")),
)
HAN = re.compile('[一-鿿]')


def missing_twins() -> list[tuple[str, str]]:
    catalogue = (ROOT / 'web' / 'i18n.js').read_text(encoding='utf-8')
    missing = []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        source = path.read_text(encoding='utf-8')
        for kind, pattern in SOURCES:
            for match in pattern.finditer(source):
                is_fstring, _, text = match.groups()
                if not HAN.search(text):
                    continue
                template = re.sub(r'\{[^{}]*\}', '{}', text) if is_fstring else text
                if kind == 'log line':
                    # Rendered without its stamp or indentation, so that is what
                    # the dictionary is asked about.
                    template = template.strip()
                if template not in catalogue:
                    missing.append((f'{path.relative_to(ROOT).as_posix()}  ({kind})', template))
    return missing


def main() -> int:
    missing = missing_twins()
    if missing:
        print(f'{len(missing)} Chinese message(s) have no English twin in web/i18n.js:\n')
        for where, text in missing:
            print(f'  {where}\n    {text}\n')
        print('Add an exact entry to DICT, or a {}-templated pair to RULES.')
        return 1
    print('All Chinese errors and log lines in app/ are covered by web/i18n.js.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
