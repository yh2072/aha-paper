"""Who this request belongs to, when more than one person shares the server.

Single-tenant is the default and is untouched by this module: leave
``AHA_MULTI_TENANT`` unset and ``current()`` returns None, every path below
falls back to the one the app has always used, and nothing asks anybody who
they are. That is the local case, and it stays the shape it was.

Switch it on and the app stops having a wallet of its own. Each workspace brings
its own provider credential, keeps its own papers, and can see neither of the
other's. The operator supplies the machine; the model credit and the PDFs are
the visitor's.

Three decisions worth keeping:

* **The passphrase is the workspace, and there is no account table.** The id is
  ``HMAC(server secret, passphrase)``, so the same passphrase on another device
  opens the same workspace and a different one opens a different workspace.
  Nothing to register, nothing to reset, nothing to leak: the server stores no
  list of who exists. The cost is that a guessable passphrase is a guessable
  workspace, which is why MIN_PASSPHRASE is not 4 and why access.py's rate
  limiting stays in front.

* **The secret is persisted, not generated per process.** A fresh secret on
  every boot would move every workspace on every restart -- and a container
  platform restarts on every deploy. It lives in the credential directory with
  the credentials, mode 600.

* **The tenant travels in a contextvar, not a parameter.** Generation runs on a
  thread pool long after the response is sent, and the credential is resolved
  deep inside llm.py. Threading an id through deep_script, figures, art_cover
  and page_highlight would touch every signature on the way for something none
  of them has an opinion about. jobs.py sets it once when the worker starts.
"""
import hashlib
import hmac
import json
import os
import secrets
from contextvars import ContextVar
from pathlib import Path

from . import config

# A workspace is only as private as the phrase that opens it. Short enough to
# type, long enough that the rate limiter in access.py has something to protect.
MIN_PASSPHRASE = 8

_current: ContextVar[str | None] = ContextVar("aha_tenant", default=None)


def enabled() -> bool:
    return os.getenv("AHA_MULTI_TENANT", "").strip().lower() in ("1", "true", "yes", "on")


def _secret_path() -> Path:
    return config.STATE_DIR / ".runtime" / "tenant-secret"


def secret() -> bytes:
    """The key the workspace ids are derived from, created once and kept.

    Losing this file does not leak anything; it orphans every workspace, because
    the same passphrase would then derive a different id."""
    path = _secret_path()
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    path.write_bytes(value)
    path.chmod(0o600)
    return value


def identify(passphrase: str) -> str:
    """The workspace a passphrase opens. Deterministic, and one way."""
    phrase = (passphrase or "").strip()
    if len(phrase) < MIN_PASSPHRASE:
        raise ValueError(f"口令至少 {MIN_PASSPHRASE} 位")
    return hmac.new(secret(), phrase.encode(), hashlib.sha256).hexdigest()[:24]


def current() -> str | None:
    """The workspace this request or job belongs to, or None in single-tenant."""
    return _current.get() if enabled() else None


def use(tenant_id: str | None):
    """Bind the workspace for everything that runs after this, on this thread."""
    return _current.set(tenant_id)


def reset(token) -> None:
    _current.reset(token)


def data_dir() -> Path:
    """Where this workspace's papers live.

    Single-tenant keeps config.DATA_DIR exactly as it was, so an existing
    installation does not have to move anything to keep working."""
    tenant_id = current()
    if not tenant_id:
        return config.DATA_DIR
    path = config.DATA_DIR / "w" / tenant_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def credential_file() -> Path:
    """The Pi credential store for this workspace.

    Pi reads PI_CREDENTIAL_FILE from its environment, so pointing each workspace
    at its own file is the whole of the per-tenant credential story -- the
    JavaScript side never learns that tenants exist."""
    tenant_id = current()
    if not tenant_id:
        return Path(os.getenv("PI_CREDENTIAL_FILE")
                    or config.STATE_DIR / ".runtime" / "credentials.json")
    path = config.STATE_DIR / ".runtime" / "w" / tenant_id / "credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def settings() -> dict:
    """This workspace's own model and voice choices, if it made any."""
    path = settings_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(values: dict) -> dict:
    """Write them. A workspace cannot be given the operator's .env to write to."""
    path = settings_file()
    merged = {**settings(), **{k: v for k, v in values.items() if v is not None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)
    path.chmod(0o600)
    return merged


def settings_file() -> Path:
    """Per-workspace model and voice choices.

    Single-tenant writes these to .env, which is the operator's own file. A
    workspace cannot be given the operator's .env to write to, so it gets a
    small JSON file of its own instead."""
    return credential_file().with_name("settings.json")
