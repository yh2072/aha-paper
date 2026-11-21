"""Chapters without a figure read the paper itself.

The property worth protecting is narrow and absolute: the model picks which sentence
is being explained, and nothing else. Every coordinate comes from the PDF's text
layer, so the worst a wrong pick can do is mark a different real sentence on a real
page. It can never mark a place that is not there. These tests hold that line, and
hold the fallbacks that keep a chapter shippable when the paper cannot cover it.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import config
from app.pipeline import page_highlight

PAPER = config.DATA_DIR / 'Xiao_等_-_2026_-_Beyond_representational_alignment_with_brain_54b8' / 'paper.pdf'

# One A4-ish page. Rects are (left, bottom, right, top) in points from the bottom
# left, the way pypdfium2 reports them.
WIDTH, HEIGHT = 600.0, 800.0
LINES = {
    'The models answer deductive questions in a chat format with three premises.':
        [(60.0, 700.0, 540.0, 712.0)],
    'Analysing reasoning types separately, ceiling-normalized predictivity drops sharply here.':
        [(60.0, 660.0, 540.0, 672.0), (60.0, 646.0, 300.0, 658.0)],
    # No full stop of its own, so the sentence split glues it to the body text and
    # the located run spans the page: the geometry filter must drop it.
    # One ordinary sentence in a narrow two-column journal. pdfium reports one
    # rect per text run, so it comes back as twenty of them stacked in 4% of the
    # page -- the shape a cap on rect count mistook for a page-spanning glue-up.
    'In a narrow two column journal one ordinary sentence is reported as many separate runs.':
        [(60.0, float(600 - 2 * i), 230.0, float(610 - 2 * i)) for i in range(20)],
    'Nature Machine Intelligence Volume 8 August 2026 and then a great deal of body text follows it':
        # It has to actually span the page. The earlier version of this fixture
        # covered a fifth of it and passed only because a rect-count cap caught it,
        # which hid the fact that the geometry never matched what it claimed.
        [(60.0, 60.0, 540.0, 72.0)] + [(60.0, float(90 + 20 * i), 540.0, float(102 + 20 * i))
                                       for i in range(30)],
}


class FakeSearcher:
    def __init__(self, hit):
        self._hit = hit

    def get_next(self):
        return self._hit


class FakeTextPage:
    """Character offsets behave the way pdfium's do: one flat string, searched
    from a start index, with boxes derived from the matched range rather than from
    the query. Keyword location is a claim about ranges, so a fake that ignores
    them would pass tests the real text layer fails."""

    def __init__(self):
        self.text = ' '.join(LINES)
        self._rects = []

    def get_text_bounded(self):
        return self.text

    def search(self, query, index=0, match_case=False, match_whole_word=False):
        query = query.strip()
        at = self.text.lower().find(query.lower(), index)
        return FakeSearcher((at, len(query)) if at >= 0 else None)

    def count_rects(self, index, count):
        self._rects = self._boxes(index, count)
        return len(self._rects)

    def get_rect(self, k):
        return self._rects[k]

    def _boxes(self, index, count):
        """A whole sentence gives back its own line boxes. A run inside one gives
        back the matching slice of its first line, which is what a word is."""
        at = 0
        for sentence, rects in LINES.items():
            if at <= index < at + len(sentence):
                offset = index - at
                length = min(count, len(sentence) - offset)
                if offset == 0 and length >= len(sentence):
                    return rects
                left, bottom, right, top = rects[0]
                span = right - left
                return [(left + span * offset / len(sentence), bottom,
                         left + span * (offset + length) / len(sentence), top)]
            at += len(sentence) + 1
        return []


class FakePage:
    def get_textpage(self):
        return FakeTextPage()

    def get_width(self):
        return WIDTH

    def get_height(self):
        return HEIGHT


class FakePdf:
    def __len__(self):
        return 1

    def __getitem__(self, index):
        return FakePage()


def catalogue():
    return page_highlight.sentences_on(FakePdf(), 1)


class GeometryTests(unittest.TestCase):
    def test_the_origin_is_flipped_to_the_top_left(self):
        """pypdfium2 measures from the bottom; the player draws from the top."""
        self.assertEqual(page_highlight._norm((60.0, 700.0, 540.0, 712.0), WIDTH, HEIGHT),
                         [0.1, 0.11, 0.8, 0.015])

    def test_bounds_covers_every_line_of_a_wrapped_sentence(self):
        box = page_highlight.bounds([[0.1, 0.11, 0.8, 0.015], [0.1, 0.13, 0.4, 0.015]])
        self.assertEqual(box, [0.1, 0.11, 0.8, 0.035])

    def test_bounds_of_nothing_is_nothing(self):
        self.assertIsNone(page_highlight.bounds([]))

    def test_a_wrapped_sentence_keeps_one_box_per_line(self):
        """Two bars, the way a marker pen leaves them -- not one block over the gap."""
        found = {s['text']: s for s in catalogue()}
        wrapped = next(s for t, s in found.items() if t.startswith('Analysing'))
        self.assertEqual(len(wrapped['rects']), 2)

    def test_a_sentence_in_many_short_runs_is_kept(self):
        """The regression that sank a whole paper: every figure-less chapter fell
        through to a schematic because its sentences were thrown away here."""
        kept = [s for s in catalogue() if 'narrow two column' in s['text']]
        self.assertEqual(len(kept), 1)
        self.assertGreater(len(kept[0]['rects']), page_highlight.MAX_RECTS // 6)
        self.assertLess(page_highlight.bounds(kept[0]['rects'])[3], page_highlight.MAX_HEIGHT)

    def test_height_is_what_decides_not_the_number_of_runs(self):
        """Rect count varies with layout and means nothing across papers; the
        fraction of the page a sentence covers means the same thing everywhere."""
        for item in catalogue():
            self.assertLess(page_highlight.bounds(item['rects'])[3], page_highlight.MAX_HEIGHT)

    def test_a_running_header_is_not_offered_as_a_sentence(self):
        """It carries no full stop, so the split glues it to the body text after it
        and the located run spans the page. Framing that would blank the camera."""
        texts = [s['text'] for s in catalogue()]
        self.assertTrue(any(t.startswith('The models answer') for t in texts))
        self.assertFalse(any(t.startswith('Nature Machine Intelligence') for t in texts),
                         'a page-spanning run was offered as a sentence')


class PickTests(unittest.TestCase):
    """What the model is allowed to do with its one judgement."""

    def plan_with(self, picks, clauses=('第一句。', '第二句。')):
        with patch.object(page_highlight.pdfium, 'PdfDocument', lambda path: FakePdf()), \
             patch.object(page_highlight.llm, 'chat_json', return_value={'picks': picks}) as call:
            out = page_highlight.plan(list(clauses), Path('paper.pdf'), [1], log=lambda *a: None)
        return out, call

    def test_a_real_id_becomes_real_geometry(self):
        out, _ = self.plan_with([{'cue': 0, 'id': 'p1s1'}])
        self.assertEqual(out[0]['page'], 1)
        self.assertTrue(out[0]['rects'])
        self.assertIsNone(out[1])

    def test_a_fabricated_id_is_dropped(self):
        """The whole point. An id outside the catalogue cannot be turned into a
        position, so a hallucination costs a highlight, never places a wrong one."""
        out, _ = self.plan_with([{'cue': 0, 'id': 'p9s99'}, {'cue': 1, 'id': 'made up'}])
        self.assertEqual(out, [None, None])

    def test_a_null_pick_is_honoured(self):
        """Transition sentences have no source; forcing one would invent a citation."""
        out, _ = self.plan_with([{'cue': 0, 'id': None}, {'cue': 1, 'id': 'p1s1'}])
        self.assertIsNone(out[0])
        self.assertIsNotNone(out[1])

    def test_a_cue_index_out_of_range_is_dropped(self):
        out, _ = self.plan_with([{'cue': 7, 'id': 'p1s1'}])
        self.assertEqual(out, [None, None])

    def test_malformed_rows_do_not_break_the_chapter(self):
        out, _ = self.plan_with(['nonsense', None, {'cue': 0, 'id': 'p1s1'}])
        self.assertIsNotNone(out[0])

    def test_two_clauses_may_share_one_sentence(self):
        out, _ = self.plan_with([{'cue': 0, 'id': 'p1s1'}, {'cue': 1, 'id': 'p1s1'}])
        self.assertEqual(out[0]['quote'], out[1]['quote'])

    def test_a_page_with_no_text_layer_yields_no_highlights(self):
        """A scanned paper must degrade to a plain page, not crash the build."""
        class Empty(FakePdf):
            def __getitem__(self, index):
                page = FakePage()
                page.get_textpage = lambda: type('T', (), {
                    'get_text_bounded': lambda self: '',
                    'search': lambda self, *a, **k: FakeSearcher(None),
                    'count_rects': lambda self, *a: 0, 'get_rect': lambda self, k: None})()
                return page
        with patch.object(page_highlight.pdfium, 'PdfDocument', lambda path: Empty()), \
             patch.object(page_highlight.llm, 'chat_json') as call:
            out = page_highlight.plan(['一句。'], Path('paper.pdf'), [1], log=lambda *a: None)
        self.assertEqual(out, [None])
        call.assert_not_called()      # nothing to choose from, so nothing to pay for


class KeyTests(unittest.TestCase):
    """Key terms inside the chosen sentence. Same bargain as the sentence pick:
    the model says which words matter, the text layer says where they are, and a
    word it cannot verify is dropped rather than drawn somewhere plausible."""

    FIRST = 'The models answer deductive questions in a chat format with three premises.'

    def keys_for(self, keys, sentence=None):
        sentence = sentence or catalogue()[0]
        return page_highlight.locate_keys(FakePdf(), sentence, keys)

    def test_a_key_from_the_sentence_is_located(self):
        found = self.keys_for(['deductive questions'])
        self.assertEqual([k['text'] for k in found], ['deductive questions'])
        self.assertTrue(found[0]['rects'])

    def test_the_key_box_sits_inside_the_sentence_box(self):
        sentence = catalogue()[0]
        outer = page_highlight.bounds(sentence['rects'])
        for x, y, w, h in self.keys_for(['premises'], sentence)[0]['rects']:
            self.assertGreaterEqual(round(x, 4), outer[0])
            self.assertLessEqual(round(x + w, 4), round(outer[0] + outer[2], 4))

    def test_a_key_the_sentence_does_not_contain_is_dropped(self):
        """It is on the page, in the next sentence. Being real is not enough --
        it has to be in the sentence this clause is explaining."""
        self.assertIn('Analysing', ' '.join(LINES))
        self.assertEqual(self.keys_for(['Analysing']), [])

    def test_a_key_the_model_invented_is_dropped(self):
        self.assertEqual(self.keys_for(['caffeine']), [])

    def test_a_key_past_the_located_span_is_dropped(self):
        """A long sentence may only be located by a prefix. A key beyond that
        prefix has no verified position, so it is not searched for loose on the
        page -- that is exactly how a marker lands on the wrong paragraph."""
        sentence = catalogue()[0]
        self.assertTrue(self.keys_for(['premises'], sentence))
        clipped = dict(sentence, span=[sentence['span'][0], 20])
        self.assertEqual(self.keys_for(['premises'], clipped), [])

    def test_at_most_three_keys_survive(self):
        found = self.keys_for(['models', 'answer', 'deductive', 'chat', 'premises'])
        self.assertEqual(len(found), page_highlight.MAX_KEYS)

    def test_the_same_key_twice_is_kept_once(self):
        self.assertEqual(len(self.keys_for(['premises', 'Premises', ' premises. '])), 1)

    def test_malformed_keys_do_not_break_the_chapter(self):
        self.assertEqual(self.keys_for(None), [])
        self.assertEqual(self.keys_for('premises'), [])   # a string, not a list
        self.assertEqual([k['text'] for k in self.keys_for([None, 7, 'a', 'premises'])],
                         ['premises'])

    def test_a_sentence_with_no_span_yields_no_keys(self):
        sentence = dict(catalogue()[0])
        sentence.pop('span')
        self.assertEqual(self.keys_for(['premises'], sentence), [])

    def test_a_pick_carries_its_keys_through_the_plan(self):
        with patch.object(page_highlight.pdfium, 'PdfDocument', lambda path: FakePdf()), \
             patch.object(page_highlight.llm, 'chat_json', return_value={'picks': [
                 {'cue': 0, 'id': 'p1s1', 'keys': ['deductive questions', 'caffeine']}]}):
            out = page_highlight.plan(['第一句。', '第二句。'], Path('paper.pdf'), [1],
                                      log=lambda *a: None)
        self.assertEqual([k['text'] for k in out[0]['keys']], ['deductive questions'])

    def test_a_pick_without_keys_still_highlights_its_sentence(self):
        with patch.object(page_highlight.pdfium, 'PdfDocument', lambda path: FakePdf()), \
             patch.object(page_highlight.llm, 'chat_json',
                          return_value={'picks': [{'cue': 0, 'id': 'p1s1'}]}):
            out = page_highlight.plan(['第一句。'], Path('paper.pdf'), [1], log=lambda *a: None)
        self.assertTrue(out[0]['rects'])
        self.assertEqual(out[0]['keys'], [])

    def test_a_key_cut_mid_word_is_trimmed_not_dropped(self):
        """The catalogue shows truncated sentences, so the model can copy a
        fragment off the end of one. Underlining half a word is worse than
        underlining fewer words."""
        quote = 'We report gains of up to 13% absolute accuracy over the baseline.'
        self.assertEqual(page_highlight._whole_words('up to 13% absolute accu', quote),
                         'up to 13% absolute')
        self.assertEqual(page_highlight._whole_words('e report gains', quote), 'report gains')

    def test_a_key_with_no_whole_word_left_is_dropped(self):
        quote = 'We report gains of up to 13% absolute accuracy over the baseline.'
        self.assertEqual(page_highlight._whole_words('accu', quote), '')
        self.assertEqual(page_highlight._whole_words('caffeine', quote), '')

    def test_an_exact_phrase_survives_untouched(self):
        quote = 'We report gains of up to 13% absolute accuracy over the baseline.'
        self.assertEqual(page_highlight._whole_words('absolute accuracy', quote),
                         'absolute accuracy')

    def test_a_trimmed_key_still_locates(self):
        sentence = catalogue()[0]
        found = self.keys_for(['deductive questi'], sentence)
        self.assertEqual([k['text'] for k in found], ['deductive'])

    def test_the_catalogue_says_where_it_cut_a_sentence(self):
        """A model told the line was cut is less tempted to copy its ragged end."""
        long_one = {'id': 'p1s1', 'page': 1, 'text': 'x' * 400, 'rects': [[0, 0, 1, .01]],
                    'span': [0, 400]}
        with patch.object(page_highlight.pdfium, 'PdfDocument', lambda path: FakePdf()), \
             patch.object(page_highlight, 'sentences_on', return_value=[long_one]), \
             patch.object(page_highlight.llm, 'chat_json', return_value={'picks': []}) as call:
            page_highlight.plan(['第一句。'], Path('paper.pdf'), [1], log=lambda *a: None)
        self.assertIn('此句被截断', call.call_args[0][0][0]['content'])

    def test_the_prompt_asks_for_verbatim_keys(self):
        self.assertIn('keys', page_highlight.PROMPT)
        self.assertIn('一字不差', page_highlight.PROMPT)


class PrepareTests(unittest.TestCase):
    def scenes(self):
        return [{'text': '第一句。第二句。第三句。', 'source_pages': [1]}]

    def run_prepare(self, directory, highlights, scenes=None):
        scenes = scenes if scenes is not None else self.scenes()
        root = Path(directory)
        (root / 'paper.pdf').write_bytes(b'%PDF-1.4')
        with patch.object(page_highlight, 'plan', return_value=highlights) as planner:
            page_highlight.prepare(scenes, root, root / 'work', log=lambda *a: None)
        return scenes, planner, root

    def spot(self):
        return {'page': 1, 'rects': [[0.1, 0.1, 0.5, 0.02]], 'quote': 'x'}

    def test_a_covered_chapter_gets_a_plan(self):
        with TemporaryDirectory() as directory:
            scenes, _, _ = self.run_prepare(directory, [self.spot()] * 3)
            self.assertIn('page_plan', scenes[0])

    def test_a_chapter_the_paper_barely_covers_still_reads_the_paper(self):
        """There is nowhere else to go. One mark on a real page beats a picture
        nothing in the paper supports, so a thin chapter keeps its plan."""
        with TemporaryDirectory() as directory:
            scenes, _, _ = self.run_prepare(directory, [self.spot(), None, None])
            self.assertIn('page_plan', scenes[0])

    def test_a_chapter_with_a_figure_is_left_alone(self):
        with TemporaryDirectory() as directory:
            scenes = [{'text': '一句。', 'source_pages': [1], 'figure_path': '/x/fig.png'}]
            scenes, planner, _ = self.run_prepare(directory, [self.spot()], scenes)
            planner.assert_not_called()
            self.assertNotIn('page_plan', scenes[0])

    def test_the_plan_is_cached(self):
        """A re-run must not bill the user to decide the same thing twice."""
        with TemporaryDirectory() as directory:
            scenes, planner, root = self.run_prepare(directory, [self.spot()] * 3)
            again = self.scenes()
            with patch.object(page_highlight, 'plan') as second:
                page_highlight.prepare(again, root, root / 'work', log=lambda *a: None)
            second.assert_not_called()
            self.assertIn('page_plan', again[0])

    def test_a_failed_chapter_does_not_sink_the_build(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'paper.pdf').write_bytes(b'%PDF-1.4')
            scenes = self.scenes()
            with patch.object(page_highlight, 'plan', side_effect=RuntimeError('provider down')):
                page_highlight.prepare(scenes, root, root / 'work', log=lambda *a: None)
            self.assertNotIn('page_plan', scenes[0])

    def test_a_project_without_a_pdf_is_skipped(self):
        with TemporaryDirectory() as directory:
            scenes = self.scenes()
            page_highlight.prepare(scenes, Path(directory), Path(directory) / 'work',
                                   log=lambda *a: None)
            self.assertNotIn('page_plan', scenes[0])


class RemovalTests(unittest.TestCase):
    def test_there_is_no_second_renderer(self):
        """Canvas animations and the narrated schematic are both gone. Every
        picture is now the paper's own figure or the paper's own page, so there is
        nothing left that draws something the paper does not contain."""
        for name in ('code_video.py', 'scene_review.py', 'cue_visuals.py'):
            self.assertFalse((config.ROOT / 'app' / 'pipeline' / name).exists(), name)
        self.assertFalse((config.ROOT / 'web' / 'motion-diagrams.js').exists())
        self.assertFalse(hasattr(config, 'CODE_ANIMATION'))


@unittest.skipUnless(PAPER.exists(), 'needs the sample paper')
class RealPaperTests(unittest.TestCase):
    """The text layer is the thing being trusted, so prove it on a real paper."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = page_highlight.pdfium.PdfDocument(PAPER)
        cls.sentences = page_highlight.sentences_on(cls.pdf, 6)

    def test_sentences_are_found_and_located(self):
        self.assertGreater(len(self.sentences), 20)
        for item in self.sentences:
            self.assertTrue(item['rects'])

    def test_no_located_sentence_spans_the_page(self):
        tallest = max(page_highlight.bounds(s['rects'])[3] for s in self.sentences)
        self.assertLess(tallest, page_highlight.MAX_HEIGHT)

    def test_every_box_sits_inside_the_page(self):
        for item in self.sentences:
            for x, y, w, h in item['rects']:
                self.assertTrue(0 <= x <= 1 and 0 <= y <= 1, item['id'])
                self.assertTrue(0 < w <= 1 and 0 < h <= 1, item['id'])

    def test_a_real_key_lands_inside_the_real_sentence(self):
        sentence = next(s for s in self.sentences if 'reasoning' in s['text'].lower())
        found = page_highlight.locate_keys(self.pdf, sentence, ['reasoning'])
        self.assertTrue(found, sentence['text'][:80])
        outer = page_highlight.bounds(sentence['rects'])
        for x, y, w, h in found[0]['rects']:
            self.assertGreaterEqual(x, outer[0] - 1e-3)
            self.assertLessEqual(x + w, outer[0] + outer[2] + 1e-3)
            self.assertGreaterEqual(y, outer[1] - 1e-3)
            self.assertLessEqual(y + h, outer[1] + outer[3] + 1e-3)

    def test_an_invented_key_finds_no_position_on_a_real_page(self):
        """The negative control for keys, on the real text layer."""
        for sentence in self.sentences[:12]:
            self.assertEqual(page_highlight.locate_keys(self.pdf, sentence, ['caffeine']), [])

    def test_a_sentence_the_paper_does_not_contain_cannot_be_located(self):
        """The negative control behind the whole design."""
        textpage = self.pdf[5].get_textpage()
        page = self.pdf[5]
        made_up = 'The authors report that caffeine substantially improved reasoning accuracy'
        self.assertEqual(
            page_highlight._locate(textpage, made_up, page.get_width(), page.get_height()), [])


if __name__ == '__main__':
    unittest.main()
