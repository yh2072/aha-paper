"""The bilingual UI is a dictionary keyed on the Chinese source, so the thing that
breaks is not a crash -- it is a string that quietly stays Chinese when someone adds
a button. These tests scan the real assets and fail on an untranslated one.

They also pin the two deliberate exclusions, because both look like bugs:
motion-diagrams.js (its Chinese is regexes that match the narration -- translating it
would change which animation is chosen) and the paper's own words (never a key).
"""
import json
import re
import unittest
from pathlib import Path

from app import config

WEB = config.ROOT / 'web'
I18N = (WEB / 'i18n.js').read_text(encoding='utf-8')
HAN = re.compile(r'[㐀-䶿一-鿿]')

# Chinese here is animation content and matching logic, not interface. See the module docstring.
EXCLUDED_FILES = {'i18n.js'}
# Comment prose and dev-only log text that never reaches a translated node.
EXCLUDED = {
    '可重试环节清单，启动时拉一次', '数字人总开关（来自 /api/health）',
    '无变化/弹窗打开时不重绘', '服务是长驻进程，改了代码不重启就还跑旧的。不提示的话会以为',
    '改了没用', '未匹配:', '个文件', '选择导出文件夹',
}


def _block(name):
    start = I18N.index(f'const {name} = ')
    depth, i = 0, I18N.index('[' if name == 'RULES' else '{', start)
    open_c, close_c = ('[', ']') if name == 'RULES' else ('{', '}')
    for j in range(i, len(I18N)):
        if I18N[j] == open_c:
            depth += 1
        elif I18N[j] == close_c:
            depth -= 1
            if not depth:
                return I18N[i:j + 1]
    raise AssertionError(name)


QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
_unescape = lambda s: json.loads('"' + s.replace('"', '\\"') + '"')

DICT = {}
for line in re.finditer(r"'((?:[^'\\]|\\.)*)':\s*\n?\s*'((?:[^'\\]|\\.)*)'", _block('DICT')):
    DICT[_unescape(line.group(1))] = _unescape(line.group(2))

RULES = []
for entry in re.finditer(r"\[\s*'((?:[^'\\]|\\.)*)',\s*\n?\s*'((?:[^'\\]|\\.)*)'\s*,?\s*\]",
                         _block('RULES')):
    RULES.append((_unescape(entry.group(1)), _unescape(entry.group(2))))

RULE_RES = [re.compile('^' + '([\\s\\S]+?)'.join(map(re.escape, zh.split('{}'))) + '$')
            for zh, _ in RULES]


# Compared with placeholders stripped on both sides, so a fragment of a template
# ('当前有 {} 个任务在跑…') still matches the template it is part of.
KNOWN = [k.replace('{}', '') for k in list(DICT) + [zh for zh, _ in RULES]]


def covered(text):
    """A piece is covered when it is a key, matches a template, is a template whose
    placeholder can be empty (`🤖 ${x?'重跑':''}数字人推理`), or is one literal of a
    text node the browser assembles from several (the fragment case -- those are
    translated as the whole joined string at runtime)."""
    if text in DICT or text in EXCLUDED:
        return True
    if any(r.match(text) for r in RULE_RES):
        return True
    if '{}' in text and text.replace('{}', '') in DICT:
        return True
    bare = text.replace('{}', '')
    return bool(bare) and any(bare in key for key in KNOWN)


def _norm_template(body):
    """A template literal with every ${...} replaced by {}, plus the literals nested
    inside those interpolations, yielded separately.

    The unit that matters is the finished DOM text node, so `${n} 个模型` must be
    looked up as '{} 个模型' -- not as the fragment ' 个模型', which never appears
    on its own. Braces are counted because the minified source nests ternaries and
    further template literals inside interpolations."""
    out, buf, nested, i = [], '', [], 0
    while i < len(body):
        if body[i] == '\\':
            buf += body[i:i + 2]
            i += 2
            continue
        if body.startswith('${', i):
            buf += '{}'
            depth, i = 1, i + 2
            while i < len(body) and depth:
                c = body[i]
                if c == '\\':
                    i += 2
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                elif c in '`"\'':
                    quote, i, inner = c, i + 1, ''
                    while i < len(body) and body[i] != quote:
                        if body[i] == '\\':
                            inner += body[i:i + 2]
                            i += 2
                            continue
                        inner += body[i]
                        i += 1
                    if quote == '`':
                        nested.extend(_norm_template(inner))
                    else:
                        nested.append(inner)
                i += 1
            continue
        buf += body[i]
        i += 1
    out.append(buf)
    return out + nested


_REGEX_PRECEDERS = set('=(,:[!&|?{;+')


def _skip_regex(src, i):
    """Step over a regex literal starting at its opening slash. A pattern such as
    /[\\/:*?"<>|]/g holds a quote character, and reading that as a string opener
    swallows the rest of the file."""
    i += 1
    in_class = False
    while i < len(src) and src[i] != '\n':
        if src[i] == '\\':
            i += 2
            continue
        if src[i] == '[':
            in_class = True
        elif src[i] == ']':
            in_class = False
        elif src[i] == '/' and not in_class:
            return i + 1
        i += 1
    return i


def _read_quoted(src, i, quote):
    body = ''
    while i < len(src) and src[i] != quote:
        if src[i] == '\\':
            body += src[i:i + 2]
            i += 2
            continue
        if quote != '`' and src[i] == '\n':
            break
        body += src[i]
        i += 1
    return body, i + 1


def _read_template(src, i):
    """Consume a template literal body (i points just past the opening backtick).

    A backtick inside a ${...} interpolation opens a NESTED template; treating it as
    the terminator ends the outer literal early and mis-tokenizes everything after,
    which is exactly how `...${x?`a`:'b'}` used to leak whole functions."""
    body, prev = '', ''
    while i < len(src):
        c = src[i]
        if c == '\\':
            body += src[i:i + 2]
            i += 2
            continue
        if c == '`':
            return body, i + 1
        if src.startswith('${', i):
            body += '${'
            i, depth = i + 2, 1
            while i < len(src) and depth:
                c = src[i]
                if c == '\\':
                    body += src[i:i + 2]
                    i += 2
                    continue
                if c == '/' and src[i:i + 2] in ('//', '/*'):
                    i = (src.find('\n', i) if src[i + 1] == '/' else src.find('*/', i) + 2)
                    if i < 0:
                        break
                    continue
                if c == '/' and (prev == '' or prev in _REGEX_PRECEDERS):
                    i = _skip_regex(src, i)
                    prev = '/'
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if not depth:
                        body += '}'
                        i += 1
                        break
                elif c == '`':
                    inner, i = _read_template(src, i + 1)
                    body += '`' + inner + '`'
                    prev = '`'
                    continue
                elif c in '"\'':
                    inner, i = _read_quoted(src, i + 1, c)
                    body += c + inner + c
                    prev = c
                    continue
                body += c
                if not c.isspace():
                    prev = c
                i += 1
            continue
        body += c
        i += 1
    return body, i


def js_literals(src):
    """Normalized string literals from a script, comments and regexes skipped."""
    out, i, prev = [], 0, ''
    while i < len(src):
        c = src[i]
        if c == '/' and src[i:i + 2] == '//':
            j = src.find('\n', i)
            if j < 0:
                break
            i = j
            continue
        if c == '/' and src[i:i + 2] == '/*':
            j = src.find('*/', i)
            if j < 0:
                break
            i = j + 2
            continue
        if c == '/' and (prev == '' or prev in _REGEX_PRECEDERS):
            i = _skip_regex(src, i)
            prev = '/'
            continue
        if c == '`':
            body, i = _read_template(src, i + 1)
            out.extend(_norm_template(body))
            prev = '`'
            continue
        if c in '"\'':
            body, i = _read_quoted(src, i + 1, c)
            out.append(body)
            prev = c
            continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def _looks_like_code(s):
    """advanced.html's inline script is minified to the point where a scan without a
    full JS parser still mis-slices a few spots (an HTML on* handler nested inside a
    template literal). These markers cannot occur in interface prose."""
    return any(m in s for m in ("alert('", "=>", "');", "'}", '"}', 'function ', '$('))


ATTR_RE = re.compile(r'(?:placeholder|title|aria-label|alt)="([^"]*)"')


def pieces(chunk):
    """What the browser will actually show from one chunk of markup or text:
    the text between tags, and the values of the attributes we translate."""
    found = [m.group(1) for m in ATTR_RE.finditer(chunk)]
    if '<' in chunk:
        found += re.split(r'<[^>]*>', chunk)
    elif '="' not in chunk:
        found.append(chunk)
    for part in found:
        part = (part.replace('&#10;', '\n').replace('&nbsp;', ' ')
                .replace('\\n', '\n').replace('\\t', '\t')
                .replace("\\'", "'").replace('\\"', '"').strip())
        if part and HAN.search(part) and not _looks_like_code(part):
            yield part


def ui_strings():
    """Every Chinese run the browser can show, as {normalized string: {where}}."""
    found = {}
    for path in sorted(WEB.glob('*.html')) + sorted(WEB.glob('*.js')):
        if path.name in EXCLUDED_FILES:
            continue
        src = path.read_text(encoding='utf-8')
        chunks = []
        if path.suffix == '.html':
            body = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', src)
            chunks += [m.group(1) for m in re.finditer(r'>([^<>]+)<', body)]
            chunks += [m.group(1) for m in ATTR_RE.finditer(body)]
            for m in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script>', src):
                chunks += js_literals(m.group(1))
        else:
            chunks += js_literals(src)
        for chunk in chunks:
            for part in pieces(chunk):
                found.setdefault(part, set()).add(path.name)
    return found


class CoverageTests(unittest.TestCase):
    def test_the_extractor_still_finds_the_interface(self):
        """A guard on the guard: if the scan silently found nothing, the coverage
        test below would pass while translating nothing."""
        strings = ui_strings()
        self.assertGreater(len(strings), 150, 'the scan stopped finding UI text')
        self.assertIn('开始创作', strings)
        self.assertIn('全屏观看', strings)

    def test_every_interface_string_has_english(self):
        missing = {s: sorted(w) for s, w in ui_strings().items() if not covered(s)}
        self.assertEqual(missing, {}, 'untranslated UI text:\n'
                         + '\n'.join(f'  {w} {s!r}' for s, w in missing.items()))

    def test_backend_stage_names_have_english(self):
        """Stage names arrive as data and land as card text, so the same dictionary
        covers them -- but only if someone remembers to add a new stage here."""
        src = re.sub(r'#[^\n]*', '', (config.ROOT / 'app/jobs.py').read_text(encoding='utf-8'))
        stages = {m.group(1) for m in re.finditer(r"stage\(\s*p\w*\s*,\s*'([^']+)'", src)}
        stages |= {m.group(1) for m in re.finditer(r"STAGE_NAMES\s*=\s*\{([\s\S]*?)\}", src)
                   for m in QUOTED.finditer(m.group(1))}
        chinese = {s for s in stages if HAN.search(s)}
        self.assertEqual({s for s in chinese if not covered(s)}, set())


class DictionaryTests(unittest.TestCase):
    def test_the_dictionary_parsed(self):
        self.assertGreater(len(DICT), 200)
        self.assertGreater(len(RULES), 20)

    def test_no_english_value_is_still_chinese(self):
        left = {k: v for k, v in DICT.items() if HAN.search(v)}
        self.assertEqual(left, {})

    def test_no_value_is_empty(self):
        self.assertEqual([k for k, v in DICT.items() if not v.strip()], [])

    def test_rules_keep_their_placeholders(self):
        """A rule that drops a {} would silently delete the number or name it
        was carrying."""
        for zh, en in RULES:
            self.assertEqual(zh.count('{}'), en.count('{}'), f'{zh!r} -> {en!r}')
            self.assertGreater(zh.count('{}'), 0, zh)

    def test_a_placeholder_translates_a_known_value(self):
        """Placeholders mostly carry numbers and file names, but a step name that is
        already a key should not come back Chinese inside an English sentence."""
        self.assertIn('DICT[m[++i]] ?? m[i]', I18N)
        self.assertIn('生成分镜', DICT)

    def test_a_placeholder_does_not_cross_a_line_break(self):
        """'导出完成 → {}' must not swallow the per-file lines that follow it."""
        self.assertIn("zh.includes('\\n') ? '([\\\\s\\\\S]+?)' : '([^\\\\n]+?)'", I18N)

    def test_rules_are_anchored(self):
        """Unanchored, a placeholder could swallow a sentence of the paper sitting
        next to the interface text."""
        self.assertIn("'^' +", I18N)
        self.assertIn("+ '$'", I18N)


class SafetyTests(unittest.TestCase):
    def test_animation_labels_are_not_translated(self):
        """motion-diagrams.js matches the Chinese narration with regexes to pick an
        animation; a translated label would also contradict the Chinese audio."""
        for label in ('脑活动表征', '模型表征', '很高', '绿色', '原始被试'):
            self.assertNotIn(label, DICT, f'{label} belongs to the animation, not the UI')

    def test_user_authored_attributes_are_never_touched(self):
        """value holds what the user typed; data-prompt is input for the model."""
        attrs = re.search(r"const ATTRS = \[([^\]]*)\]", I18N).group(1)
        self.assertNotIn('value', attrs)
        self.assertNotIn('data-prompt', attrs)
        self.assertIn('placeholder', attrs)

    def test_skipped_elements_still_get_their_attributes(self):
        """A textarea's placeholder and a canvas's aria-label are written by this
        app, not by the paper. Rejecting the whole element left the composer's
        placeholder in Chinese."""
        self.assertIn('SKIP_SELECTOR', I18N)
        self.assertIn('querySelectorAll(SKIP_SELECTOR)', I18N)
        placeholder = re.search(r'placeholder="([^"]*)"',
                                (WEB / 'index.html').read_text(encoding='utf-8')).group(1)
        self.assertIn(placeholder.replace('&#10;', '\n'), DICT)

    def test_content_elements_are_skipped(self):
        skip = re.search(r"const SKIP = new Set\(\[([^\]]*)\]", I18N).group(1)
        for tag in ('TEXTAREA', 'PRE', 'CANVAS', 'SCRIPT'):
            self.assertIn(tag, skip)

    def test_text_node_writes_are_observed(self):
        """studio.js updates a heading via firstChild.textContent, which is a
        characterData write and never shows up as a childList change."""
        observe = re.search(r"observer\.observe\(([^)]*)\)", I18N).group(1)
        self.assertIn('childList: true', observe)
        self.assertIn('characterData: true', observe)
        self.assertNotIn('attributes', observe)

    def test_translation_is_idempotent(self):
        """Watching characterData means seeing our own writes; applyText must
        assign nothing when the value is already correct, or it loops forever."""
        self.assertIn('if (next === current) return;', I18N)


class RuleOrderTests(unittest.TestCase):
    """A placeholder matches a run of any length, so a looser template placed
    first hides a tighter one that would have matched better. Coverage cannot see
    this: both templates exist, and the wrong one simply wins."""

    def test_the_page_range_rule_precedes_the_single_page_rule(self):
        self.assertLess(I18N.index("['第{}–{}页'"), I18N.index("['第{}页'"),
                        "'第{}页' would swallow '2–11' and render 'p. 2–11'")


class WiringTests(unittest.TestCase):
    def test_every_page_loads_the_runtime_and_has_a_slot(self):
        for name in ('index.html', 'watch.html'):
            html = (WEB / name).read_text(encoding='utf-8')
            self.assertIn('i18n.js', html, name)
            self.assertIn('data-lang-slot', html, name)

    def test_the_runtime_loads_before_the_views(self):
        """studio.js and watch.js render on load; the observer must already be on."""
        for page, view in (('index.html', 'studio.js'), ('watch.html', 'watch.js')):
            html = (WEB / page).read_text(encoding='utf-8')
            self.assertLess(html.index('i18n.js'), html.index(view), page)

    def test_the_offline_bundle_ships_the_runtime(self):
        from app.pipeline import interactive
        self.assertIn('i18n.js', interactive.BUNDLE_ASSETS)
        for name in interactive.BUNDLE_ASSETS:
            self.assertTrue((WEB / name).exists(), name)


if __name__ == '__main__':
    unittest.main()
