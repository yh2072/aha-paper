"""Central config: loads .env and normalizes OpenRouter settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

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

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# 口播语速按 ~300字/分钟 估算；≈5分钟 => 正文 ~1500 字（讲图占大头，内容要讲透）
MAX_SCRIPT_CHARS = 1500
MODEL_HUMANIZER = os.getenv("OPENAI_MODEL_HUMANIZER", "openai/gpt-5.6-sol-pro")
SCRIPT_ITERATIONS = 3          # 初稿 + 最多 N 轮「评审→修改」
SCRIPT_PASS_SCORE = 8.5        # 评审平均分达到即提前收工

MODEL_COVER = os.getenv("OPENROUTER_MODEL_COVER", "openai/gpt-image-2")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+0%")



IMAGE_PROTOCOL = os.getenv("IMAGE_PROTOCOL", "openrouter-images")

def use_provider(use: str) -> str:
    """Which provider serves a use. A blank media provider shares the language one."""
    if use == "image":
        return IMAGE_PROVIDER or LANGUAGE_PROVIDER
    return LANGUAGE_PROVIDER
