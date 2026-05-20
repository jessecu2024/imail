"""Tests for the dotenv loader path resolution.

`config.py` documents that `~/.config/imail/.env` is a valid place to keep
`DEEPSEEK_API_KEY` etc. These tests pin the actual loader behaviour to that
contract so we don't quietly regress to only reading `.env` from CWD.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the env vars the loader cares about before each test."""
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "IMAIL_CONFIG_DIR"):
        monkeypatch.delenv(key, raising=False)


def test_loads_dotenv_from_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``~/.config/imail/.env`` should populate the process env, exactly as
    the user guide tells people to set up."""
    config_dir = tmp_path / "imail-config"
    config_dir.mkdir()
    (config_dir / ".env").write_text("DEEPSEEK_API_KEY=sk-from-config-dir\n")
    monkeypatch.setenv("IMAIL_CONFIG_DIR", str(config_dir))

    # Re-run the loader directly — the module-import call already ran with a
    # different env, but the function is idempotent and safe to invoke again.
    from imail.config import _load_dotenv_files

    monkeypatch.chdir(tmp_path)  # ensure no stray CWD .env interferes
    _load_dotenv_files()

    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-config-dir"


def test_cwd_dotenv_wins_over_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer running from a checkout with its own ``.env`` should not
    have their key silently overridden by a stale ``~/.config/imail/.env``."""
    config_dir = tmp_path / "imail-config"
    config_dir.mkdir()
    (config_dir / ".env").write_text("DEEPSEEK_API_KEY=sk-from-config-dir\n")
    monkeypatch.setenv("IMAIL_CONFIG_DIR", str(config_dir))

    cwd_dir = tmp_path / "checkout"
    cwd_dir.mkdir()
    (cwd_dir / ".env").write_text("DEEPSEEK_API_KEY=sk-from-cwd\n")
    monkeypatch.chdir(cwd_dir)

    from imail.config import _load_dotenv_files

    _load_dotenv_files()

    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-cwd"


def test_missing_config_dir_dotenv_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No .env anywhere → loader leaves env vars untouched, does not raise."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("IMAIL_CONFIG_DIR", str(empty_dir))
    monkeypatch.chdir(empty_dir)

    from imail.config import _load_dotenv_files

    _load_dotenv_files()  # must not raise

    assert "DEEPSEEK_API_KEY" not in os.environ
