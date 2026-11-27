"""Chat goes over Chat Completions only where the model speaks it.

Pi resolves Anthropic to https://api.anthropic.com, its native Messages root;
appending /chat/completions to that is a 404 with no body. Those models go
through Pi's own client instead.
"""
import unittest
from unittest.mock import patch

from app import llm, pi_models


class RoutingTests(unittest.TestCase):
    def via(self, api):
        with patch.object(pi_models, 'model_api', return_value=api):
            return llm._via_pi('p', 'm')

    def test_only_non_chat_completions_protocols_go_through_pi(self):
        self.assertTrue(self.via('anthropic-messages'))
        self.assertTrue(self.via('google-generative-ai'))
        self.assertFalse(self.via('openai-completions'))

    def test_an_id_outside_the_catalog_keeps_the_http_path(self):
        self.assertFalse(self.via(None))

    def test_chat_uses_pi_for_an_anthropic_model_and_never_posts(self):
        with patch.object(llm, '_via_pi', return_value=True), \
                patch.object(pi_models, 'complete', return_value={'text': 'hi'}) as complete, \
                patch.object(llm, '_post', side_effect=AssertionError('posted')):
            self.assertEqual(llm.chat([{'role': 'user', 'content': 'x'}], model='claude-x', temperature=.3), 'hi')
        self.assertEqual(complete.call_args.args[1:], ('claude-x', [{'role': 'user', 'content': 'x'}], .3))


class PiRetryTests(unittest.TestCase):
    def run_with(self, errors):
        calls = iter(errors)

        def complete(*_a, **_k):
            error = next(calls)
            if error:
                raise pi_models.ProviderError(error)
            return {'text': 'ok'}
        with patch.object(pi_models, 'complete', side_effect=complete), patch.object(llm.time, 'sleep'):
            return llm._pi_chat('anthropic', 'm', [], .5)

    def test_a_transient_failure_is_retried(self):
        self.assertEqual(self.run_with(['529 overloaded_error', None]), 'ok')

    def test_a_permanent_failure_is_raised_at_once_with_the_model_named(self):
        with self.assertRaisesRegex(RuntimeError, '模型 m 请求失败：.*invalid x-api-key'):
            self.run_with(['401 authentication_error: invalid x-api-key', None])


if __name__ == '__main__':
    unittest.main()
