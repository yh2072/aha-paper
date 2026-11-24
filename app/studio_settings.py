"""Local settings: never return a credential to the browser."""
import os
import re
from urllib.parse import urlsplit
from pathlib import Path
import httpx
from dotenv import set_key
from . import config, pi_models
from .llm import validate_chat_model

VOICES = {'zh-CN-XiaoxiaoNeural','zh-CN-YunxiNeural','zh-CN-XiaoyiNeural','zh-CN-YunjianNeural','en-US-AriaNeural'}


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


def public_settings():
    return {'configured':bool(config.API_KEY),'model_text':config.MODEL_TEXT,
        'script_audit':config.SCRIPT_AUDIT,
        'model_cover':config.MODEL_COVER,
        'voice':config.EDGE_TTS_VOICE,'rate':config.EDGE_TTS_RATE,
        'uses':_use_status(),
        'language_provider':config.LANGUAGE_PROVIDER,'image_provider':config.IMAGE_PROVIDER,
        'engine':'pi-canvas','tts':'edge-tts','base_url':config.BASE_URL,'image_protocol':config.IMAGE_PROTOCOL,'delivery':'explainer'}


def save_settings(values):
    mapping={'model_text':('OPENAI_MODEL','MODEL_TEXT'),
        'model_cover':('OPENROUTER_MODEL_COVER','MODEL_COVER'),
        'image_protocol':('IMAGE_PROTOCOL','IMAGE_PROTOCOL'),'voice':('EDGE_TTS_VOICE','EDGE_TTS_VOICE'),'rate':('EDGE_TTS_RATE','EDGE_TTS_RATE'),
        'language_provider':('LANGUAGE_PROVIDER','LANGUAGE_PROVIDER'),'image_provider':('IMAGE_PROVIDER','IMAGE_PROVIDER'),
        }
    # A switch, not a string: it has no length, no format and no provider to
    # validate against, so it is written before the loop below rather than
    # threaded through validations that mean nothing for a boolean.
    if values.get('script_audit') is not None:
        flag='1' if values['script_audit'] in (True,'1','true','on','yes') else '0'
        set_key(str(config.ENV_FILE),'AHA_SCRIPT_AUDIT',flag)
        os.environ['AHA_SCRIPT_AUDIT']=flag
        config.SCRIPT_AUDIT=(flag=='1')
    pending=[]
    for field,(env,attr) in mapping.items():
        value=values.get(field)
        if value is None:continue
        value=value.strip()
        if (not value and field not in ('code_base_url','image_provider')) or len(value)>256 or any(c in value for c in '\n\r\x00'):
            raise ValueError('设置值不能为空或包含换行')
        if field in ('base_url','code_base_url') and value:
            value=normalize_api_root(value)
        if field=='image_protocol' and value not in ('openrouter-images','openai-images'):
            raise ValueError('请选择明确的图片 API 协议')
        if field.endswith('_provider') and value and not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,40}',value):
            raise ValueError('供应商 ID 无效，请从列表中选择')
        if field.startswith('model_') and not re.fullmatch(r'[A-Za-z0-9_.:/~+\-]+',value):
            raise ValueError('模型 ID 格式无效')
        if field=='voice' and value not in VOICES:raise ValueError('请选择列表中的 Edge TTS 音色')
        if field=='rate' and not re.fullmatch(r'[+-](?:[0-9]|[1-4][0-9]|50)%',value):
            raise ValueError('语速范围为 -50% 到 +50%')
        pending.append((env,attr,value))
    target_base=next((v for _,attr,v in pending if attr=='BASE_URL'),config.BASE_URL)
    for _,attr,value in pending:
        if attr=='MODEL_TEXT':
            validate_chat_model(value,target_base)
    path=config.ENV_FILE 
    for env,attr,value in pending:
        set_key(str(path),env,value)
        os.environ[env]=value
        setattr(config,attr,value)
    if path.exists():path.chmod(0o600)
    return public_settings()


def check_connection():
    """Report each use's own connection, since they can point at different services."""
    if not config.API_KEY:raise ValueError('请先填写并保存语言 API Key')
    validate_chat_model(config.MODEL_TEXT)
    language=_probe_language()
    if language.get('ok') is None:return language
    return {'ok':True,'message':language['message']}


def _probe_language():
    host=(urlsplit(config.BASE_URL).hostname or '').lower()
    official=host=='openrouter.ai' or host.endswith('.openrouter.ai')
    endpoint='/key' if official else '/models'
    response=httpx.get(config.BASE_URL+endpoint,headers={'Authorization':'Bearer '+config.API_KEY},timeout=20)
    if response.status_code==404 and not official:return {'ok':None,'message':'该兼容端点不提供模型目录；可手动配置模型，尚未验证推理权限。'}
    if response.status_code!=200:
        raise ValueError(f'语言 API 验证失败（HTTP {response.status_code}），请检查 Key 和额度')
    return {'ok':True,'message':'语言连接已就绪，文稿与封面使用此账户额度。'}


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
