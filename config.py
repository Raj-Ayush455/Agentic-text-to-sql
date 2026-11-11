"""
Provider-agnostic configuration.

Reads `.env` (if present) and exposes an OpenAI-compatible client
that works with both Google Gemini and Groq.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()  # loads .env from cwd or parents

# ── Resolve provider ────────────────────────────────────────
# Priority: GEMINI_API_KEY  →  GROQ_API_KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GEMINI_API_KEY:
    LLM_PROVIDER = "gemini"
    API_KEY = GEMINI_API_KEY
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    DEFAULT_MODEL = "gemini-3.6-flash"
elif GROQ_API_KEY:
    LLM_PROVIDER = "groq"
    API_KEY = GROQ_API_KEY
    BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
else:
    LLM_PROVIDER = ""
    API_KEY = ""
    BASE_URL = ""
    DEFAULT_MODEL = ""

LLM_MODEL: str = os.getenv("LLM_MODEL", DEFAULT_MODEL)


def require_api_key() -> None:
    """Call at application startup to fail fast if no key is configured."""
    if not API_KEY:
        print(
            "ERROR: No API key found.\n"
            "       Set GEMINI_API_KEY or GROQ_API_KEY in a .env file\n"
            "       or as an environment variable.\n"
            "       See .env.example for reference.",
            file=sys.stderr,
        )
        sys.exit(1)
