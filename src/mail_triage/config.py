"""Configuration & secrets loading.

Resolution order for paths and keys:
1. Environment variable (or `.env` in the project root).
2. Sensible default under `~/.config/mail-triage/`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the directory the user is running in (or its parents).
load_dotenv()

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "mail-triage"


@dataclass(frozen=True)
class Settings:
    """All runtime configuration in one place."""

    anthropic_api_key: str
    anthropic_model: str
    gmail_credentials_path: Path
    gmail_token_path: Path
    user_signoff: str  # name to sign emails with, e.g. "Jie"


def load_settings() -> Settings:
    """Read settings from env / defaults. Raises if a required secret is missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to a .env file or export it in your shell."
        )

    config_dir = Path(os.environ.get("MAIL_TRIAGE_CONFIG_DIR", DEFAULT_CONFIG_DIR))
    config_dir.mkdir(parents=True, exist_ok=True)

    credentials_path = Path(
        os.environ.get("GMAIL_CREDENTIALS_PATH", config_dir / "credentials.json")
    )
    token_path = Path(os.environ.get("GMAIL_TOKEN_PATH", config_dir / "token.json"))

    return Settings(
        anthropic_api_key=api_key,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        gmail_credentials_path=credentials_path,
        gmail_token_path=token_path,
        user_signoff=os.environ.get("USER_SIGNOFF", "Jie"),
    )
