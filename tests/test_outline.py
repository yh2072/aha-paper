"""Choosing how long the explainer runs, and which part of the paper it covers.

Two properties matter here and they are different in kind.

Duration is arithmetic: a requested number of minutes becomes a character budget
and a chapter band, and the default has to reproduce the hand-tuned numbers this
pipeline already shipped, or every existing project silently changes length.

Section choice is a constraint, not a request. The chosen sections decide which
pages the writer is even shown, and a chapter citing a page outside them is
rejected. Asking the model nicely in the prompt is the weak half; this is the
half that holds when it ignores the prompt.

The PDFs here are built in-process on purpose. Leaning on whatever happens to be
in data/ means the day that folder is cleared these tests quietly skip.
"""
import io
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pypdf import PdfWriter

from app.pipeline import deep_script, outline


def make_pdf(path, pages=12, bookmarks=(), text_pages=True):
    """A PDF with the given bookmarks. `bookmarks` is (title, page_number, parent_index)."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    handles = []
    for title, page, parent in bookmarks:
        parent_handle = handles[parent] if parent is not None else None
        handles.append(writer.add_outline_item(title, page, parent=parent_handle))
    buffer = io.BytesIO()
    writer.write(buffer)
    Path(path).write_bytes(buffer.getvalue())
    return path


ROADMAP = (('Introduction', 0, None),
           ('What can we do?', 2, 0),
           ('Reverse-engineer sensory systems', 4, None),
           ('Core idea', 4, 2),
           ('Details', 6, 2),
           ('Methods', 9, None),
           ('Appendix', 11, None))


class ExtractionTests(unittest.TestCase):
    def outline_of(self, directory, **kwargs):
        return outline.extract(make_pdf(Path(directory) / 'p.pdf', **kwargs))

    def test_bookmarks_become_entries_with_levels_and_pages(self):
        with TemporaryDirectory() as directory:
            items = self.outline_of(directory, bookmarks=ROADMAP)
            self.assertEqual([(i['level'], i['title'], i['page']) for i in items][:4],
                             [(0, 'Introduction', 1), (1, 'What can we do?', 3),
                              (0, 'Reverse-engineer sensory systems', 5), (1, 'Core idea', 5)])

    def test_a_section_runs_until_the_next_one_at_its_level(self):
        with TemporaryDirectory() as directory:
            items = {i['title']: i for i in self.outline_of(directory, bookmarks=ROADMAP)}
            self.assertEqual((items['Introduction']['page'], items['Introduction']['end_page']), (1, 4))
            self.assertEqual((items['Methods']['page'], items['Methods']['end_page']), (10, 11))
            # the last entry runs to the end of the paper
            self.assertEqual(items['Appendix']['end_page'], 12)

    def test_a_subsection_sits_inside_its_parent(self):
        with TemporaryDirectory() as directory:
            items = {i['title']: i for i in self.outline_of(directory, bookmarks=ROADMAP)}
            parent, child = items['Reverse-engineer sensory systems'], items['Details']
            self.assertGreaterEqual(child['page'], parent['page'])
            self.assertLessEqual(child['end_page'], parent['end_page'])

    def test_top_level_sections_tile_the_paper_without_overlapping(self):
        with TemporaryDirectory() as directory:
            tops = [i for i in self.outline_of(directory, bookmarks=ROADMAP) if i['level'] == 0]
            for earlier, later in zip(tops, tops[1:]):
                self.assertLess(earlier['end_page'], later['page'])

    def test_a_paper_with_no_bookmarks_offers_no_choice(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(self.outline_of(directory, bookmarks=()), [])

    def test_two_bookmarks_are_not_a_table_of_contents(self):
        """A cover marker and an appendix marker are not something to pick from."""
        with TemporaryDirectory() as directory:
            thin = (('Cover', 0, None), ('Appendix', 9, None))
            self.assertEqual(self.outline_of(directory, bookmarks=thin), [])

    def test_a_file_that_is_not_a_pdf_is_not_an_error(self):
        with TemporaryDirectory() as directory:
            broken = Path(directory) / 'broken.pdf'
            broken.write_bytes(b'not a pdf at all')
            self.assertEqual(outline.extract(broken), [])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.items = outline.extract(make_pdf(Path(self.directory.name) / 'p.pdf',
                                              bookmarks=ROADMAP))
        self.by_title = {i['title']: i for i in self.items}

    def test_choosing_a_section_selects_its_whole_span(self):
        ident = self.by_title['Reverse-engineer sensory systems']['id']
        self.assertEqual(outline.pages_for(self.items, [ident]), {5, 6, 7, 8, 9})

    def test_choosing_nothing_selects_nothing(self):
        self.assertEqual(outline.pages_for(self.items, []), set())
        self.assertEqual(outline.pages_for(self.items, None), set())

    def test_an_unknown_id_contributes_no_pages(self):
        self.assertEqual(outline.pages_for(self.items, ['s999']), set())

    def test_two_sections_union_their_pages(self):
        ids = [self.by_title['Methods']['id'], self.by_title['Appendix']['id']]
        self.assertEqual(outline.pages_for(self.items, ids), {10, 11, 12})

    def test_the_description_names_the_section_and_its_pages(self):
        chosen = outline.chosen(self.items, [self.by_title['Methods']['id']])
        text = outline.describe(chosen)
        self.assertIn('Methods', text)
        self.assertIn('第10–11页', text)


class BudgetTests(unittest.TestCase):
    def test_the_default_reproduces_the_shipped_numbers(self):
        """An unset duration must not change what existing projects produce."""
        plan = deep_script.budget(None)
        self.assertEqual(plan['minutes'], deep_script.DEFAULT_MINUTES)
        self.assertEqual((plan['low'], plan['high']), (2640, 4125))
        self.assertEqual((plan['chapters_low'], plan['chapters_high']), (8, 13))

    def test_length_scales_with_the_requested_duration(self):
        short, long = deep_script.budget(5), deep_script.budget(20)
        self.assertLess(short['high'], long['low'])
        self.assertLess(short['chapters_high'], long['chapters_low'])

    def test_chapters_stay_about_the_same_length_at_every_duration(self):
        """The band has to scale, or a long explainer gets a few huge chapters."""
        for minutes in (3, 5, 11, 20, 30):
            plan = deep_script.budget(minutes)
            middle = (plan['chapters_low'] + plan['chapters_high']) / 2
            self.assertTrue(220 <= plan['target'] / middle <= 440,
                            f'{minutes} 分钟每章 {plan["target"] / middle:.0f} 字')

    def test_a_silly_duration_is_clamped_not_obeyed(self):
        self.assertEqual(deep_script.budget(0)['minutes'], deep_script.MIN_MINUTES)
        self.assertEqual(deep_script.budget(600)['minutes'], deep_script.MAX_MINUTES)

    def test_the_band_always_contains_its_target(self):
        for minutes in range(deep_script.MIN_MINUTES, deep_script.MAX_MINUTES + 1):
            plan = deep_script.budget(minutes)
            self.assertLessEqual(plan['low'], plan['target'])
            self.assertLessEqual(plan['target'], plan['high'])


def chapter(text='一' * 400, pages=(1,)):
    return {'segment_title': '章', 'text': text, 'visual_concept': '画面',
            'figure': None, 'source_pages': list(pages)}


class EnforcementTests(unittest.TestCase):
    """The half that holds when the model ignores the prompt."""

    def test_a_chapter_outside_the_chosen_sections_is_rejected(self):
        draft = {'title': 't', 'chapters': [chapter(pages=[5]), chapter(pages=[40])] * 4}
        with self.assertRaisesRegex(ValueError, '不在选定的章节范围内'):
            deep_script.validate_outline(draft, [], 60, allowed_pages={5, 6, 7})

    def test_the_same_draft_passes_when_the_pages_are_inside(self):
        draft = {'title': 't', 'chapters': [chapter(pages=[5]), chapter(pages=[6])] * 4}
        board = deep_script.validate_outline(draft, [], 60, allowed_pages={5, 6, 7})
        self.assertEqual(len(board['scenes']), 8)

    def test_no_selection_leaves_the_whole_paper_citable(self):
        draft = {'title': 't', 'chapters': [chapter(pages=[40])] * 8}
        board = deep_script.validate_outline(draft, [], 60)
        self.assertEqual(len(board['scenes']), 8)

    def test_a_draft_sized_for_eleven_minutes_is_refused_for_five(self):
        draft = {'title': 't', 'chapters': [chapter()] * 8}
        deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(11))
        with self.assertRaises(ValueError):
            deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(5))

    def test_a_draft_that_is_only_too_long_is_accepted_and_reported(self):
        """Over the ceiling the explainer just runs longer than was asked for.
        That is a preference, and rewriting the whole article to satisfy it costs
        a full model call -- so it is accepted, flagged, and its real length
        reported rather than refused."""
        draft = {'title': 't', 'chapters': [chapter(text='一' * 500)] * 5}
        board = deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(5))
        self.assertEqual(board['total_chars'], 2500)
        self.assertTrue(board['over_budget'])
        self.assertAlmostEqual(board['minutes_estimate'], 8.3, places=1)

    def test_a_runaway_draft_is_still_refused(self):
        """Twice the target is not an overshoot, it is a lost brief."""
        draft = {'title': 't', 'chapters': [chapter(text='一' * 800)] * 5}
        with self.assertRaisesRegex(ValueError, '失控'):
            deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(5))

    def test_a_summary_is_still_refused_outright(self):
        """The floor is the rule this pipeline exists for: a few sentences must
        never pass as a deep explainer, however much faster that would be."""
        draft = {'title': 't', 'chapters': [chapter(text='一' * 40)] * 5}
        with self.assertRaisesRegex(ValueError, '至少'):
            deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(5))

    def test_a_draft_inside_the_band_is_not_flagged(self):
        draft = {'title': 't', 'chapters': [chapter(text='一' * 300)] * 5}
        board = deep_script.validate_outline(draft, [], 60, plan=deep_script.budget(5))
        self.assertFalse(board['over_budget'])


class WriterInputTests(unittest.TestCase):
    """What the writer is actually shown, which is where the saving comes from."""

    def feed(self, **kwargs):
        with TemporaryDirectory() as directory:
            path = make_pdf(Path(directory) / 'p.pdf', bookmarks=ROADMAP)
            seen = {}

            def capture(messages, **_):
                seen['text'] = messages[-1]['content'][0]['text']
                raise RuntimeError('stop')

            with patch.object(deep_script.llm, 'chat_json', side_effect=capture):
                with self.assertRaises(RuntimeError):
                    deep_script.generate(Path(path), [], Path(directory),
                                         log=lambda *a: None, **kwargs)
            body = seen['text']
            return body, sorted({int(n) for n in re.findall(r'\[PDF 第(\d+)页\]', body)})

    def test_only_the_chosen_pages_reach_the_writer(self):
        items = None
        with TemporaryDirectory() as directory:
            items = outline.extract(make_pdf(Path(directory) / 'p.pdf', bookmarks=ROADMAP))
        ident = next(i['id'] for i in items if i['title'] == 'Methods')
        _, pages = self.feed(section_ids=[ident])
        self.assertEqual(pages, [10, 11])

    def test_without_a_selection_the_whole_paper_reaches_the_writer(self):
        _, pages = self.feed()
        self.assertEqual(pages, list(range(1, 13)))

    def test_the_chosen_sections_are_named_in_the_prompt(self):
        with TemporaryDirectory() as directory:
            items = outline.extract(make_pdf(Path(directory) / 'p.pdf', bookmarks=ROADMAP))
        ident = next(i['id'] for i in items if i['title'] == 'Methods')
        body, _ = self.feed(section_ids=[ident])
        self.assertIn('Methods', body)
        self.assertIn('只讲论文的下列小节', body)

    def test_the_json_template_survives_interpolation(self):
        """The prompt ends in a JSON shape full of braces. Building it with an
        f-string turns those into format fields and fails at call time, not at
        import -- so it would ship looking fine."""
        body, _ = self.feed(minutes=6)
        self.assertIn('{"title":"...","subtitle":"..."', body)
        self.assertIn('"source_pages":[1,2]', body)

    def test_the_requested_duration_reaches_the_prompt(self):
        body, _ = self.feed(minutes=6)
        self.assertIn('口播约6分钟', body)
        self.assertIn('约1800字', body)


if __name__ == '__main__':
    unittest.main()
