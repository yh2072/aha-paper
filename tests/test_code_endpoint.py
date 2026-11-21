"""The animation model's configuration contract.

The app names a provider and a model; Pi's registry owns everything else. These
tests pin that boundary, because the previous design re-implemented it badly:
a protocol dropdown, a bespoke key env var, and a settings form whose fields the
API silently discarded.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import config, pi_models, studio_settings

CLI = str(config.ROOT / 'scripts' / 'pi-models.mjs')


def cli(*args, stdin=None, store=None, env=None):
    """Run the provider CLI against an isolated credential store."""
    environment = {**os.environ, 'PI_CREDENTIAL_FILE': store or '/nonexistent/none.json', **(env or {})}
    done = subprocess.run(['node', CLI, *args], input=stdin, capture_output=True,
                          text=True, cwd=config.ROOT, env=environment, timeout=60)
    return done


class CatalogTests(unittest.TestCase):
    """The protocol is a property of the model, never a question for the user."""

    def test_the_protocol_comes_from_the_catalog_entry(self):
        models = {m['id']: m for m in pi_models.catalog('anthropic')}
        self.assertEqual(models['claude-opus-5-5']['api'], 'anthropic-messages')

    def test_one_provider_serves_several_protocols_chosen_per_model(self):
        """A provider-level protocol setting cannot express this, which is why it is gone.

        OpenRouter answers Claude models on its Anthropic-shaped endpoint and the
        rest on the OpenAI-shaped one. Forcing one protocol for the provider is how
        a Claude model ends up being asked to disable reasoning in the wrong shape."""
        models = {m['id']: m for m in pi_models.catalog('openrouter')}
        self.assertEqual(models['anthropic/claude-opus-5.5']['api'], 'anthropic-messages')
        self.assertEqual(models['google/gemini-3.7-flash']['api'], 'openai-completions')

    def test_the_catalog_carries_the_real_limits_and_price(self):
        entry = next(m for m in pi_models.catalog('anthropic') if m['id'] == 'claude-opus-5-5')
        self.assertEqual(entry['context_window'], 1_000_000)
        self.assertEqual(entry['max_tokens'], 128_000)
        self.assertEqual((entry['cost']['input'], entry['cost']['output']), (4, 20))

    def test_reading_the_catalog_needs_no_credential(self):
        self.assertTrue(pi_models.catalog('anthropic'))

    def test_a_model_id_in_the_wrong_form_names_the_right_one(self):
        with self.assertRaisesRegex(ValueError, 'claude-opus-5-5'):
            studio_settings._validate_catalog_model('anthropic', 'claude-opus-5.5')

    def test_an_unknown_provider_is_an_error_not_a_fallback(self):
        with self.assertRaises(pi_models.ProviderError):
            pi_models.catalog('not-a-provider')


class AmbientCredentialTests(unittest.TestCase):
    """Claude Code's session credential is not this app's configuration."""

    def test_the_users_own_api_key_is_recognized_with_its_source_named(self):
        done = cli('check', 'anthropic', env={'ANTHROPIC_API_KEY': 'sk-ant-user'})
        status = json.loads(done.stdout)
        self.assertTrue(status['configured'])
        self.assertEqual(status['source'], 'ANTHROPIC_API_KEY')

    def test_a_session_routing_credential_is_ignored(self):
        done = cli('check', 'anthropic', env={'ANTHROPIC_AUTH_TOKEN': 'session-token',
                                              'ANTHROPIC_BASE_URL': 'https://relay.internal'})
        self.assertFalse(json.loads(done.stdout)['configured'])

    def test_a_stored_credential_wins_over_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = str(Path(directory) / 'credentials.json')
            self.assertEqual(cli('login', 'anthropic', stdin='sk-ant-stored', store=store).returncode, 0)
            status = json.loads(cli('check', 'anthropic', store=store,
                                    env={'ANTHROPIC_API_KEY': 'sk-ant-ambient'}).stdout)
            self.assertEqual(status['source'], 'stored credential')

    def test_logout_forgets_the_store_but_not_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = str(Path(directory) / 'credentials.json')
            cli('login', 'anthropic', stdin='sk-ant-stored', store=store)
            cli('logout', 'anthropic', store=store)
            self.assertFalse(Path(store).exists())
            status = json.loads(cli('check', 'anthropic', store=store,
                                    env={'ANTHROPIC_API_KEY': 'sk-ant-ambient'}).stdout)
            self.assertEqual(status['source'], 'ANTHROPIC_API_KEY')

    def test_the_credential_file_is_not_world_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'credentials.json'
            cli('login', 'anthropic', stdin='sk-ant-stored', store=str(store))
            self.assertEqual(store.stat().st_mode & 0o077, 0)


class BillableCallTests(unittest.TestCase):
    def test_an_unconnected_provider_fails_before_any_billable_call(self):
        done = cli('probe', 'anthropic', 'claude-opus-5-5')
        self.assertEqual(done.returncode, 1)
        self.assertIn('not connected', done.stderr)

    def test_a_model_outside_the_catalog_is_refused_before_the_request(self):
        done = cli('probe', 'anthropic', 'claude-opus-5.5', env={'ANTHROPIC_API_KEY': 'sk-ant-user'})
        self.assertEqual(done.returncode, 1)
        self.assertIn('not in', done.stderr)

class SettingsTests(unittest.TestCase):
    def test_the_provider_choice_is_actually_persisted(self):
        """The previous form posted fields the API model never declared, so saving did nothing."""
        from app.main import StudioSettings
        declared = set(StudioSettings.model_fields)
        self.assertIn('language_provider', declared)
        # The animation model's fields went with the animation.
        self.assertNotIn('model_code', declared)
        self.assertNotIn('code_provider', declared)

    def test_no_credential_is_ever_returned_to_the_browser(self):
        """Whatever a use is called, a stored key must never reach the browser."""
        with tempfile.TemporaryDirectory() as directory:
            store = str(Path(directory) / 'credentials.json')
            cli('login', 'anthropic', stdin='sk-ant-local-secret', store=store)
            with patch.dict(os.environ, {'PI_CREDENTIAL_FILE': store}), \
                 patch.object(config, 'LANGUAGE_PROVIDER', 'anthropic'):
                public = studio_settings.public_settings()
            row = next(u for u in public['uses'] if u['use'] == 'language')
            self.assertTrue(row['configured'])
            self.assertEqual(row['source'], 'stored credential')
            self.assertNotIn('sk-ant-local-secret', json.dumps(public, ensure_ascii=False))

    def test_an_invalid_provider_id_is_rejected_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'ROOT', Path(directory)):
            with self.assertRaises(ValueError):
                studio_settings.save_settings({'language_provider': 'Not A Provider!'})
            self.assertFalse((Path(directory) / '.env').exists())


if __name__ == '__main__':
    unittest.main()
