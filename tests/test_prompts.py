"""Focus presets: the ones that ship, and the ones the user writes.

The bug this module was written to remove is visible rather than subtle -- the
English interface offered a Chinese sentence, because the preset lived in a
`data-prompt` attribute and web/i18n.js deliberately never rewrites a
user-authored attribute. tests/test_i18n.py pins that refusal, so the fix could
not be 'translate the attribute too'. It had to be: stop storing a prompt in the
DOM at all.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, prompts


class StoreTestCase(unittest.TestCase):
    """Each test gets its own store. The real one is the user's saved prompts;
    a suite that wrote to it would quietly delete their work."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(config, 'STATE_DIR', Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def store(self) -> Path:
        return Path(self._tmp.name) / 'prompts.json'


class Presets(StoreTestCase):
    def test_every_preset_exists_in_both_languages(self):
        """The whole point. A preset missing one language is the original bug."""
        for preset in prompts.PRESETS:
            with self.subTest(preset=preset['id']):
                for field in ('label', 'prompt'):
                    self.assertTrue(preset[field]['zh'].strip())
                    self.assertTrue(preset[field]['en'].strip())

    def test_the_english_preset_carries_no_chinese(self):
        for preset in prompts.PRESETS:
            text = preset['label']['en'] + preset['prompt']['en']
            stray = [c for c in text if '一' <= c <= '鿿']
            with self.subTest(preset=preset['id']):
                self.assertFalse(stray, f'Chinese in the English preset: {stray[:5]}')

    def test_the_chinese_preset_is_actually_chinese(self):
        for preset in prompts.PRESETS:
            with self.subTest(preset=preset['id']):
                self.assertRegex(preset['prompt']['zh'], r'[一-鿿]')

    def test_preset_ids_are_unique(self):
        ids = [p['id'] for p in prompts.PRESETS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_listing_serves_one_language_flat(self):
        english = prompts.listing('en')
        self.assertEqual(english['lang'], 'en')
        for item in english['presets']:
            self.assertIsInstance(item['prompt'], str)   # flattened, not {zh, en}
            self.assertEqual(item['kind'], 'preset')
        self.assertNotEqual([p['label'] for p in english['presets']],
                            [p['label'] for p in prompts.listing('zh')['presets']])

    def test_an_unknown_language_falls_back_to_chinese(self):
        for code in (None, '', 'klingon', 'ZH'):
            with self.subTest(code=code):
                self.assertEqual(prompts.listing(code)['lang'], 'zh')

    def test_english_is_matched_by_prefix(self):
        """The interface may send en, en-US or en-GB; all of them mean English."""
        for code in ('en', 'EN', 'en-US', 'en-GB'):
            with self.subTest(code=code):
                self.assertEqual(prompts.listing(code)['lang'], 'en')


class CustomPrompts(StoreTestCase):
    def test_saving_and_listing_round_trips(self):
        saved = prompts.add('因果识别', '只讲工具变量的外生性。')
        self.assertEqual(saved['kind'], 'custom')
        listed = prompts.listing('zh')['custom']
        self.assertEqual([p['id'] for p in listed], [saved['id']])
        self.assertEqual(listed[0]['prompt'], '只讲工具变量的外生性。')

    def test_a_custom_prompt_is_never_translated(self):
        """It is the user's own sentence. Handing back a rewrite of what someone
        wrote, as though they wrote it, is worse than leaving it alone."""
        prompts.add('', 'Only discuss the identification strategy.')
        for code in ('zh', 'en'):
            with self.subTest(code=code):
                self.assertEqual(prompts.listing(code)['custom'][0]['prompt'],
                                 'Only discuss the identification strategy.')

    def test_an_unnamed_prompt_is_labelled_from_its_first_clause(self):
        """Naming a prompt is work the user did not ask for."""
        saved = prompts.add('', '只讲因果识别策略：工具变量选得好不好，排除性约束站不站得住。')
        self.assertEqual(saved['label'], '只讲因果识别策略：工具变量选得好不好')

    def test_a_long_label_is_cut_rather_than_refused(self):
        saved = prompts.add('x' * 200, 'something to explain')
        self.assertEqual(len(saved['label']), prompts.MAX_LABEL)

    def test_an_empty_prompt_is_refused(self):
        for text in ('', '   ', '\n\t '):
            with self.subTest(text=repr(text)):
                with self.assertRaises(ValueError):
                    prompts.add('name', text)

    def test_an_overlong_prompt_is_refused(self):
        with self.assertRaises(ValueError):
            prompts.add('name', 'x' * (prompts.MAX_PROMPT + 1))

    def test_the_same_prompt_is_not_saved_twice(self):
        prompts.add('a', '只讲实验设计。')
        with self.assertRaises(ValueError):
            prompts.add('b', '  只讲实验设计。  ')

    def test_the_store_is_bounded(self):
        for i in range(prompts.MAX_CUSTOM):
            prompts.add('', f'focus number {i}')
        with self.assertRaises(ValueError):
            prompts.add('', 'one too many')

    def test_updating_changes_only_that_prompt(self):
        first = prompts.add('a', 'explain the design')
        second = prompts.add('b', 'explain the figures')
        prompts.update(first['id'], 'a2', 'explain the controls')
        saved = {p['id']: p for p in prompts.listing('zh')['custom']}
        self.assertEqual(saved[first['id']]['prompt'], 'explain the controls')
        self.assertEqual(saved[second['id']]['prompt'], 'explain the figures')

    def test_removing_works_once(self):
        saved = prompts.add('a', 'explain the design')
        prompts.remove(saved['id'])
        self.assertEqual(prompts.listing('zh')['custom'], [])
        with self.assertRaises(KeyError):
            prompts.remove(saved['id'])


class BuiltInsAreNotTheUsers(StoreTestCase):
    """A preset ships with the app and exists in two languages; editing one in
    place would strand the other half."""

    def test_a_preset_cannot_be_deleted(self):
        for preset in prompts.PRESETS:
            with self.subTest(preset=preset['id']):
                with self.assertRaises(ValueError):
                    prompts.remove(preset['id'])

    def test_a_preset_cannot_be_edited(self):
        with self.assertRaises(ValueError):
            prompts.update('figures', 'mine', 'my own version')

    def test_presets_survive_the_attempt(self):
        try:
            prompts.remove('figures')
        except ValueError:
            pass
        self.assertIn('figures', [p['id'] for p in prompts.listing('zh')['presets']])


class StoreResilience(StoreTestCase):
    def test_a_missing_store_is_simply_empty(self):
        self.assertFalse(self.store.exists())
        self.assertEqual(prompts.listing('zh')['custom'], [])

    def test_a_corrupt_store_does_not_take_the_page_down(self):
        """The prompts are a convenience; losing them is recoverable, a home
        page that will not render is not."""
        self.store.write_text('{ not json at all')
        self.assertEqual(prompts.listing('zh')['custom'], [])
        self.assertTrue(prompts.listing('zh')['presets'])

    def test_malformed_entries_are_skipped_not_served(self):
        self.store.write_text(json.dumps({'version': 1, 'prompts': [
            {'id': 'ok', 'prompt': 'real one'},
            {'id': 'no-prompt'},
            {'prompt': 'no id'},
            'not even a dict',
        ]}, ensure_ascii=False))
        self.assertEqual([p['id'] for p in prompts.listing('zh')['custom']], ['ok'])

    def test_the_write_is_atomic(self):
        """tmp-then-replace, so a crash mid-write cannot truncate the real file."""
        prompts.add('a', 'explain the design')
        self.assertTrue(self.store.exists())
        self.assertFalse(self.store.with_name(self.store.name + '.tmp').exists())
        self.assertEqual(json.loads(self.store.read_text())['version'], 1)


if __name__ == '__main__':
    unittest.main()
