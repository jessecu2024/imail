"""Test fixtures shared across the suite.

Replaces the real OS keyring with an in-memory stub for all tests, so we never
write secrets into the developer's actual macOS Keychain during a test run.
"""

from __future__ import annotations

from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend


class _InMemoryKeyring(KeyringBackend):
    """Process-local keyring used only inside the test session."""

    priority = 1.0

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) in self._store:
            del self._store[(service, username)]
        else:
            raise keyring.errors.PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def _swap_keyring(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Swap in the in-memory keyring before every test."""
    keyring.set_keyring(_InMemoryKeyring())
    return
