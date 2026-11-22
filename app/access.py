"""One shared password in front of the whole app.

Not a login system: no accounts, no roles, one secret the operator sets. It is
here for a single reason — every button in the studio spends the operator's own
model credits and writes to their disk, so a public URL without a gate is an
open wallet. The only middleware before this was ``local_origin_guard``, which
checks *where* a request came from (CSRF). It never asked *who* sent it, and on
127.0.0.1 it did not have to.

Leave ``AHA_ACCESS_PASSWORD`` unset and nothing changes: no gate, no cookie, no
login page. That is the local case, and it stays the default.

Three decisions worth keeping:

* **The cookie is signed with a key derived from the password itself**, not from
  a random per-process secret. A random secret logs everyone out on every
  restart — and a container platform restarts on every deploy, so the gate would
  feel broken. Deriving the key from the password means sessions survive
  restarts, and *changing the password revokes every outstanding cookie*.
  Nothing is given away: someone who could forge a cookie already knows the
  password, so they could just log in.

* **The global failure counter is what makes the per-IP one worth anything.**
  ``x-forwarded-for`` is written by the client; a guesser rotates it and a
  per-IP counter never fires. The cost is that a flood can lock the operator out
  for the window. That is the right way round for a tool with one user.

* **/api/ping is open**, so an orchestrator's health check can reach it. Gating
  the health check is how you get a container that is restarted forever while
  serving perfectly well.
"""
import hashlib
import hmac
import html
import time
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import config

COOKIE = "aha_access"
TTL = 30 * 24 * 3600                      # a month: one operator, their own tool

# Reachable without the password. /api/ping is the liveness probe; the rest is
# the gate itself, which cannot ask for the password behind the password.
OPEN = ("/api/ping", "/login", "/api/login")

# A request for data gets 401 so the caller can react. Everything else gets sent
# to the login page — but never a .js or an .mp4 request: an HTML login page
# served under those names is parsed as script or as media and fails obscurely.
DATA_PREFIXES = ("/api/", "/files/", "/assets/")

WINDOW = 900                              # 15 minutes
PER_IP = 5
GLOBAL = 30
_MAX_BUCKETS = 2048
_fails: dict[str, list[float]] = {}


def enabled() -> bool:
    return bool(config.ACCESS_PASSWORD)


def _key() -> bytes:
    return hashlib.blake2b(config.ACCESS_PASSWORD.encode(),
                           person=b"aha-paper", digest_size=32).digest()


def _sign(expiry: str) -> str:
    return hmac.new(_key(), expiry.encode(), hashlib.sha256).hexdigest()


def mint() -> str:
    expiry = str(int(time.time()) + TTL)
    return f"{expiry}.{_sign(expiry)}"


def valid(token: str) -> bool:
    expiry, _, mac = (token or "").partition(".")
    if not mac or not expiry.isdigit():
        return False
    return hmac.compare_digest(mac, _sign(expiry)) and int(expiry) > time.time()


# ---------- brute-force throttle ----------

def _client(request: Request) -> str:
    hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return hop or (request.client.host if request.client else "?")


def _recent(bucket: str, now: float) -> int:
    hits = [t for t in _fails.get(bucket, ()) if now - t < WINDOW]
    if hits:
        _fails[bucket] = hits
    else:
        _fails.pop(bucket, None)
    return len(hits)


def locked(request: Request) -> bool:
    now = time.time()
    return _recent(_client(request), now) >= PER_IP or _recent("*", now) >= GLOBAL


def note_failure(request: Request) -> None:
    now = time.time()
    if len(_fails) > _MAX_BUCKETS:
        for bucket in list(_fails):
            _recent(bucket, now)
    if len(_fails) > _MAX_BUCKETS:
        # Spoofed headers must not grow memory — but the global counter has to
        # survive the purge, or overflowing the table *is* the reset button.
        keep = _fails.get("*", [])
        _fails.clear()
        _fails["*"] = keep
    for bucket in (_client(request), "*"):
        _fails.setdefault(bucket, []).append(now)


def forget(request: Request) -> None:
    """A correct password clears that client's failures."""
    _fails.pop(_client(request), None)


# ---------- the gate ----------

def check(request: Request):
    """None when the request may proceed, otherwise the response to send."""
    if not enabled():
        return None
    path = request.url.path
    if path in OPEN or valid(request.cookies.get(COOKIE, "")):
        return None
    if path.startswith(DATA_PREFIXES):
        return JSONResponse({"detail": "需要访问口令 · access password required"},
                            status_code=401, headers={"Cache-Control": "no-store"})
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303,
                            headers={"Cache-Control": "no-store"})


def _https(request: Request) -> bool:
    """Whether the *browser's* hop is TLS. Behind a proxy the app itself speaks
    plain HTTP, so the scheme on the request says nothing. Getting this wrong in
    the other direction is worse: a Secure cookie on an http://localhost login is
    dropped silently and the page just bounces back to itself."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return (forwarded or request.url.scheme) == "https"


def grant(response, request: Request) -> None:
    response.set_cookie(COOKIE, mint(), max_age=TTL, httponly=True,
                        samesite="lax", secure=_https(request), path="/")


def revoke(response) -> None:
    response.delete_cookie(COOKIE, path="/")


def safe_next(raw: str) -> str:
    """Only same-site paths. `//evil.com` is a protocol-relative URL, so the
    leading-slash test alone is an open redirect."""
    raw = raw or "/"
    bad = raw.startswith("//") or raw.startswith("/\\") or not raw.startswith("/")
    return "/" if bad or any(c in raw for c in "\r\n") else raw


# ---------- the login page ----------

def page(request: Request, nxt: str = "/", error: str = "", status: int = 200) -> HTMLResponse:
    body = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aha-paper</title>
<style>
  :root {{ --paper:#fff; --ink:#18181b; --muted:#71717a; --line:#e4e4e7;
           --accent:#1f6f4f; --bad:#b91c1c; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --paper:#111113; --ink:#f4f4f5; --muted:#a1a1aa; --line:#2a2a2e;
             --accent:#4ca37c; --bad:#f87171; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:24px;
          background:var(--paper); color:var(--ink);
          font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Helvetica Neue",sans-serif; }}
  form {{ width:100%; max-width:320px; }}
  .mark {{ width:26px; height:26px; border-radius:7px; background:var(--accent);
           color:#fff; display:grid; place-items:center; font-size:17px; margin-bottom:18px; }}
  h1 {{ font-size:17px; font-weight:650; letter-spacing:-.2px; margin:0 0 4px; }}
  p {{ color:var(--muted); font-size:13px; margin:0 0 20px; }}
  label {{ display:block; font-size:12px; color:var(--muted); margin-bottom:6px; }}
  input {{ width:100%; padding:9px 11px; font-size:14px; color:var(--ink);
           background:transparent; border:1px solid var(--line); border-radius:7px; }}
  input:focus {{ outline:none; border-color:var(--accent); }}
  button {{ width:100%; margin-top:14px; padding:9px; font-size:14px; font-weight:550;
            color:#fff; background:var(--accent); border:0; border-radius:7px; cursor:pointer; }}
  .bad {{ color:var(--bad); font-size:13px; margin:12px 0 0; }}
</style></head>
<body>
<form method="post" action="/api/login">
  <div class="mark">✦</div>
  <h1>aha-paper</h1>
  <p>带你读一遍论文 · a guided read of the paper</p>
  <input type="hidden" name="next" value="{html.escape(nxt, quote=True)}">
  <label for="pw">访问口令 · access password</label>
  <input id="pw" name="password" type="password" autocomplete="current-password" autofocus>
  <button type="submit">进入 · Enter</button>
  {f'<p class="bad">{html.escape(error)}</p>' if error else ''}
</form>
</body></html>"""
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})
