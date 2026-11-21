import unittest
from unittest.mock import patch
from app import config, pi_models, studio_settings


class ApiConnectionTests(unittest.TestCase):
    def test_api_root_normalizes_full_known_endpoints(self):
        for path in ('/chat/completions', '/images/generations', '/images', '/models'):
            self.assertEqual(studio_settings.normalize_api_root('https://relay.example/prefix/v1' + path),
                             'https://relay.example/prefix/v1')

    def test_api_root_rejects_embedded_credentials(self):
        with self.assertRaises(ValueError):
            studio_settings.normalize_api_root('https://secret:token@relay.example/v1')

    def test_every_use_reads_the_catalog_locally_without_a_request(self):
        """No key, no network, and never a model the runtime cannot resolve."""
        with patch.object(studio_settings, 'httpx') as http:
            language = studio_settings.model_catalog('language', 'openrouter')
            images = studio_settings.model_catalog('image', 'openrouter')
            http.get.assert_not_called()
        self.assertTrue(language['models'] and images['models'])
        self.assertNotEqual([m['id'] for m in language['models']], [m['id'] for m in images['models']])

    def test_image_models_come_from_the_image_catalog(self):
        images = {m['id'] for m in studio_settings.model_catalog('image', 'openrouter')['models']}
        chat = {m['id'] for m in studio_settings.model_catalog('language', 'openrouter')['models']}
        self.assertTrue(images - chat)

    def test_discovery_does_not_replace_the_selected_model(self):
        before = config.MODEL_COVER
        studio_settings.model_catalog('image', 'openrouter')
        self.assertEqual(config.MODEL_COVER, before)

    def test_a_provider_without_image_models_is_an_error_not_an_empty_picker(self):
        with self.assertRaises(pi_models.ProviderError):
            studio_settings.model_catalog('image', 'anthropic')


if __name__ == '__main__':
    unittest.main()
