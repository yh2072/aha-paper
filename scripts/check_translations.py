#!/usr/bin/env python3
"""Every user-facing Chinese error raised in app/ must have an English twin.

The interface is translated by web/i18n.js, which matches a Chinese source
string either exactly (DICT) or against a template whose {} stands for an
interpolated value (RULES). An f-string's {value} is therefore normalised to {}
before the lookup -- that is precisely the shape i18n.js compiles.

Run it directly; it needs nothing installed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAISE = re.compile(
    r"""raise\s+(?:ValueError|RuntimeError|HTTPException)\s*\(\s*(?:\d+\s*,\s*)?(f?)(['"])(.+?)\2""")
HAN = re.compile(r'[一-鿿]')


def main() -> int:
    catalogue = (ROOT / 'web' / 'i18n.js').read_text(encoding='utf-8')
    missing = []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        for match in RAISE.finditer(path.read_text(encoding='utf-8')):
            is_fstring, _, text = match.groups()
            if not HAN.search(text):
                continue
            template = re.sub(r'\{[^{}]*\}', '{}', text) if is_fstring else text
            if template not in catalogue:
                missing.append((path.relative_to(ROOT).as_posix(), template))
    if missing:
        print(f'{len(missing)} Chinese message(s) have no English twin in web/i18n.js:\n')
        for where, text in missing:
            print(f'  {where}\n    {text}\n')
        print('Add an exact entry to DICT, or a {}-templated pair to RULES.')
        return 1
    print('All Chinese messages raised in app/ are covered by web/i18n.js.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
