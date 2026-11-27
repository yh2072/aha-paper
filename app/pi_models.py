"""Bridge to Pi's provider registry and credential store.

ahaexplain's daemon owns persistence and asks Pi for everything else: which
providers exist, whether one is configured and from where, and what models it
offers. This module is the same boundary, crossed with a subprocess because the
registry is JavaScript. Nothing here duplicates that knowledge — no protocol
table, no env-var map, no model list.

Credentials never pass through a settings response: they go in on stdin and the
store (``.runtime/credentials.json``, mode 600) is the only place they live.
"""
import json
import os
import subprocess

from . import bin as binaries, config, tenant

CLI = config.ROOT / 'scripts' / 'pi-models.mjs'
TIMEOUT = 30


class ProviderError(RuntimeError):
    """A provider/credential operation the user can act on."""


def _run(*args: str, stdin: str | None = None):
    try:
        # Not a bare 'node': a desktop build runs this with the Node that Electron
        # already carries, so there is nothing for the user to install separately.
        # The whole of the per-workspace credential story is this one variable:
        # Pi reads PI_CREDENTIAL_FILE from its environment, so pointing each
        # workspace at its own store keeps the JavaScript side unaware that
        # tenants exist at all. Single-tenant passes the path it always used.
        env = {**os.environ, 'PI_CREDENTIAL_FILE': str(tenant.credential_file())}
        done = subprocess.run([binaries.node(), str(CLI), *args], input=stdin,
                              capture_output=True, env=env,
                              text=True, timeout=TIMEOUT, cwd=config.ROOT)
    except (FileNotFoundError, RuntimeError) as error:
        raise ProviderError('找不到 node，模型配置需要 Node.js 运行时') from error
    except subprocess.TimeoutExpired as error:
        raise ProviderError('读取模型配置超时') from error
    if done.returncode != 0:
        raise ProviderError((done.stderr or '').strip()[:400] or '模型配置操作失败')
    try:
        return json.loads(done.stdout or 'null')
    except json.JSONDecodeError as error:
        raise ProviderError('模型配置返回了无法解析的结果') from error


def providers() -> list[dict]:
    """Every known provider with its connection state and credential source."""
    return _run('providers') or []


def catalog(provider: str, kind: str = 'chat') -> list[dict]:
    """The provider's model catalog. Local read: no key and no network needed."""
    return _run('models', provider, kind) or []


def check(provider: str) -> dict:
    """Connection state for one provider, safe to call for display."""
    return _run('check', provider) or {'id': provider, 'configured': False}


def probe(provider: str, model: str) -> dict:
    """End-to-end check: one tiny completion through the provider's connection."""
    return _run('probe', provider, model)


def login(provider: str, api_key: str) -> dict:
    """Store an API key for the provider through its own login flow."""
    if not api_key.strip():
        raise ProviderError('请填写 API Key')
    return _run('login', provider, stdin=api_key.strip())


def logout(provider: str) -> dict:
    """Forget the stored credential. Ambient environment keys remain visible."""
    return _run('logout', provider)


# Keyed by (workspace, provider). Keying it by provider alone was right while
# there was one credential store; with one per workspace it would hand the first
# caller's key to the second, which is the one bug this whole change exists to
# make impossible.
_resolved: dict[tuple[str | None, str], dict] = {}


def resolve(provider: str) -> dict:
    """Endpoint and credential for a provider, for the app's own HTTP calls.

    Server-side only and cached per process and workspace: this is what lets
    every use share one connection. Never put the result in an API response."""
    key = (tenant.current(), provider)
    if key not in _resolved:
        _resolved[key] = _run('resolve', provider)
    return _resolved[key]


def forget_resolved(provider: str | None = None):
    """Drop cached endpoints after a login, logout or provider change.

    Scoped to the workspace that asked: one workspace reconnecting a provider is
    no reason to make every other workspace pay for a fresh resolve."""
    me = tenant.current()
    for key in [k for k in _resolved if k[0] == me and (provider is None or k[1] == provider)]:
        _resolved.pop(key, None)


def model_options(provider: str, kind: str = 'chat') -> list[dict]:
    """Catalog entries trimmed for the model picker."""
    return [{'id': m['id'], 'name': m.get('name') or m['id'], 'api': m.get('api'),
             'reasoning': m.get('reasoning'), 'context_window': m.get('context_window'),
             'max_tokens': m.get('max_tokens'), 'cost': m.get('cost')}
            for m in catalog(provider, kind)]
