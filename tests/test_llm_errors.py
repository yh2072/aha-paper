import unittest
from unittest.mock import patch
import httpx
from app import llm,config,pi_models,studio_settings

CONNECTION=('https://openrouter.ai/api/v1',{'Authorization':'Bearer private-test'})

class LlmErrorsTests(unittest.TestCase):
 def setUp(self):
  patcher=patch.object(llm,'connection',return_value=CONNECTION)
  patcher.start();self.addCleanup(patcher.stop)
 def response(self,status,data):return httpx.Response(status,json=data,request=httpx.Request('POST','https://openrouter.ai/api/v1/chat/completions'))
 def test_batch_rejected_without_network(self):
  with patch.object(llm.httpx,'post') as post:
   with self.assertRaisesRegex(ValueError,'异步批处理'):llm._post({'model':'vendor/model:batch'})
   post.assert_not_called()
 def test_404_shows_provider_reason_and_does_not_retry(self):
  r=self.response(404,{'error':{'message':'No endpoints found for test/model'}})
  with patch.object(llm.httpx,'post',return_value=r) as post,patch.object(llm.time,'sleep') as sleep:
   with self.assertRaisesRegex(RuntimeError,'No endpoints found'):llm._post({'model':'test/model'})
   self.assertEqual(post.call_count,1);sleep.assert_not_called()
 def test_503_retries_then_succeeds(self):
  with patch.object(llm.httpx,'post',side_effect=[self.response(503,{'error':{'message':'Unavailable'}}),self.response(200,{'choices':[]})]) as post,patch.object(llm.time,'sleep'):
   self.assertEqual(llm._post({'model':'test/model'}),{'choices':[]});self.assertEqual(post.call_count,2)
 def test_error_redacts_the_resolved_credential(self):
  with patch.dict(pi_models._resolved,{'openrouter':{'api_key':'secret-example'}},clear=True):
   message=str(llm._http_error(self.response(401,{'error':{'message':'Bad key secret-example'}}),'test/model'))
  self.assertNotIn('secret-example',message);self.assertIn('[REDACTED]',message)
 def test_invalid_settings_do_not_write(self):
  with patch.object(config,'BASE_URL','https://openrouter.ai/api/v1'),patch.object(studio_settings,'set_key') as write:
   with self.assertRaisesRegex(ValueError,'异步批处理'):studio_settings.save_settings({'model_text':'vendor/model:batch'})
   write.assert_not_called()
 def test_the_builtin_catalog_offers_no_batch_alias(self):
  ids=[m['id']for m in studio_settings.model_catalog('language','openrouter')['models']]
  self.assertTrue(ids);self.assertFalse([i for i in ids if i.endswith(':batch')])
if __name__=='__main__':unittest.main()
