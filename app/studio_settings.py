"""Local settings: never return a credential to the browser."""
import os
import re
from urllib.parse import urlsplit
from pathlib import Path
import httpx
from dotenv import set_key
from . import config, pi_models, tenant
from .llm import validate_chat_model
from .pipeline import speech

VOICES = {v.id for v in speech.PROVIDERS['edge'].voices}


USES = (('language','文稿与讲解','MODEL_TEXT'),('image','封面配图','MODEL_COVER'))


def _use_status():
    """Per-use provider, model and connection state.

    Uses name a provider; the provider owns the endpoint and the credential. Two
    uses on one provider are one connection, which is the whole point of the change.
    Never raises: the page must render even when the Node bridge is unavailable."""
    rows = []
    for use, label, attr in USES:
        provider = config.use_provider(use)
        try:
            status = pi_models.check(provider)
            error = ''
        except pi_models.ProviderError as problem:
            status, error = {}, str(problem)
        rows.append({'use':use,'label':label,'provider':provider,
                     'model':getattr(config, attr),
                     'configured':bool(status.get('configured')),
                     'source':status.get('source',''),
                     'stored':status.get('source')=='stored credential',
                     'error':error})
    return rows


def _speech():
    return speech.get(config.setting('TTS_PROVIDER'))


def public_settings():
    uses=_use_status()
    # Connected means the language use's provider has a credential in Pi -- the
    # same thing jobs.start_full_video gates on. config.API_KEY only sees the
    # env vars, so a key connected on this page used to read as "not set".
    language=next((u for u in uses if u['use']=='language'),{})
    return {'configured':bool(language.get('configured')),'model_text':config.setting('MODEL_TEXT'),
        'script_audit':config.setting('SCRIPT_AUDIT'),'ai_cover':config.setting('AI_COVER'),
        'model_cover':config.setting('MODEL_COVER'),
        'tts_provider':_speech().id,'tts_model':_speech().model_for(config.setting('TTS_MODEL')),
        'voice':config.setting(_speech().voice_setting) or '','rate':config.setting('EDGE_TTS_RATE'),
        'uses':uses,
        'language_provider':config.setting('LANGUAGE_PROVIDER'),'image_provider':config.setting('IMAGE_PROVIDER'),
        'engine':'pi-canvas','tts':_speech().id,'base_url':config.BASE_URL,'image_protocol':config.setting('IMAGE_PROTOCOL'),'delivery':'explainer'}


def save_settings(values):
    mapping={'model_text':('OPENAI_MODEL','MODEL_TEXT'),
        'model_cover':('OPENROUTER_MODEL_COVER','MODEL_COVER'),
        'image_protocol':('IMAGE_PROTOCOL','IMAGE_PROTOCOL'),'rate':('EDGE_TTS_RATE','EDGE_TTS_RATE'),
        'tts_provider':('TTS_PROVIDER','TTS_PROVIDER'),'tts_model':('TTS_MODEL','TTS_MODEL'),
        'language_provider':('LANGUAGE_PROVIDER','LANGUAGE_PROVIDER'),'image_provider':('IMAGE_PROVIDER','IMAGE_PROVIDER'),
        }
    # A switch, not a string: it has no length, no format and no provider to
    # validate against, so it is written before the loop below rather than
    # threaded through validations that mean nothing for a boolean.
    for field,attr in (('script_audit','SCRIPT_AUDIT'),('ai_cover','AI_COVER')):
        if values.get(field) is None:continue
        on='1' if values[field] in (True,'1','true','on','yes') else '0'
        if tenant.enabled():
            # One workspace's choice is not every workspace's: it goes in that
            # workspace's own file, and never into the process environment.
            tenant.save_settings({attr: on=='1'})
        else:
            set_key(str(config.ENV_FILE),'AHA_'+attr,on)
            os.environ['AHA_'+attr]=on
            setattr(config,attr,on=='1')
    # The voice belongs to whichever provider the same request leaves selected:
    # Edge keeps its own (EDGE_TTS_VOICE), every other provider shares TTS_VOICE.
    if values.get('tts_provider') is not None and values['tts_provider'] not in speech.PROVIDERS:
        raise ValueError('请选择列表中的语音供应商')
    voice_provider=speech.get(values.get('tts_provider') or config.setting('TTS_PROVIDER'))
    mapping['voice']=(voice_provider.voice_setting,voice_provider.voice_setting)
    pending=[]
    for field,(env,attr) in mapping.items():
        value=values.get(field)
        if value is None:continue
        value=value.strip()
        if (not value and field not in ('code_base_url','image_provider','tts_model')) or len(value)>256 or any(c in value for c in '\n\r\x00'):
            raise ValueError('设置值不能为空或包含换行')
        if field in ('base_url','code_base_url') and value:
            value=normalize_api_root(value)
        if field=='image_protocol' and value not in ('openrouter-images','openai-images'):
            raise ValueError('请选择明确的图片 API 协议')
        if field.endswith('_provider') and value and not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,40}',value):
            raise ValueError('供应商 ID 无效，请从列表中选择')
        if field.startswith('model_') and not re.fullmatch(r'[A-Za-z0-9_.:/~+\-]+',value):
            raise ValueError('模型 ID 格式无效')
        if field=='voice' and not voice_provider.valid_voice(value):
            raise ValueError('请选择列表中的 Edge TTS 音色' if voice_provider.id=='edge' else '音色 ID 无效，请从列表中选择')
        if field=='tts_model' and value and not speech.MODEL_ID.fullmatch(value):
            raise ValueError('语音模型 ID 格式无效')
        if field=='rate' and not re.fullmatch(r'[+-](?:[0-9]|[1-4][0-9]|50)%',value):
            raise ValueError('语速范围为 -50% 到 +50%')
        pending.append((env,attr,value))
    target_base=next((v for _,attr,v in pending if attr=='BASE_URL'),config.BASE_URL)
    for _,attr,value in pending:
        if attr=='MODEL_TEXT':
            validate_chat_model(value,target_base)
    if tenant.enabled():
        # A workspace cannot be handed the operator's .env to write to: that
        # file is the machine's, and one visitor's model choice is not another's.
        tenant.save_settings({attr: value for _, attr, value in pending})
        return public_settings()
    path=config.ENV_FILE 
    for env,attr,value in pending:
        set_key(str(path),env,value)
        os.environ[env]=value
        setattr(config,attr,value)
    if path.exists():path.chmod(0o600)
    return public_settings()


def check_connection():
    """One tiny real request through the language provider's Pi connection.

    The same connection the pipeline uses: it proves the key, the protocol, the
    model ID and the entitlement together, for a few tokens."""
    provider=config.use_provider('language')
    model=config.setting('MODEL_TEXT')
    try:
        connected=pi_models.check(provider).get('configured')
    except pi_models.ProviderError as error:
        raise ValueError(f'无法读取供应商状态：{error}') from error
    if not connected:raise ValueError(f'请先在设置中连接供应商 {provider}')
    validate_chat_model(model,pi_models.resolve(provider).get('base_url'))
    try:
        pi_models.probe(provider,model)
    except pi_models.ProviderError as error:
        raise ValueError(f'{provider} 验证失败：{error}') from error
    return {'ok':True,'message':f'语言连接已就绪：{provider} · {model}'}


def _validate_catalog_model(provider,model_id):
    """A model ID must exist in its provider's catalog, with the near-miss named."""
    try:
        known=[m['id'] for m in pi_models.catalog(provider)]
    except pi_models.ProviderError:
        return                      # Bridge unavailable: let the request itself report it.
    if model_id in known:return
    flat=model_id.replace('.','').replace('-','')
    near=[i for i in known if i.replace('.','').replace('-','')==flat]
    raise ValueError(f'{provider} 的模型目录里没有 {model_id}'+(f'，你是指 {near[0]} 吗？' if near else ''))


def normalize_api_root(value):
    parts=urlsplit(value)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Base URL 需为不含凭据、查询或片段的 HTTP(S) API 根地址')
    value=value.rstrip('/')
    for suffix in ('/chat/completions','/images/generations','/images','/models'):
        if value.endswith(suffix):return value[:-len(suffix)]
    return value


def model_catalog(usage='language',provider=None):
    """Models for a use, from Pi's catalog for whichever provider serves it."""
    if usage not in ('language','image'):raise ValueError('未知模型用途')
    target=provider or config.use_provider(usage)
    models=pi_models.model_options(target,'image' if usage=='image' else 'chat')
    # Async batch aliases share the catalog but cannot serve a synchronous request;
    # offering one only produces a rejection at save time.
    models=[m for m in models if not m['id'].endswith(':batch')]
    return {'models':models,'provider':target,
            'message':'来自 Pi 内置目录，含协议、上下文窗口与价格；列出不代表 Key 有该模型权限。'}


def _read_catalog(base,key,path,image):
    headers={'Authorization':'Bearer '+key,'HTTP-Referer':'http://localhost:8321','X-Title':'aha-paper'} if key else {}
    response=httpx.get(base+path,headers=headers,timeout=20)
    if response.status_code==404:
        return {'models':[],'message':'此端点不提供模型目录；可手动填写服务支持的准确模型 ID。'}
    if response.status_code!=200:raise ValueError(f'读取模型失败（HTTP {response.status_code}），请检查端点和凭据')
    data=response.json().get('data')
    if not isinstance(data,list):raise ValueError('服务未返回兼容的模型目录；请手动填写模型 ID')
    if not image and (urlsplit(base).hostname or '').lower()=='openrouter.ai':
        data=[m for m in data if not isinstance(m,dict) or not str(m.get('id','')).endswith(':batch')]
    return {'models':[{'id':m['id'],'name':m.get('name',m['id'])}for m in data if isinstance(m,dict) and isinstance(m.get('id'),str)],
            'message':'只读取目录，不生成内容；模型是否有权限以实际请求为准。'}
