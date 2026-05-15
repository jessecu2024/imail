"""Generic IMAP provider — covers Outlook, 163, QQ, Yahoo, iCloud, custom hosts.

Drafts are stored via IMAP APPEND to the Drafts folder (no SMTP send by design).

Known quirks handled here:
- 163 / QQ require an IMAP `ID` command after LOGIN, otherwise the server
  responds with "Unsafe Login". We send a benign client identifier.
- Drafts folder names vary (`Drafts`, `草稿箱`, etc.). We probe the SPECIAL-USE
  attribute via `LIST` and fall back to common names.
- imaplib's response strings are bytes; we decode RFC 2047 headers explicitly.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import time
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage, Message

from imail.providers.base import EmailMsg, ProviderError

DEFAULT_PORT = 993
COMMON_DRAFT_FOLDERS = ["Drafts", "[Gmail]/Drafts", "草稿箱", "Brouillons", "INBOX.Drafts"]


@dataclass(frozen=True)
class ImapPreset:
    """Connection settings for a well-known mail host."""

    host: str
    port: int = DEFAULT_PORT
    needs_imap_id: bool = False  # 163 / QQ requirement


# Hard-coded presets keep the UI buttons "just work" for the common cases.
PRESETS: dict[str, ImapPreset] = {
    "outlook": ImapPreset(host="outlook.office365.com"),
    "163": ImapPreset(host="imap.163.com", needs_imap_id=True),
    "126": ImapPreset(host="imap.126.com", needs_imap_id=True),
    "qq": ImapPreset(host="imap.qq.com", needs_imap_id=True),
    "yahoo": ImapPreset(host="imap.mail.yahoo.com"),
    "icloud": ImapPreset(host="imap.mail.me.com"),
}


class ImapProvider:
    """Connect over IMAPS, fetch unread mail, store drafts via APPEND."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = DEFAULT_PORT,
        needs_imap_id: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._needs_imap_id = needs_imap_id
        self._conn: imaplib.IMAP4_SSL | None = None
        self._drafts_folder: str | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def _ensure_connected(self) -> imaplib.IMAP4_SSL:
        if self._conn is not None:
            return self._conn

        try:
            conn = imaplib.IMAP4_SSL(self._host, self._port, timeout=30)
            conn.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            raise ProviderError(
                f"IMAP login failed for {self._username}@{self._host}: {exc}"
            ) from exc
        except OSError as exc:
            raise ProviderError(f"Cannot reach {self._host}:{self._port}: {exc}") from exc

        if self._needs_imap_id:
            self._send_imap_id(conn)

        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        finally:
            self._conn = None

    @staticmethod
    def _send_imap_id(conn: imaplib.IMAP4_SSL) -> None:
        """163/QQ refuse access without a client ID. Send something benign."""
        client_id = '("name" "imail" "version" "0.2" "vendor" "github.com/jessecu2024/imail")'
        # imaplib doesn't expose ID directly; piggyback on _simple_command.
        typ, _ = conn._simple_command("ID", client_id)
        conn._untagged_response(typ, [None], "ID")

    # ------------------------------------------------------------------
    # MailProvider surface
    # ------------------------------------------------------------------
    def fetch_unread(self, limit: int = 20) -> list[EmailMsg]:
        conn = self._ensure_connected()
        typ, _ = conn.select("INBOX", readonly=False)
        if typ != "OK":
            raise ProviderError("Could not select INBOX.")

        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            raise ProviderError("IMAP UNSEEN search failed.")

        ids = data[0].split()
        # Newest first; trim to limit.
        ids = list(reversed(ids))[:limit]
        if not ids:
            return []

        # BODY.PEEK[] avoids implicitly flipping the \Seen flag.
        id_set = ",".join(i.decode("ascii") for i in ids)
        typ, fetched = conn.fetch(id_set, "(BODY.PEEK[] UID)")
        if typ != "OK":
            raise ProviderError("IMAP FETCH failed.")

        # imaplib zip-of-tuples-with-flags: walk in pairs.
        messages: list[EmailMsg] = []
        for chunk in fetched:
            if not isinstance(chunk, tuple) or len(chunk) < 2:
                continue
            envelope_header = chunk[0]
            raw_body = chunk[1]
            if not isinstance(envelope_header, bytes) or not isinstance(raw_body, bytes):
                continue
            uid = _extract_uid(envelope_header)
            if not uid:
                continue
            messages.append(self._parse_message(uid, raw_body))

        return messages

    def create_draft(self, email_msg: EmailMsg, body: str) -> str:
        conn = self._ensure_connected()
        folder = self._get_drafts_folder(conn)

        reply = EmailMessage()
        reply.set_content(body)
        reply["From"] = self._username
        reply["To"] = email_msg.sender
        reply["Subject"] = self._reply_subject(email_msg.subject)
        reply["In-Reply-To"] = email_msg.id
        reply["References"] = email_msg.id

        raw = reply.as_bytes()
        date = imaplib.Time2Internaldate(time.time())

        typ, response = conn.append(folder, "\\Draft", date, raw)
        if typ != "OK":
            raise ProviderError(f"APPEND to {folder} failed: {response!r}")

        # IMAP doesn't return a stable draft id; use the UIDNEXT from STATUS.
        typ, status = conn.status(folder, "(UIDNEXT)")
        if typ == "OK" and status:
            return _parse_status_uidnext(status[0]) or "appended"
        return "appended"

    def mark_read(self, email_msg: EmailMsg) -> None:
        conn = self._ensure_connected()
        conn.select("INBOX")
        conn.uid("STORE", email_msg.id, "+FLAGS", "(\\Seen)")

    def archive(self, email_msg: EmailMsg) -> None:
        # IMAP "archive" varies. Simplest portable behavior: set \Seen + remove
        # from INBOX by EXPUNGEing after \Deleted, but that destroys the message.
        # Safer compromise: just mark as read; user can move it server-side.
        # Override per-provider later if needed.
        self.mark_read(email_msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_drafts_folder(self, conn: imaplib.IMAP4_SSL) -> str:
        if self._drafts_folder is not None:
            return self._drafts_folder

        # 1) Try SPECIAL-USE: LIST returns "\Drafts" attribute for the drafts box.
        typ, listing = conn.list()
        if typ == "OK":
            for raw in listing or []:
                if not isinstance(raw, bytes):
                    continue
                line = raw.decode(errors="replace")
                if "\\Drafts" in line:
                    folder = _parse_list_folder(line)
                    if folder:
                        self._drafts_folder = folder
                        return folder

        # 2) Fall back to common names.
        for candidate in COMMON_DRAFT_FOLDERS:
            typ, _ = conn.select(candidate, readonly=True)
            if typ == "OK":
                conn.close()
                self._drafts_folder = candidate
                return candidate

        raise ProviderError(
            "Could not locate a Drafts folder. "
            "Please create one called 'Drafts' on the mail server."
        )

    def _parse_message(self, uid: str, raw: bytes) -> EmailMsg:
        msg: Message = email.message_from_bytes(raw, policy=email.policy.default)

        subject = _decode_header_safe(msg.get("Subject", "(no subject)"))
        sender = _decode_header_safe(msg.get("From", "(unknown)"))
        body = _extract_plain_body(msg)
        snippet = (body[:200] + " …") if len(body) > 200 else body

        return EmailMsg(
            id=uid,
            thread_id=uid,  # IMAP has no first-class threading; fall back to uid.
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        )

    @staticmethod
    def _reply_subject(original: str) -> str:
        return original if original.lower().startswith("re:") else f"Re: {original}"


# ----------------------------------------------------------------------
# Module-level helpers (pure functions — easy to test)
# ----------------------------------------------------------------------
def _decode_header_safe(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError):
        return value


def _extract_plain_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return str(payload or "")


def _extract_uid(envelope_header: bytes) -> str | None:
    """imaplib returns headers like b'1 (UID 1234 BODY[] {12345}\\r\\n'."""
    text = envelope_header.decode(errors="replace")
    marker = "UID "
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker) :]
    uid = ""
    for ch in rest:
        if ch.isdigit():
            uid += ch
        else:
            break
    return uid or None


def _parse_list_folder(list_line: str) -> str | None:
    """LIST line: (\\HasNoChildren \\Drafts) "/" "Drafts" → return "Drafts"."""
    # Folder name is the last quoted segment (or last token after last space).
    if list_line.endswith('"'):
        # Last quoted segment
        last_quote = list_line.rfind('"', 0, len(list_line) - 1)
        if last_quote != -1:
            return list_line[last_quote + 1 : -1]
    parts = list_line.rsplit(maxsplit=1)
    return parts[-1] if parts else None


def _parse_status_uidnext(status_line: bytes) -> str | None:
    """STATUS response: b'"Drafts" (UIDNEXT 42)' → return '42'."""
    text = status_line.decode(errors="replace")
    marker = "UIDNEXT "
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker) :]
    uid = ""
    for ch in rest:
        if ch.isdigit():
            uid += ch
        else:
            break
    return uid or None
