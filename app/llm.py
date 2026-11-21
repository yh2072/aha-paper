"""Thin OpenRouter client: text chat, JSON chat, and image generation."""
import base64
import json
import re
import time

import httpx

from . import config, pi_models

_HEADERS = {"Content-Type": "application/json", "HTTP-Referer": "http://localhost", "X-Title": "aha-paper"}


def connection(use: str = "language") -> tuple[str, dict]:
    """The endpoint and auth headers for a use, taken from its provider connection.

    Scripts, reviews and cover art all run on whichever provider the user connected;
    none of them carries its own Base URL or key any more."""
    provider = config.use_provider(use)
    try:
        resolved = pi_models.resolve(provider)
    except pi_models.ProviderError as error:
        raise RuntimeError(f"供应商 {provider} 未连接：{error}") from error
    headers = {**_HEADERS, **(resolved.get("headers") or {})}
    if resolved.get("api_key"):
        headers["Authorization"] = "Bearer " + resolved["api_key"]
    return resolved["base_url"].rstrip("/"), headers


def validate_chat_model(model: str, base_url: str | None = None):
    from urllib.parse import urlsplit
    host = (urlsplit(base_url or config.BASE_URL).hostname or '').lower()
    if (host == 'openrouter.ai' or host.endswith('.openrouter.ai')) and model.endswith(':batch'):
        raise ValueError(f'模型 {model} 是异步批处理版本，不能用于当前 Chat Completions / Pi 工作流。请在模型与声音中改用 {model.removesuffix(":batch")}。')


def _http_error(resp, model):
    try:
        error = resp.json().get('error', {})
        message = error.get('message', '') if isinstance(error, dict) else str(error)
    except (ValueError, AttributeError):
        message = ''
    # Keep provider diagnostics useful without ever echoing a resolved credential.
    for resolved in pi_models._resolved.values():
        if resolved.get('api_key'):
            message = message.replace(resolved['api_key'], '[REDACTED]')
    hint = '请检查模型 ID、同步接口兼容性及账户的供应商路由设置。' if resp.status_code == 404 else ''
    return RuntimeError(f'模型 {model} 请求失败（HTTP {resp.status_code}）：{message[:1000] or "服务未提供错误详情"} {hint}'.strip())


def _post(payload: dict, timeout: float = 300.0, retries: int = 3, use: str = "language") -> dict:
    model = payload.get('model', '')
    base_url, headers = connection(use)
    validate_chat_model(model, base_url)
    last_err = None
    for attempt in range(retries):
        try:
            resp = httpx.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=timeout)
        except httpx.TransportError as error:
            last_err = RuntimeError(f'模型 {model} 网络请求失败：{type(error).__name__}')
        else:
            if resp.is_error:
                last_err = _http_error(resp, model)
                if resp.status_code not in (408, 429) and resp.status_code < 500:
                    raise last_err
            else:
                data = resp.json()
                if "error" in data:
                    raise _http_error(resp, model)
                return data
        if attempt + 1 < retries:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'模型 {model} 请求重试 {retries} 次仍失败：{last_err}')


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.9) -> str:
    data = _post({
        "model": model or config.MODEL_TEXT,
        "messages": messages,
        "temperature": temperature,
    })
    return data["choices"][0]["message"]["content"] or ""


def chat_json(messages: list[dict], model: str | None = None, temperature: float = 0.6):
    """Chat that must return JSON; strips code fences and retries once on parse failure."""
    for attempt in range(2):
        text = chat(messages, model=model, temperature=temperature)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
        # 截取最外层的 JSON 对象/数组，容忍模型在前后加话
        m = re.search(r"[\[{].*[\]}]", cleaned, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "上面的输出不是合法 JSON。请只输出 JSON，本身不要任何解释或 markdown 代码块。"},
        ]
    raise RuntimeError("model failed to produce valid JSON")


def generate_image(prompt: str, model: str | None = None) -> bytes:
    """Generate one image via OpenRouter multimodal chat; returns PNG/JPEG bytes."""
    data = _post({
        "model": model or config.MODEL_IMAGE,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }, timeout=300.0, use="image")
    msg = data["choices"][0]["message"]
    # OpenRouter 把生成的图放在 message.images；个别模型放在 content parts 里,两处都找
    candidates = []
    for img in msg.get("images") or []:
        url = (img.get("image_url") or {}).get("url", "")
        if url:
            candidates.append(url)
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                candidates.append(part["image_url"]["url"])
    for url in candidates:
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if url.startswith("http"):
            return httpx.get(url, timeout=120).content
    raise RuntimeError(f"image model returned no image (content={str(content)[:200]!r})")
