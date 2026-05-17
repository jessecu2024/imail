"""Provider abstraction. Every mail backend conforms to `MailProvider`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# Folder kinds the UI knows about. Providers map these to their own folder names
# (e.g. IMAP "Drafts" / "草稿箱" / "[Gmail]/Drafts").
FolderKind = Literal["inbox", "drafts", "sent", "junk"]


class ProviderError(RuntimeError):
    """Raised when a provider cannot complete a requested action."""


@dataclass(frozen=True)
class EmailMsg:
    """Provider-neutral email payload used by the UI and reply generator."""

    id: str  # provider-local message id (UID for IMAP, message id for Gmail)
    thread_id: str  # provider-local thread/conversation id (== id for IMAP)
    sender: str  # raw "Name <addr@example>" string
    subject: str
    snippet: str  # short preview, suitable for listings
    body: str  # best-effort plain-text body — may be empty in list mode
    date: str = ""  # RFC822 Date header, raw string
    unread: bool = False  # only meaningful for inbox listings


@runtime_checkable
class MailProvider(Protocol):
    """All mail backends must implement this surface."""

    def fetch_unread(self, limit: int = 20) -> list[EmailMsg]:
        """Return the most recent unread inbox messages (used by the batch triage queue)."""

    def list_folder(self, kind: FolderKind, limit: int = 50) -> list[EmailMsg]:
        """List recent messages in inbox/drafts/sent. Bodies are empty here — use
        fetch_message to load a single message's body on demand."""

    def fetch_message(self, kind: FolderKind, message_id: str) -> EmailMsg:
        """Return a single message with its full body."""

    def delete_message(self, kind: FolderKind, message_id: str) -> None:
        """Delete a message in the given folder. Mainly for drafts."""

    def move_message(self, from_kind: FolderKind, to_kind: FolderKind, message_id: str) -> None:
        """Move a message from one folder to another. Used by the spam classifier
        to push detected-spam mail out of the inbox, and by the UI to restore
        false positives from Junk back to Inbox."""

    def search(self, kind: FolderKind, query: str, limit: int = 50) -> list[EmailMsg]:
        """Full-text search within a folder. Returns message summaries (no body)."""

    def update_draft(self, message_id: str, new_body: str) -> str:
        """Replace a draft's body. Returns the new message id (IMAP can't update
        in place — it's a delete + append). To/Subject are preserved from the
        original."""

    def create_draft(self, email: EmailMsg, body: str) -> str:
        """Create a reply draft in the original thread/folder. Returns a stable id."""

    def send(self, email: EmailMsg, body: str) -> None:
        """Send the reply via the provider's outbound channel (SMTP / API).

        Implementations should raise :class:`ProviderError` if they can't send.
        """

    def mark_read(self, email: EmailMsg) -> None:
        """Mark the message as read (but keep it in the inbox)."""

    def archive(self, email: EmailMsg) -> None:
        """Move the message out of the inbox and mark it as read."""

    def close(self) -> None:
        """Release any open connections. Idempotent."""
