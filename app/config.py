"""Central config: loads .env and normalizes OpenRouter settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Where the code and the read-only assets are: web/, models/, scripts/. Inside a
# packaged app this is in the bundle, which is read-only — and on macOS writing
# into a signed bundle invalidates the signature, so nothing writable may live
# under it.
ROOT = Path(__file__).resolve().parent.parent

# Where the user's own things are: their papers, their .env, their credentials.
# The desktop shell sets AHA_STATE_DIR to the platform's application-data
# directory, because Electron already knows what that is on each OS and
# re-deriving it here would be the same rules written twice. Unset — running
# from a checkout — it is the checkout, exactly as before.
STATE_DIR = Path(os.getenv("AHA_STATE_DIR") or ROOT).expanduser()
ENV_FILE = STATE_DIR / ".env"
load_dotenv(ENV_FILE)

def _normalize_base_url(url: str) -> str:
    """Accept either the API root or a full /chat/completions endpoint."""
    url = (url or "https://openrouter.ai/api/v1").rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url

# Every use names a provider from Pi's registry; the connection and credential are
# the provider's, shared by all of them. One account is configured once, not per use.
LANGUAGE_PROVIDER = os.getenv("LANGUAGE_PROVIDER", "openrouter")
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "")          # blank: share the language provider
API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
BASE_URL = _normalize_base_url(os.getenv("OPENAI_BASE_URL", ""))
MODEL_TEXT = os.getenv("OPENAI_MODEL", "google/gemini-3.7-flash")
MODEL_IMAGE = os.getenv("OPENAI_MODEL_IMAGE", "google/gemini-3.1-flash-image")
MODEL_AUDIO = os.getenv("OPENAI_MODEL_AUDIO", "openai/gpt-audio-mini")

# 访问口令：留空＝不设门（本机跑就是这种）。一旦部署到公网必须设，
# 因为界面上每个按钮花的都是运营者自己的模型额度。详见 app/access.py。
ACCESS_PASSWORD = os.getenv("AHA_ACCESS_PASSWORD", "").strip()

DATA_DIR = STATE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)   # parents: the state dir may be new

# 口播语速按 ~300字/分钟 估算；≈5分钟 => 正文 ~1500 字（讲图占大头，内容要讲透）
MAX_SCRIPT_CHARS = 1500
MODEL_HUMANIZER = os.getenv("OPENAI_MODEL_HUMANIZER", "openai/gpt-5.6-sol-pro")
SCRIPT_ITERATIONS = 3          # 初稿 + 最多 N 轮「评审→修改」
SCRIPT_PASS_SCORE = 8.5        # 评审平均分达到即提前收工

# 独立核对那一轮：把整篇重写一遍，对着原文和真图核数值、图号和来源页码。
# 它是质量最高的一道关卡，也是整条流水线最慢的一步——实测 145 秒，占文稿
# 阶段的一半还多。默认关：写作人格里的准确性约束仍然在，少的是第二双眼睛。
# 想要那道关卡时在「模型与声音」里打开，或设 AHA_SCRIPT_AUDIT=1。
SCRIPT_AUDIT = os.getenv("AHA_SCRIPT_AUDIT", "0").strip().lower() in ("1", "true", "yes", "on")

MODEL_COVER = os.getenv("OPENROUTER_MODEL_COVER", "openai/gpt-image-2")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+0%")



IMAGE_PROTOCOL = os.getenv("IMAGE_PROTOCOL", "openrouter-images")

# The choices a workspace may make for itself. The module globals below are the
# operator's own, read from .env at import; a workspace overlays its own on top.
# Read them through setting(), never as attributes, or a workspace gets the
# operator's model and the operator's voice.
OVERRIDABLE = ("MODEL_TEXT", "MODEL_COVER", "EDGE_TTS_VOICE", "EDGE_TTS_RATE",
               "LANGUAGE_PROVIDER", "IMAGE_PROVIDER", "IMAGE_PROTOCOL",
               "SCRIPT_AUDIT")


def setting(name: str):
    """This workspace's value for a setting, falling back to the operator's.

    Single-tenant has no overlay and this is the module global, which is what
    makes the local install behave exactly as it did.
    """
    from . import tenant
    if tenant.enabled():
        overlay = tenant.settings()
        if name in overlay and overlay[name] not in (None, ""):
            return overlay[name]
    return globals().get(name)


def use_provider(use: str) -> str:
    """Which provider serves a use. A blank media provider shares the language one."""
    if use == "image":
        return setting("IMAGE_PROVIDER") or setting("LANGUAGE_PROVIDER")
    return setting("LANGUAGE_PROVIDER")
