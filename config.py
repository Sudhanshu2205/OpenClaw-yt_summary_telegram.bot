import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
OPENAI_API_KEY = (
    os.getenv("OPENAI_API_KEY")
    or os.getenv("OPENROUTER_API_KEY")
)

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY (or OPENROUTER_API_KEY) in environment.")

if OPENAI_API_KEY.startswith("sk-or-v1") and not OPENAI_BASE_URL:
    OPENAI_BASE_URL = "https://openrouter.ai/api/v1"

default_headers = None
if OPENAI_BASE_URL and "openrouter.ai" in OPENAI_BASE_URL:
    referer = os.getenv("OPENROUTER_SITE_URL", "").strip()
    title = os.getenv("OPENROUTER_APP_NAME", "").strip()
    hdrs = {}
    if referer:
        hdrs["HTTP-Referer"] = referer
    if title:
        hdrs["X-Title"] = title
    default_headers = hdrs or None

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    default_headers=default_headers,
)

default_chat_model = "openai/gpt-4o-mini" if (OPENAI_BASE_URL and "openrouter.ai" in OPENAI_BASE_URL) else "gpt-4o-mini"
CHAT_MODEL = os.getenv("CHAT_MODEL", default_chat_model)
STT_MODEL = os.getenv("STT_MODEL", "whisper-1")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")

def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    return default


_provider_disables_audio_by_default = bool(OPENAI_BASE_URL and "openrouter.ai" in OPENAI_BASE_URL)
_default_audio_enabled = not _provider_disables_audio_by_default

AUDIO_ENABLED = _parse_bool_env("AUDIO_ENABLED", _default_audio_enabled)
VOICE_INPUT_ENABLED = _parse_bool_env("VOICE_INPUT_ENABLED", AUDIO_ENABLED)
VOICE_OUTPUT_ENABLED = _parse_bool_env("VOICE_OUTPUT_ENABLED", AUDIO_ENABLED)
