"""Configuration & secrets loading.

Resolution order for paths and keys:
1. Environment variable (or ``.env`` in the current working directory).
2. ``.env`` under ``~/.config/imail/`` (the location documented in the
   user guide — same directory we use for accounts, tokens, replies).
3. Sensible default under ``~/.config/imail/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "imail"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def _load_dotenv_files() -> None:
    """Load ``.env`` from CWD, then from the config dir.

    CWD is checked first so a developer running ``imail`` from a checkout
    can override anything in the user-level config. ``load_dotenv``
    respects ``override=False`` (the default), so the second call only
    fills in keys that CWD's ``.env`` (or the surrounding shell) left
    blank.

    The user guide (``docs/user-guide-zh.md``) documents
    ``~/.config/imail/.env`` as the place to put ``DEEPSEEK_API_KEY``,
    so we honour that path explicitly instead of forcing the user to
    start ``imail`` from a specific working directory.
    """
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        load_dotenv(cwd_env)

    config_dir_env = os.environ.get("IMAIL_CONFIG_DIR")
    config_dir = Path(config_dir_env) if config_dir_env else DEFAULT_CONFIG_DIR
    config_env = config_dir / ".env"
    if config_env.is_file():
        load_dotenv(config_env)


_load_dotenv_files()


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
