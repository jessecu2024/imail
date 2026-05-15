"""Configuration & secrets loading.

Resolution order for paths and keys:
1. Environment variable (or `.env` in the project root).
2. Sensible default under `~/.config/imail/`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "imail"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class Settings:
    """All runtime configuration in one place."""

    api_key: str
    base_url: str
    model: str
    gmail_credentials_path: Path  # default path; per-account paths override
    user_signoff: str
    config_dir: Path
    server_host: str
    server_port: int


def load_settings(require_api_key: bool = True) -> Settings:
    """Read settings from env / defaults.

    Set ``require_api_key=False`` to load paths without enforcing the LLM key,
    e.g. during initial account setup.

    Supports both ``DEEPSEEK_API_KEY`` (preferred) and ``OPENAI_API_KEY``
    (fallback) so users can point at any OpenAI-compatible endpoint.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if require_api_key and not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY (or OPENAI_API_KEY) is not set. "
            "Add it to a .env file or export it in your shell."
        )

    config_dir = Path(os.environ.get("IMAIL_CONFIG_DIR", DEFAULT_CONFIG_DIR))
    config_dir.mkdir(parents=True, exist_ok=True)

    credentials_path = Path(
        os.environ.get("GMAIL_CREDENTIALS_PATH", config_dir / "credentials.json")
    )

    return Settings(
        api_key=api_key,
        base_url=os.environ.get("IMAIL_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("IMAIL_MODEL", DEFAULT_MODEL),
        gmail_credentials_path=credentials_path,
        user_signoff=os.environ.get("USER_SIGNOFF", "Jie"),
        config_dir=config_dir,
        server_host=os.environ.get("IMAIL_HOST", "127.0.0.1"),
        server_port=int(os.environ.get("IMAIL_PORT", "8765")),
    )
