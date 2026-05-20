"""Gmail provider — OAuth installed-app flow + Gmail API."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from imail.providers.base import EmailMsg, FolderKind, ProviderError

# Full mailbox access: read + draft + modify labels + send.
# Note: adding `gmail.send` to an existing token requires re-consent.
# When a stale token is loaded with the old scope set, refresh() raises and we
# fall through to a fresh `flow.run_local_server()` that opens the browser
# again — which is exactly the migration the user needs.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

# Map our internal folder kinds onto Gmail system labels.
GMAIL_LABEL = {
    "inbox": "INBOX",
    "drafts": "DRAFT",
    "sent": "SENT",
    "junk": "SPAM",
}


class GmailProvider:
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
            try:
                creds.refresh(Request())
            except Exception:
                # Token can't satisfy the new scope set → fall through to a
                # fresh consent so the user re-grants with gmail.send included.
                creds = None

        if creds is None or not creds.valid:
            if not self._credentials_path.exists():
                raise ProviderError(
                    f"Gmail OAuth client file not found at {self._credentials_path}. "
                    "See docs/gmail-setup.md for how to create one."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self._credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json())
        return creds

    # ------------------------------------------------------------------
    # MailProvider surface — discovery + reading
    # ------------------------------------------------------------------
    def fetch_unread(self, limit: int = 20) -> list[EmailMsg]:
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q="is:unread in:inbox", maxResults=limit)
            .execute()
        )
        return [self._get_message(m["id"]) for m in resp.get("messages", [])]

    def list_folder(self, kind: FolderKind, limit: int = 50) -> list[EmailMsg]:
        label = GMAIL_LABEL.get(kind)
        if label is None:
            raise ProviderError(f"Unknown folder kind {kind!r}")
        # Drafts are exposed via a different endpoint and don't carry a real
        # message id until they're sent — handle separately.
        if kind == "drafts":
            return self._list_drafts(limit)
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", labelIds=[label], maxResults=limit)
            .execute()
        )
        return [
            self._get_message_summary(m["id"], unread_label=(kind == "inbox"))
            for m in resp.get("messages", [])
        ]

    def fetch_message(self, kind: FolderKind, message_id: str) -> EmailMsg:
        if kind == "drafts":
            draft = (
                self._service.users()
                .drafts()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return self._parse_full_message(draft["message"])
        return self._get_message(message_id)

    def delete_message(self, kind: FolderKind, message_id: str) -> None:
        if kind == "drafts":
            self._service.users().drafts().delete(userId="me", id=message_id).execute()
            return
        # For non-draft messages, send to trash. Permanent delete requires the
        # gmail.modify scope (we have it) plus messages.delete which is destructive.
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def move_message(self, from_kind: FolderKind, to_kind: FolderKind, message_id: str) -> None:
        src = GMAIL_LABEL[from_kind]
        dst = GMAIL_LABEL[to_kind]
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [dst], "removeLabelIds": [src]},
        ).execute()

    def search(self, kind: FolderKind, query: str, limit: int = 50) -> list[EmailMsg]:
        label = GMAIL_LABEL.get(kind)
        if label is None or not query.strip():
            return []
        gmail_query = f"label:{label.lower()} {query}"
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=gmail_query, maxResults=limit)
            .execute()
        )
        return [self._get_message_summary(m["id"]) for m in resp.get("messages", [])]

    # ------------------------------------------------------------------
    # MailProvider surface — drafts + send
    # ------------------------------------------------------------------
    def create_draft(self, email: EmailMsg, body: str) -> str:
        raw = _build_reply_raw(email, body, sign_as=None)
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

    def update_draft(self, message_id: str, new_body: str) -> str:
        # Gmail supports in-place draft updates — much cleaner than IMAP.
        original = self.fetch_message("drafts", message_id)
        raw = _build_reply_raw(
            EmailMsg(
                id=original.id,
                thread_id=original.thread_id,
                sender=original.sender,
                subject=original.subject,
                snippet="",
                body="",
            ),
            new_body,
            sign_as=None,
            reuse_recipient=True,
        )
        updated = (
            self._service.users()
            .drafts()
            .update(userId="me", id=message_id, body={"message": {"raw": raw}})
            .execute()
        )
        return str(updated["id"])

    def send(self, email: EmailMsg, body: str) -> None:
        raw = _build_reply_raw(email, body, sign_as=None)
        self._service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": email.thread_id},
        ).execute()

    def send_compose(self, to: str, subject: str, body: str) -> None:
        """Send an arbitrary message via the Gmail API."""
        if not to.strip():
            raise ProviderError("Recipient (To:) is empty.")
        from base64 import urlsafe_b64encode
        from email.message import EmailMessage as _EmailMessage

        msg = _EmailMessage()
        msg.set_content(body)
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"
        raw = urlsafe_b64encode(bytes(msg)).decode("ascii")
        self._service.users().messages().send(userId="me", body={"raw": raw}).execute()

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

    def set_flagged(self, kind: FolderKind, message_id: str, flagged: bool) -> None:
        # Gmail's "star" maps to the system STARRED label.
        body = {"addLabelIds": ["STARRED"]} if flagged else {"removeLabelIds": ["STARRED"]}
        self._service.users().messages().modify(userId="me", id=message_id, body=body).execute()

    def list_flagged(self, kind: FolderKind, limit: int = 50) -> list[EmailMsg]:
        """Server-side filter using the STARRED label intersected with the
        folder label. Skips drafts (Gmail drafts use a separate endpoint
        and can't be starred meaningfully)."""
        if kind == "drafts":
            return []
        label = GMAIL_LABEL.get(kind)
        if label is None:
            return []
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", labelIds=[label, "STARRED"], maxResults=limit)
            .execute()
        )
        return [
            self._get_message_summary(m["id"], unread_label=(kind == "inbox"))
            for m in resp.get("messages", [])
        ]

    def close(self) -> None:
        # The Discovery client holds no long-lived sockets.
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _list_drafts(self, limit: int) -> list[EmailMsg]:
        resp = self._service.users().drafts().list(userId="me", maxResults=limit).execute()
        out: list[EmailMsg] = []
        for d in resp.get("drafts", []) or []:
            try:
                detail = (
                    self._service.users()
                    .drafts()
                    .get(userId="me", id=d["id"], format="metadata")
                    .execute()
                )
                msg = detail.get("message", {})
                headers = {
                    h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
                }
                out.append(
                    EmailMsg(
                        id=d["id"],  # draft id, not message id
                        thread_id=msg.get("threadId", d["id"]),
                        sender=headers.get("to", self._whoami()),
                        subject=headers.get("subject", "(no subject)"),
                        snippet=msg.get("snippet", ""),
                        body="",
                        date=headers.get("date", ""),
                        unread=False,
                    )
                )
            except Exception:
                continue
        return out

    def _get_message(self, message_id: str) -> EmailMsg:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._parse_full_message(msg)

    def _get_message_summary(self, message_id: str, unread_label: bool = False) -> EmailMsg:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        label_ids = msg.get("labelIds") or []
        is_unread = "UNREAD" in label_ids if unread_label else False
        return EmailMsg(
            id=msg["id"],
            thread_id=msg.get("threadId", msg["id"]),
            sender=headers.get("from", "(unknown)"),
            subject=headers.get("subject", "(no subject)"),
            snippet=msg.get("snippet", ""),
            body="",
            date=headers.get("date", ""),
            unread=is_unread,
            flagged="STARRED" in label_ids,
        )

    def _parse_full_message(self, msg: dict[str, Any]) -> EmailMsg:
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = _extract_plain_body(msg.get("payload", {}))
        return EmailMsg(
            id=msg["id"],
            thread_id=msg.get("threadId", msg["id"]),
            sender=headers.get("from", "(unknown)"),
            subject=headers.get("subject", "(no subject)"),
            snippet=msg.get("snippet", ""),
            body=body,
            date=headers.get("date", ""),
            unread="UNREAD" in (msg.get("labelIds") or []),
        )

    def _whoami(self) -> str:
        profile = self._service.users().getProfile(userId="me").execute()
        return str(profile.get("emailAddress", ""))

    @staticmethod
    def _reply_subject(original: str) -> str:
        return original if original.lower().startswith("re:") else f"Re: {original}"


# ----------------------------------------------------------------------
# Module-level helpers (pure-ish)
# ----------------------------------------------------------------------
def _build_reply_raw(
    email: EmailMsg,
    body: str,
    sign_as: str | None = None,
    reuse_recipient: bool = False,
) -> str:
    """Build a base64url-encoded RFC822 reply for Gmail's raw-message endpoints.

    `reuse_recipient` is a marker for the update-draft path where the EmailMsg
    we constructed already holds the To: address (rather than a From: address);
    we keep it for clarity even though both branches use the same field today.
    """
    _ = reuse_recipient  # signature kept stable for callers
    reply = EmailMessage()
    reply.set_content(body)
    reply["To"] = email.sender
    if sign_as:
        reply["From"] = sign_as
    reply["Subject"] = (
        email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
    )
    reply["In-Reply-To"] = email.id
    reply["References"] = email.id
    return base64.urlsafe_b64encode(reply.as_bytes()).decode()


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
    return ""


def _decode_b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
