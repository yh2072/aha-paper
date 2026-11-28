"""The narration's language: the budget, the voice, the cuts, the prompts.

The tests that matter most here are the lossless ones. A sentence split that
drops a space produces narration that still plays and still sounds right, while
every word timestamp behind it has moved -- so the cursor points at the wrong
line and nothing in the product says so. That failure cannot be caught by
listening to it, which is why it is pinned by assertion instead.
"""
import unittest
from pathlib import Path

from app import lang
from app.pipeline import cue_alignment, deep_script, tts

EN_SAMPLES = [
    'The team ran 12 trials. Fig. 3 shows the result clearly. J. Dean proposed it.',
    'Consider panel A. It plots loss against steps, whereas panel b adds the correction.',
    'Accuracy was 0.85 vs. 0.5 at baseline; the gap held. "Why?" they asked.',
    'Smith et al. report 13% absolute gains, i.e. a real effect, in Sec. 4.',
    'One sentence with no terminal punctuation at all',
]
ZH_SAMPLES = [
    '模型先编码，再看子图b的坐标轴。准确率提升了13个百分点；这很关键。',
    '没有标点的一句话',
]


class LosslessCuts(unittest.TestCase):
    """Every cut this module makes is a partition of the input, not a parse of it."""

    def test_narration_split_loses_no_character(self):
        for profile, samples in ((lang.EN, EN_SAMPLES), (lang.ZH, ZH_SAMPLES)):
            for text in samples:
                with self.subTest(lang=profile.code, text=text):
                    self.assertEqual(''.join(profile.split_narration(text)), text)

    def test_cue_split_loses_no_character(self):
        for profile, samples in ((lang.EN, EN_SAMPLES), (lang.ZH, ZH_SAMPLES)):
            for text in samples:
                with self.subTest(lang=profile.code, text=text):
                    self.assertEqual(''.join(profile.split_cues(text)), text)

    def test_cue_boundaries_are_a_refinement_of_sentence_boundaries(self):
        """A cue may start inside a sentence; it may never straddle one.

        The two cuts are consumed by different code paths over the same audio,
        so a cue that spanned a sentence end would place the cursor in one
        chapter position while the audio timing came from another."""
        for text in EN_SAMPLES:
            sentences = lang.EN.split_narration(text)
            cues = lang.EN.split_cues(text)
            ends, offset = set(), 0
            for sentence in sentences:
                offset += len(sentence)
                ends.add(offset)
            starts, offset = set(), 0
            for cue in cues:
                offset += len(cue)
                starts.add(offset)
            with self.subTest(text=text):
                self.assertTrue(ends <= starts, f'{sorted(ends)} not within {sorted(starts)}')


class EnglishSentenceEnds(unittest.TestCase):
    def test_abbreviation_does_not_end_a_sentence(self):
        for text in ('Fig. 3 shows it.', 'Smith et al. report it.', 'See Sec. 4 for detail.'):
            with self.subTest(text=text):
                self.assertEqual(len(lang.EN.split_narration(text)), 1)

    def test_initial_stays_with_its_name_but_a_panel_label_ends_the_sentence(self):
        """Identical in shape, opposite in meaning; the word in front decides."""
        self.assertEqual(len(lang.EN.split_narration('J. Dean proposed this approach.')), 1)
        self.assertEqual(len(lang.EN.split_narration(
            'Consider panel A. It plots the loss curve.')), 2)

    def test_a_decimal_point_is_not_a_sentence_end(self):
        self.assertEqual(len(lang.EN.split_narration('The score reached 0.85 after training.')), 1)

    def test_a_fragment_is_merged_rather_than_synthesised_alone(self):
        pieces = lang.EN.split_narration('It plots loss. Yes. Fig. 3 confirms it.')
        self.assertTrue(all(len(p.strip()) >= 12 for p in pieces), pieces)


class CursorMoves(unittest.TestCase):
    """The regression this layer exists for: cue_alignment.units used one
    Chinese-only regex, so an English chapter came back as a single unit and the
    cursor stood still for the whole of it."""

    def test_english_chapter_yields_more_than_one_cursor_target(self):
        text = ('The team ran 12 trials. Now look at panel b, where loss drops. '
                'On the left the baseline flattens, whereas panel c diverges.')
        self.assertGreater(len(cue_alignment.units(text, lang.EN)), 3)

    def test_default_profile_keeps_the_chinese_cue_rule(self):
        text = '模型先编码，再看子图b的坐标轴。准确率提升了13个百分点；这很关键。'
        self.assertEqual(cue_alignment.units(text), cue_alignment.units(text, lang.ZH))
        self.assertGreater(len(cue_alignment.units(text)), 3)


class VoiceAndCache(unittest.TestCase):
    def test_each_language_narrates_in_its_own_voice(self):
        self.assertTrue(tts.voice_of(lang.ZH).startswith('zh-'))
        self.assertTrue(tts.voice_of(lang.EN).startswith('en-'))

    def test_a_configured_voice_is_kept_only_for_its_own_language(self):
        self.assertEqual(lang.voice_for(lang.ZH, 'zh-CN-YunxiNeural'), 'zh-CN-YunxiNeural')
        self.assertEqual(lang.voice_for(lang.EN, 'zh-CN-YunxiNeural'), lang.EN.voice)
        self.assertEqual(lang.voice_for(lang.EN, None), lang.EN.voice)

    def test_the_audio_cache_key_distinguishes_the_languages(self):
        """Cached per-sentence durations are zipped with a freshly computed
        split. A key that matched across a change of split rule would pair every
        sentence with another sentence's duration."""
        self.assertNotEqual(tts.cache_identity(lang.ZH), tts.cache_identity(lang.EN))
        self.assertIn('|en|', tts.cache_identity(lang.EN))


class Budget(unittest.TestCase):
    def test_the_shipped_chinese_numbers_are_unchanged(self):
        self.assertEqual(deep_script.budget(), {
            'minutes': 11, 'target': 3300, 'low': 2640, 'high': 4125,
            'lang': 'zh', 'chapters_low': 8, 'chapters_high': 13})

    def test_a_minute_is_a_minute_in_either_language(self):
        """Same duration, same chapter count, three times the characters --
        because len() counts letters in English and syllables in Chinese."""
        zh, en = deep_script.budget(11, lang.ZH), deep_script.budget(11, lang.EN)
        self.assertEqual(zh['minutes'], en['minutes'])
        self.assertEqual((zh['chapters_low'], zh['chapters_high']),
                         (en['chapters_low'], en['chapters_high']))
        self.assertEqual(en['target'], zh['target'] * 3)

    def test_a_character_budget_is_restated_in_words_for_english(self):
        self.assertEqual(lang.EN.words(9900), 1650)
        self.assertEqual(lang.ZH.words(3300), 3300)   # Chinese counts characters

    def test_the_plan_carries_its_language_so_the_validator_follows_it(self):
        plan = deep_script.budget(11, lang.EN)
        board = deep_script.validate_outline(
            {'chapters': [{'text': 'word ' * 220, 'source_pages': [i + 1]}
                          for i in range(10)]}, [], 20, plan=plan)
        self.assertEqual(board['title'], lang.EN.default_title)


class QuantityWording(unittest.TestCase):
    def test_an_absolute_difference_is_not_left_as_a_percentage(self):
        self.assertEqual(lang.EN.canonical('a 13% absolute gain'),
                         'a 13 percentage point absolute gain')
        self.assertEqual(lang.EN.canonical('an absolute improvement of 4%'),
                         'an absolute improvement of 4 percentage points')
        self.assertEqual(lang.ZH.canonical('13%的绝对准确率提升'), '13个百分点的绝对准确率提升')

    def test_a_legitimate_percentage_is_left_alone(self):
        for text in ('13% of all runs failed', '准确率为13%', 'coverage hit 99.9%'):
            with self.subTest(text=text):
                self.assertEqual(lang.EN.canonical(text), text)
                self.assertEqual(lang.ZH.canonical(text), text)

    def test_the_singular_is_used_where_english_uses_it(self):
        self.assertIn('1 percentage point absolute', lang.EN.canonical('a 1% absolute gain'))
        self.assertIn('of 1 percentage point', lang.EN.canonical('an absolute gain of 1%'))


class Prompts(unittest.TestCase):
    """An English explainer must not be asked for in two languages at once.

    Mixed-language instructions are the cheapest way to lose instruction
    following, and the page marker in particular is what every chapter's
    source_pages is read back from."""

    def test_the_english_prompt_contains_no_chinese(self):
        plan = deep_script.budget(11, lang.EN)
        texts = [lang.EN.persona, lang.EN.instructions(plan, 4), lang.EN.instructions(plan, 0),
                 lang.EN.audit(plan), lang.EN.repair('x'), lang.EN.page_label(3),
                 lang.EN.figure_note('fig.png', 2), lang.EN.paper_header,
                 lang.EN.figures_header, lang.EN.section_scope(''), lang.EN.user_focus('')]
        for text in texts:
            stray = [c for c in text if '一' <= c <= '鿿']
            with self.subTest(text=text[:40]):
                self.assertFalse(stray, f'Chinese in an English prompt: {stray[:6]}')

    def test_both_languages_state_the_json_contract_and_the_length(self):
        for profile in (lang.ZH, lang.EN):
            plan = deep_script.budget(11, profile)
            text = profile.instructions(plan, 4)
            with self.subTest(lang=profile.code):
                self.assertIn('source_pages', text)
                self.assertIn('cover_prompt', text)
                self.assertIn(str(plan['low']), text)
                self.assertIn(str(plan['chapters_high']), text)

    def test_the_figure_rule_follows_how_many_figures_there_are(self):
        plan = deep_script.budget(11, lang.EN)
        self.assertIn('null in every chapter', lang.EN.instructions(plan, 0))
        self.assertNotIn('null in every chapter', lang.EN.instructions(plan, 4))


class Fallback(unittest.TestCase):
    def test_an_absent_or_unknown_code_is_chinese(self):
        """Which is what every project created before the field existed is."""
        for code in (None, '', 'zh', 'ZH', 'klingon'):
            with self.subTest(code=code):
                self.assertIs(lang.get(code), lang.ZH)

    def test_a_known_code_is_case_insensitive(self):
        self.assertIs(lang.get('EN'), lang.EN)

    def test_every_profile_is_complete(self):
        for code, profile in lang.PROFILES.items():
            with self.subTest(code=code):
                self.assertEqual(profile.code, code)
                self.assertTrue(profile.label and profile.persona and profile.default_title)
                self.assertTrue(profile.voice.startswith(code + '-'))
                plan = deep_script.budget(11, profile)
                self.assertTrue(profile.instructions(plan, 3))
                self.assertTrue(profile.audit(plan))
                self.assertEqual(profile.split_narration('x'), ['x'])


class StageGate(unittest.TestCase):
    """Changing the language has to make the script stale, or an English voice
    reads a Chinese script aloud and every stage after it reports success."""

    def gate(self, **meta):
        from app import jobs
        return jobs._script_done(None, {'script': 'x', **meta})

    def test_a_script_in_the_requested_language_is_done(self):
        self.assertTrue(self.gate(script_lang='en', lang='en'))

    def test_a_script_in_another_language_is_not_done(self):
        self.assertFalse(self.gate(script_lang='zh', lang='en'))
        self.assertFalse(self.gate(script_lang='en', lang='zh'))

    def test_a_project_from_before_the_field_existed_is_left_alone(self):
        """Absent and 'zh' are the same answer, so an old project is not
        silently rebilled for a script it already has."""
        self.assertTrue(self.gate())
        self.assertTrue(self.gate(lang='zh'))
        self.assertTrue(self.gate(script_lang='zh'))

    def test_no_script_is_never_done(self):
        from app import jobs
        self.assertFalse(jobs._script_done(None, {'lang': 'en'}))


class EnglishBuildEndToEnd(unittest.TestCase):
    """The whole point of the layer: a project marked 'en' is narrated in
    English, cut by English rules, with an English voice -- without any caller
    passing a profile by hand."""

    def build(self, code, text):
        import json
        import tempfile
        import wave
        from pathlib import Path
        from unittest.mock import patch

        from PIL import Image
        from pypdf import PdfWriter

        from app.pipeline import explainer

        asked = {}

        def synth(sentences, path, log=print, profile=None):
            asked['profile'] = profile
            asked['sentences'] = list(sentences)
            with wave.open(str(path), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\0\0' * 24000)
            # Word timestamps, as the real synthesis returns them. Their presence
            # is what routes the chapter through cue_alignment -- the path where
            # the cursor's targets are decided.
            # Edge emits one boundary per word for English and roughly one per
            # character for Chinese, which is what makes a per-clause start time
            # recoverable at all in a script with no spaces.
            words = []
            for token in ''.join(sentences).split():
                if any('\u4e00' <= c <= '\u9fff' for c in token):
                    words.extend(token)
                else:
                    words.append(token)
            step = 1.0 / max(len(words), 1)
            Path(str(path)[:-4] + '.timestamps.json').write_text(json.dumps(
                [{'text': w, 'start': i * step} for i, w in enumerate(words)]))
            return path, [1 / len(sentences)] * len(sentences)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'figures').mkdir()
            Image.new('RGB', (400, 300), 'white').save(root / 'figures/fig.png')
            writer = PdfWriter()
            for _ in range(2):
                writer.add_blank_page(width=200, height=300)
            with open(root / 'paper.pdf', 'wb') as handle:
                writer.write(handle)
            meta = {'id': root.name, 'engine': 'pi-canvas', 'lang': code,
                    'script_profile': 'deep-science-v1',
                    'figures': [{'file': 'fig.png', 'page': 2}],
                    'storyboard': {'scenes': [
                        {'text': text, 'figure': 'fig.png',
                         'figure_path': str(root / 'figures/fig.png'),
                         'source_pages': [2]}]}}
            with patch.object(explainer.tts, 'synthesize_sentences', side_effect=synth), \
                 patch.object(explainer.page_highlight, 'prepare', lambda *a, **k: None), \
                 patch.object(explainer.figures, 'map_sentences_to_regions',
                              return_value=[[.1, .2, .3, .4]]):
                manifest = explainer.build(root, meta, log=lambda _: None)
            return manifest, asked

    def test_an_english_project_narrates_in_english(self):
        text = ('The team ran twelve trials. Now look at panel b, where the loss '
                'drops sharply. On the left the baseline flattens out, whereas '
                'panel c diverges after step four hundred.')
        manifest, asked = self.build('en', text)
        self.assertIs(asked['profile'], lang.EN)
        self.assertTrue(tts.voice_of(asked['profile']).startswith('en-'))
        # Cut by English rules rather than left whole.
        self.assertGreater(len(asked['sentences']), 1)
        cues = manifest['segments'][0]['cues']
        self.assertGreater(len(cues), 3, [c['text'] for c in cues])
        self.assertEqual(''.join(c['text'] for c in cues), text)

    def test_a_project_with_no_language_is_still_chinese(self):
        text = '先看这个概念。再看这张主图的坐标轴，随后比较两条曲线。'
        manifest, asked = self.build(None, text)
        self.assertIs(asked['profile'], lang.ZH)
        self.assertTrue(tts.voice_of(asked['profile']).startswith('zh-'))
        self.assertEqual(
            ''.join(c['text'] for c in manifest['segments'][0]['cues']), text)


class EveryCallerDeclaresTheLanguage(unittest.TestCase):
    """The narration's language has to travel to every module that cuts it up.

    What this pins actually shipped. page_highlight.prepare called units(text)
    with no profile, so an English chapter was cut by the Chinese rule into 2-4
    clauses while the player drove its cursor from 7-8. The highlights are
    zipped onto the cues by position, so every highlight landed on a line of
    narration it did not belong to -- the paper marked sentences the voice was
    not explaining -- and nothing raised, logged or looked wrong in a test.

    A grep for 'cue_alignment.units(' missed it, because that call site imports
    the bare name. So this walks the syntax tree instead of the text.
    """

    LANGUAGE_DEPENDENT = {'units', 'split_sentences', 'cache_identity',
                          'synthesize_sentences', 'prepare'}

    def calls(self):
        import ast
        root = Path(__file__).resolve().parent.parent / 'app'
        for path in sorted(root.rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            defined = {n.name for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name in self.LANGUAGE_DEPENDENT and name not in defined:
                    yield path.name, node.lineno, name, node

    def test_no_call_falls_back_to_chinese_by_omission(self):
        import ast
        offenders = []
        for filename, line, name, node in self.calls():
            named = {kw.arg for kw in node.keywords}
            # Either a keyword, or the profile passed positionally after the text.
            declared = ('profile' in named or 'lang_code' in named
                        or len(node.args) >= 2
                        or (len(node.args) == 1
                            and isinstance(node.args[0], ast.Name)
                            and node.args[0].id == 'profile'))
            if not declared:
                offenders.append(f'{filename}:{line} {name}()')
        self.assertEqual(offenders, [], 'these would silently narrate in Chinese: '
                                        + ', '.join(offenders))

    def test_the_guard_itself_sees_the_calls(self):
        """A test that scans for offenders is worthless if its scan finds
        nothing at all, so the scan has to prove it reaches real call sites."""
        found = {name for _, _, name, _ in self.calls()}
        self.assertIn('units', found)
        self.assertIn('prepare', found)
        self.assertIn('split_sentences', found)


class SubtitlesFitTheLanguage(unittest.TestCase):
    """What shipped: 'which reduces the search space' rendered as 'ich reduces
    the s' over two lines, and 'is not overlapping' as 'is notoverlapping'.

    Three Chinese assumptions, stacked. A Han glyph is square, so a line held
    width/size characters -- about 17 for English, after which the caption was
    truncated with no sign it had been. A line could break after any character,
    because in Chinese it can. And a long sentence was cut into 34-character
    pieces, which in English lands mid-word and loses the space between them.
    """

    LONG = ('The sixteenth layer of the language model predicts cortical responses, '
            'which reduces the search space considerably.')

    def test_an_english_line_never_breaks_inside_a_word(self):
        for line in lang.EN.subtitle_lines(self.LONG, 900, 52):
            with self.subTest(line=line):
                self.assertEqual(line, line.strip())
                for word in line.split():
                    self.assertIn(word.strip('.,;:'), self.LONG)

    def test_an_english_chunk_never_breaks_inside_a_word(self):
        for chunk in lang.EN.subtitle_chunks(self.LONG):
            for word in chunk.split():
                with self.subTest(word=word):
                    self.assertIn(word, self.LONG)

    def test_english_gets_about_twice_the_characters_per_line(self):
        """Because a Latin glyph is about half the advance width of a Han one.
        Same box, same font size, twice the text -- which is what stops the
        caption from being cut off."""
        en = max(len(l) for l in lang.EN.subtitle_lines(self.LONG, 900, 52))
        zh = max(len(l) for l in lang.ZH.subtitle_lines('模型第十六层的特征' * 6, 900, 52))
        self.assertGreater(en, zh * 1.6)

    def test_chinese_wrapping_is_unchanged(self):
        text = '语言模型第十六层的特征能够预测皮层反应，这把搜索空间大大缩小了。'
        self.assertEqual(lang.ZH.subtitle_lines(text, 900, 52),
                         lang._wrap_cjk(text, max(int(900 / 52), 6)))

    def test_nothing_is_dropped_by_chunking(self):
        for profile, text in ((lang.EN, self.LONG),
                              (lang.ZH, '语言模型第十六层的特征能够预测皮层反应，这把搜索空间缩小了。')):
            joined = ''.join(profile.subtitle_chunks(text)).replace(' ', '')
            with self.subTest(lang=profile.code):
                self.assertEqual(joined, text.replace(' ', ''))



class PunctuationOnlyCueTests(unittest.TestCase):
    """A sentence ending inside a quotation ("……。”。") split '”。' off as a cue of
    its own. Nothing in it is spoken, so it had no timestamp and alignment
    rejected the whole chapter: 有讲解片段无法对应到实际词时间戳."""

    def test_a_trailing_quote_and_stop_stay_with_their_clause(self):
        self.assertEqual(lang.ZH.split_cues('模型回答“Is it up?”。然后停了。'),
                         ['模型回答“Is it up?”。', '然后停了。'])

    def test_no_cue_is_left_without_a_spoken_character(self):
        for text in ('他说“好。”。然后走了。', '……第一句。第二句。', 'He said "yes." Then left.'):
            for profile in (lang.ZH, lang.EN):
                with self.subTest(text=text, lang=profile.code):
                    cues = profile.split_cues(text)
                    self.assertTrue(all(any(c.isalnum() for c in cue) for cue in cues), cues)
                    self.assertEqual(''.join(cues), text.strip())

    def test_such_a_chapter_now_aligns(self):
        from app.pipeline import cue_alignment
        text = '他说“好。”。然后走了。'
        events = [{'text': w, 'start': i * .3} for i, w in enumerate(['他', '说', '好', '然后', '走', '了'])]
        cues, _ = cue_alignment.align(cue_alignment.units(text, lang.ZH), events, 3.0)
        self.assertEqual([c['text'] for c in cues], ['他说“好。”。', '然后走了。'])

if __name__ == '__main__':
    unittest.main()
