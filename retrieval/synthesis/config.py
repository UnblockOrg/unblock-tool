"""Environment-based configuration for Gemini answer synthesis."""

import os

from retrieval.exceptions import ConfigError


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is already in project deps
    pass


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_API_BASE_URL = os.environ.get(
    "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", 30))


def validate_synthesis_config() -> None:
    """Raise a clear error early if required synthesis config is missing."""
    if not GEMINI_API_KEY:
        raise ConfigError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    if not GEMINI_MODEL:
        raise ConfigError("GEMINI_MODEL is empty. Set it to a Gemini model.")
