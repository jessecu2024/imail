"""Thin wrapper around the Gmail API for the triage workflow.

Scope: read unread messages, create drafts, mark as read, archive.
Auth: OAuth installed-app flow — first run opens a browser; token cached on disk.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read inbox + draft + modify labels. No "send" — drafts only by design.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


@dataclass(frozen=True)
class EmailMsg:
    """Minimal structured email payload used by the rest of the app."""

    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body: str  # plain-text body (best-effort)


class GmailClient:
    """Authenticated Gmail API client."""

    def __init__(self, credentials_path: Path, token_path: Path) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = build("gmail", "v1", credentials=self._authorize())

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    def _authorize(self) -> Credentials:
        creds: Credentials | None = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not self._credentials_path.exists():
                raise FileNotFoundError(
                    f"Gmail OAuth client file not found at {self._credentials_path}. "
                    "See docs/gmail-setup.md for how to create one."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self._credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json())
        return creds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_unread(self, limit: int = 20) -> list[EmailMsg]:
        """Return the most recent unread messages in INBOX."""
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q="is:unread in:inbox", maxResults=limit)
            .execute()
        )
        return [self._get_message(m["id"]) for m in resp.get("messages", [])]

    def create_draft(self, email: EmailMsg, body: str) -> str:
        """Create a reply draft in the same thread. Returns the draft id."""
        reply = EmailMessage()
        reply.set_content(body)
        reply["To"] = email.sender
        reply["Subject"] = self._reply_subject(email.subject)
        reply["In-Reply-To"] = email.id
        reply["References"] = email.id

        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
        draft = (
            self._service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw, "threadId": email.thread_id}},
            )
            .execute()
        )
        return str(draft["id"])

    def mark_read(self, email: EmailMsg) -> None:
        self._service.users().messages().modify(
            userId="me", id=email.id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def archive(self, email: EmailMsg) -> None:
        self._service.users().messages().modify(
            userId="me",
            id=email.id,
            body={"removeLabelIds": ["INBOX", "UNREAD"]},
        ).execute()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_message(self, message_id: str) -> EmailMsg:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        body = _extract_plain_body(msg["payload"])
        return EmailMsg(
            id=msg["id"],
            thread_id=msg["threadId"],
            sender=headers.get("from", "(unknown)"),
            subject=headers.get("subject", "(no subject)"),
            snippet=msg.get("snippet", ""),
            body=body,
        )

    @staticmethod
    def _reply_subject(original: str) -> str:
        return original if original.lower().startswith("re:") else f"Re: {original}"


def _extract_plain_body(payload: dict[str, Any]) -> str:
    """Walk MIME parts to find the best plain-text representation."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_b64(data)

    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return _decode_b64(data)
        nested = _extract_plain_body(part)
        if nested:
            return nested

    # Fall back to snippet if nothing else.
    return ""


def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
