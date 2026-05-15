"""Provider abstraction. Every mail backend conforms to `MailProvider`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete a requested action."""


@dataclass(frozen=True)
class EmailMsg:
    """Provider-neutral email payload used by the UI and reply generator."""

    id: str  # provider-local message id
    thread_id: str  # provider-local thread/conversation id (== id for IMAP if no thread support)
    sender: str  # raw "Name <addr@example>" string
    subject: str
    snippet: str  # short preview
    body: str  # best-effort plain-text body


@runtime_checkable
class MailProvider(Protocol):
    """All mail backends must implement this surface."""

    def fetch_unread(self, limit: int = 20) -> list[EmailMsg]:
        """Return the most recent unread inbox messages."""

    def create_draft(self, email: EmailMsg, body: str) -> str:
        """Create a reply draft in the original thread/folder. Returns a stable id."""

    def mark_read(self, email: EmailMsg) -> None:
        """Mark the message as read (but keep it in the inbox)."""

    def archive(self, email: EmailMsg) -> None:
        """Move the message out of the inbox and mark it as read."""

    def close(self) -> None:
        """Release any open connections. Idempotent."""
