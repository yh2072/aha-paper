"""The explainer as a deck of 3:4 images.

The failure this file exists for is the quiet one. A card is a PNG: text that
does not fit is not an error, a warning, or a visibly broken layout -- it is
simply absent from the bottom of the picture, and the only way to notice is to
read every card of every deck. So the sizing is asserted rather than eyeballed.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app import lang
from app.pipeline import cards


class Headline(unittest.TestCase):
    """cover.py's own _split_title keeps three lines and drops the rest; on a
    32-character headline that lost half the sentence and broke a word."""

    TITLES = [
        '句子和算式，在大脑里共用多少表征？用大语言模型特征做的跨领域预测',
        '把LLM团队当作分布式系统：加人何时提速，协调者何时成为单点故障',
        '从论文走向理解',
        'Can a model trained on sentences predict arithmetic?',
    ]

    def test_no_character_is_dropped(self):
        for title in self.TITLES:
            with self.subTest(title=title[:18]):
                kept = ''.join(cards._headline(title)).replace(' ', '')
                want = re.sub(r'[，。！？、；：,.!?;:\s]+', '', title)
                self.assertEqual(kept, want)

    def test_a_phrase_is_never_cut_in_half(self):
        """A break lands where the author put punctuation, or not at all."""
        for title in self.TITLES:
            phrases = [p for p in re.split(r'[，。！？、；：,.!?;:\s]+', title) if p]
            lines = cards._headline(title)
            if max(len(p) for p in phrases) > 24:
                continue                    # no line could hold it; splitting is forced
            for phrase in phrases:
                with self.subTest(title=title[:14], phrase=phrase[:14]):
                    self.assertTrue(any(phrase in line for line in lines),
                                    f'{phrase!r} was split across lines {lines}')

    def test_it_stays_within_the_line_budget(self):
        for title in self.TITLES:
            self.assertLessEqual(len(cards._headline(title, max_lines=5)), 5)


class TextAlwaysFits(unittest.TestCase):
    CHAPTER = '这是一章深度讲解的正文。' * 34      # 408 字：比实测最长的一章还长

    def test_the_longest_chapter_still_fits_the_box(self):
        for profile in (lang.ZH, lang.EN):
            text = self.CHAPTER if profile is lang.ZH else 'A sentence of narration. ' * 30
            budget = cards.H - cards.FOOTER_H - 160 - cards.MIN_PICTURE
            lines, size, height = cards._fit(text, profile, budget)
            with self.subTest(lang=profile.code):
                self.assertLessEqual(height, budget, f'{len(lines)} 行 @{size}px 放不下')

    def test_a_short_chapter_keeps_the_large_size(self):
        lines, size, _ = cards._fit('很短的一句话。', lang.ZH, 900)
        self.assertEqual(size, cards.TEXT_SIZES[0])

    def test_the_picture_never_falls_below_the_floor(self):
        """Text wins the argument, but not all of it: a picture squeezed past
        this stops being a picture of anything."""
        budget = cards.H - cards.FOOTER_H - 160 - cards.MIN_PICTURE
        _, _, height = cards._fit(self.CHAPTER, lang.ZH, budget)
        self.assertLessEqual(height, budget)


class Deck(unittest.TestCase):
    def project(self, chapters=3, kind='page'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'pages').mkdir(parents=True)
        (root / 'figures').mkdir()
        (root / 'images').mkdir()
        Image.new('RGB', (1307, 1664), 'white').save(root / 'pages' / 'page_01.png')
        Image.new('RGB', (900, 600), 'white').save(root / 'figures' / 'fig_01.png')
        segments = []
        for i in range(chapters):
            visual = ({'kind': 'figure', 'url': f'/files/x/figures/fig_01.png'}
                      if kind == 'figure' else
                      {'kind': 'page', 'pages': {'1': '/files/x/pages/page_01.png'}})
            segments.append({
                'id': f'segment-{i+1}', 'index': i, 'title': f'第{i+1}章标题',
                'summary': '这是正文。' * 60, 'visual': visual,
                'figure_source': '原文高亮 · PDF 第1页',
                'cues': [{'text': 'x', 'highlight': {
                    'page': 1, 'rects': [[0.08, 0.3 + i * 0.05, 0.4, 0.012]],
                    'quote': 'q'}}]})
        (root / 'explainer.json').write_text(json.dumps(
            {'segments': segments, 'title': '测试讲解'}, ensure_ascii=False))
        return root

    def test_a_deck_is_a_cover_plus_one_card_a_chapter(self):
        root = self.project(chapters=4)
        made = cards.render_deck(root, {'title': '测试讲解', 'paper_title': 'P'},
                                 log=lambda _: None)
        self.assertEqual(len(made), 5)
        self.assertEqual([p.name for p in made][:2], ['card_00.png', 'card_01.png'])

    def test_every_card_is_three_by_four(self):
        root = self.project()
        for card in cards.render_deck(root, {'title': 'T'}, log=lambda _: None):
            with self.subTest(card=card.name), Image.open(card) as img:
                self.assertEqual(img.size, (1080, 1440))

    def test_cards_sort_the_way_they_read(self):
        root = self.project(chapters=12)
        made = cards.render_deck(root, {'title': 'T'}, log=lambda _: None)
        self.assertEqual([p.name for p in made], sorted(p.name for p in made))

    def test_a_rerun_leaves_no_cards_from_a_longer_deck(self):
        root = self.project(chapters=6)
        cards.render_deck(root, {'title': 'T'}, log=lambda _: None)
        manifest = json.loads((root / 'explainer.json').read_text())
        manifest['segments'] = manifest['segments'][:2]
        (root / 'explainer.json').write_text(json.dumps(manifest, ensure_ascii=False))
        made = cards.render_deck(root, {'title': 'T'}, log=lambda _: None)
        on_disk = sorted(p.name for p in (root / 'cards').glob('card_*.png'))
        self.assertEqual(on_disk, [p.name for p in made])

    def test_a_project_with_no_explainer_says_so(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(ValueError, '图文卡片'):
            cards.render_deck(Path(tmp.name), {}, log=lambda _: None)


class ThePassage(unittest.TestCase):
    """A whole page shrunk into half a card is unreadable type that is still
    unreadable. The chapter knows which lines it is about."""

    def page(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'page.png'
        Image.new('RGB', (1000, 2000), 'white').save(path)
        return path

    def test_it_crops_to_the_highlighted_band(self):
        spot = {'rects': [[0.1, 0.50, 0.4, 0.01], [0.1, 0.54, 0.4, 0.01]]}
        crop = cards._page_passage(self.page(), [spot])
        self.assertIsNotNone(crop)
        self.assertLess(crop.height, 2000 * 0.25, '裁得还不够紧')

    def test_a_single_line_still_gets_room_around_it(self):
        crop = cards._page_passage(self.page(), [{'rects': [[0.1, 0.5, 0.4, 0.01]]}])
        self.assertGreater(crop.height, 100)

    def test_the_marker_is_actually_drawn(self):
        """The rendered page is clean -- the player paints the highlight on a
        canvas above it. A card that only cropped would show the right
        paragraph with nothing pointing at it."""
        crop = cards._page_passage(self.page(), [{'rects': [[0.1, 0.5, 0.4, 0.02]]}])
        colours = {c for _, c in crop.convert('RGB').getcolors(100000) or []}
        self.assertTrue(any(r > 200 and g > 150 and b < 200 for r, g, b in colours),
                        '裁出来全是白的，马克笔没画上')

    def test_no_highlights_means_no_crop(self):
        self.assertIsNone(cards._page_passage(self.page(), []))
        self.assertIsNone(cards._page_passage(None, [{'rects': [[0, 0, 1, 1]]}]))


if __name__ == '__main__':
    unittest.main()
