"""Persisted account configuration.

Non-secret fields (provider kind, hostname, username, OAuth credential file
path) live in `accounts.json`. Secrets (IMAP password, refresh token blobs)
live in the OS keyring (macOS Keychain on this user's machine).
"""

from __future__ import annotations

import contextlib
import json
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import keyring

from mail_triage.config import load_settings
from mail_triage.providers.base import MailProvider
from mail_triage.providers.gmail import GmailProvider
from mail_triage.providers.imap import PRESETS, ImapProvider

ProviderKind = Literal["gmail", "imap"]
KEYRING_SERVICE = "mail-triage"


@dataclass
class Account:
    """A single configured mailbox."""

    id: str
    kind: ProviderKind
    label: str  # display name (e.g. "Work · Gmail")
    username: str = ""  # email address
    imap_host: str = ""
    imap_port: int = 993
    imap_preset: str = ""  # 'outlook' | '163' | '126' | 'qq' | 'yahoo' | 'icloud' | '' (custom)
    gmail_credentials_path: str = ""  # filesystem path to Google OAuth client JSON

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "username": self.username,
            "imap_host": self.imap_host,
            "imap_port": self.imap_port,
            "imap_preset": self.imap_preset,
            "gmail_credentials_path": self.gmail_credentials_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> Account:
        return cls(
            id=str(data["id"]),
            kind=data["kind"],  # type: ignore[arg-type]
            label=str(data.get("label", "")),
            username=str(data.get("username", "")),
            imap_host=str(data.get("imap_host", "")),
            imap_port=int(data.get("imap_port", 993) or 993),
            imap_preset=str(data.get("imap_preset", "")),
            gmail_credentials_path=str(data.get("gmail_credentials_path", "")),
        )


@dataclass
class AccountStore:
    """Loads and persists accounts. One store per running process."""

    path: Path
    accounts: list[Account] = field(default_factory=list)

    @classmethod
    def load(cls) -> AccountStore:
        settings = load_settings(require_anthropic=False)
        store_path = settings.gmail_credentials_path.parent / "accounts.json"
        accounts: list[Account] = []
        if store_path.exists():
            try:
                data = json.loads(store_path.read_text())
                accounts = [Account.from_dict(a) for a in data.get("accounts", [])]
            except (json.JSONDecodeError, KeyError, TypeError):
                accounts = []
        return cls(path=store_path, accounts=accounts)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"accounts": [a.to_dict() for a in self.accounts]}, indent=2)
        )

    def add(self, account: Account, secret: str | None = None) -> None:
        self.accounts.append(account)
        if secret:
            keyring.set_password(KEYRING_SERVICE, account.id, secret)
        self.save()

    def remove(self, account_id: str) -> None:
        self.accounts = [a for a in self.accounts if a.id != account_id]
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, account_id)
        self.save()

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)

    @staticmethod
    def fresh_id() -> str:
        return f"acct_{uuid.uuid4().hex[:10]}_{secrets.token_hex(3)}"


def open_provider(account: Account) -> MailProvider:
    """Construct a live MailProvider for the given account."""
    if account.kind == "gmail":
        settings = load_settings(require_anthropic=False)
        credentials_path = (
            Path(account.gmail_credentials_path)
            if account.gmail_credentials_path
            else settings.gmail_credentials_path
        )
        token_path = settings.gmail_credentials_path.parent / f"token-{account.id}.json"
        return GmailProvider(credentials_path=credentials_path, token_path=token_path)

    if account.kind == "imap":
        password = keyring.get_password(KEYRING_SERVICE, account.id)
        if password is None:
            raise RuntimeError(f"No stored password for account {account.id}. Re-add this account.")
        preset = PRESETS.get(account.imap_preset) if account.imap_preset else None
        host = account.imap_host or (preset.host if preset else "")
        if not host:
            raise RuntimeError(f"Account {account.id} has no IMAP host configured.")
        return ImapProvider(
            host=host,
            port=account.imap_port or 993,
            username=account.username,
            password=password,
            needs_imap_id=bool(preset and preset.needs_imap_id),
        )

    raise RuntimeError(f"Unknown provider kind: {account.kind!r}")
