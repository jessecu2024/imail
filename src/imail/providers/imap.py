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

import contextlib
import email
import email.policy
import imaplib
import smtplib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage, Message

from imail.providers.base import EmailMsg, FolderKind, ProviderError

# RFC 2971 IMAP ID extension isn't in Python's stdlib command table.
# Register it as valid in AUTH and SELECTED states so _simple_command("ID", ...)
# doesn't raise KeyError. Required to log in to 163 / QQ servers.
imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))

DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 465

# Per-folder kind: SPECIAL-USE attribute + fallback name list.
FOLDER_HINTS: dict[str, tuple[str, list[str]]] = {
    "inbox": ("\\Inbox", ["INBOX"]),
    "drafts": ("\\Drafts", ["Drafts", "[Gmail]/Drafts", "草稿箱", "Brouillons", "INBOX.Drafts"]),
    "sent": ("\\Sent", ["Sent", "Sent Items", "[Gmail]/Sent Mail", "已发送", "INBOX.Sent"]),
    "junk": ("\\Junk", ["Junk", "Spam", "[Gmail]/Spam", "垃圾邮件", "Junk E-mail", "INBOX.Junk"]),
}


@dataclass(frozen=True)
class ImapPreset:
    """Connection settings for a well-known mail host (IMAP + SMTP)."""

    host: str  # IMAP host
    smtp_host: str  # SMTP host
    port: int = DEFAULT_IMAP_PORT
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_use_ssl: bool = True  # False → STARTTLS on the given port (usually 587)
    needs_imap_id: bool = False  # 163 / QQ requirement


# Hard-coded presets keep the UI buttons "just work" for the common cases.
PRESETS: dict[str, ImapPreset] = {
    "outlook": ImapPreset(
        host="outlook.office365.com",
        smtp_host="smtp-mail.outlook.com",
        smtp_port=587,
        smtp_use_ssl=False,
    ),
    "163": ImapPreset(host="imap.163.com", smtp_host="smtp.163.com", needs_imap_id=True),
    "126": ImapPreset(host="imap.126.com", smtp_host="smtp.126.com", needs_imap_id=True),
    "qq": ImapPreset(host="imap.qq.com", smtp_host="smtp.qq.com", needs_imap_id=True),
    "yahoo": ImapPreset(host="imap.mail.yahoo.com", smtp_host="smtp.mail.yahoo.com"),
    "icloud": ImapPreset(
        host="imap.mail.me.com",
        smtp_host="smtp.mail.me.com",
        smtp_port=587,
        smtp_use_ssl=False,
    ),
}


class ImapProvider:
    """Connect over IMAPS, fetch unread mail, store drafts via APPEND, send via SMTP."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = DEFAULT_IMAP_PORT,
        needs_imap_id: bool = False,
        smtp_host: str = "",
        smtp_port: int = DEFAULT_SMTP_PORT,
        smtp_use_ssl: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._needs_imap_id = needs_imap_id
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_use_ssl = smtp_use_ssl
        self._conn: imaplib.IMAP4_SSL | None = None
        self._folder_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def _ensure_connected(self) -> imaplib.IMAP4_SSL:
        """Return a live IMAP4_SSL connection, reconnecting if the prior one died.

        163/QQ drop idle IMAP sockets after ~30-60s; without this check, any
        operation that happens after the user pauses to read/edit a reply blows
        up with BrokenPipeError. NOOP is cheap (~1 round-trip) and verifies the
        socket is still healthy.
        """
        if self._conn is not None:
            try:
                self._conn.noop()
                return self._conn
            except (imaplib.IMAP4.error, imaplib.IMAP4.abort, OSError):
                # Dead connection — drop it silently and reconnect below.
                with contextlib.suppress(Exception):
                    self._conn.logout()
                self._conn = None
                self._folder_cache.clear()

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
            try:
                self._send_imap_id(conn)
            except (imaplib.IMAP4.error, KeyError, OSError) as exc:
                raise ProviderError(
                    f"IMAP ID handshake failed for {self._host} (needed for 163/QQ): {exc}"
                ) from exc

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
    # Folder browsing (used by the sidebar UI)
    # ------------------------------------------------------------------
    def list_folder(self, kind: FolderKind, limit: int = 50) -> list[EmailMsg]:
        """List recent messages in a folder. Bodies left empty — use fetch_message."""
        conn = self._ensure_connected()
        folder = self._get_folder(kind, conn)
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise ProviderError(f"Could not select {folder}.")

        typ, data = conn.search(None, "ALL")
        if typ != "OK":
            raise ProviderError(f"IMAP search in {folder} failed.")

        ids = data[0].split()
        ids = list(reversed(ids))[:limit]
        if not ids:
            return []

        id_set = ",".join(i.decode("ascii") for i in ids)
        # Envelope-only fetch keeps payloads small for list views.
        typ, fetched = conn.fetch(
            id_set, "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
        )
        if typ != "OK":
            raise ProviderError(f"IMAP envelope fetch in {folder} failed.")

        return _parse_envelope_list(fetched)

    def fetch_message(self, kind: FolderKind, message_id: str) -> EmailMsg:
        """Return one message with full body."""
        conn = self._ensure_connected()
        folder = self._get_folder(kind, conn)
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise ProviderError(f"Could not select {folder}.")

        typ, fetched = conn.uid("FETCH", message_id, "(BODY.PEEK[])")
        if typ != "OK" or not fetched:
            raise ProviderError(f"Message {message_id} not found in {folder}.")

        for chunk in fetched:
            if isinstance(chunk, tuple) and len(chunk) >= 2 and isinstance(chunk[1], bytes):
                return self._parse_message(message_id, chunk[1])

        raise ProviderError(f"Could not parse message {message_id} in {folder}.")

    def delete_message(self, kind: FolderKind, message_id: str) -> None:
        """Mark a message deleted and expunge. Mainly used for drafts."""
        conn = self._ensure_connected()
        folder = self._get_folder(kind, conn)
        typ, _ = conn.select(folder, readonly=False)
        if typ != "OK":
            raise ProviderError(f"Could not select {folder}.")
        conn.uid("STORE", message_id, "+FLAGS", "(\\Deleted)")
        conn.expunge()

    def move_message(self, from_kind: FolderKind, to_kind: FolderKind, message_id: str) -> None:
        """Move a message between folders: COPY + STORE \\Deleted + EXPUNGE.

        Some servers support the IMAP MOVE extension (RFC 6851) which is atomic,
        but COPY+DELETE is the universally supported fallback and works on 163.
        """
        conn = self._ensure_connected()
        src = self._get_folder(from_kind, conn)
        dst = self._get_folder(to_kind, conn)

        typ, _ = conn.select(src, readonly=False)
        if typ != "OK":
            raise ProviderError(f"Could not select {src} for move.")

        typ, _ = conn.uid("COPY", message_id, dst)
        if typ != "OK":
            raise ProviderError(f"COPY from {src} to {dst} failed.")

        conn.uid("STORE", message_id, "+FLAGS", "(\\Deleted)")
        conn.expunge()

    def send(self, email_msg: EmailMsg, body: str) -> None:
        """Send the reply via SMTP. Most providers auto-copy to Sent folder."""
        if not self._smtp_host:
            raise ProviderError(
                "SMTP host is not configured for this account. "
                "Pick a provider preset (Outlook/163/QQ/...) or re-add the account "
                "with explicit SMTP settings."
            )

        reply = EmailMessage()
        reply.set_content(body)
        reply["From"] = self._username
        reply["To"] = email_msg.sender
        reply["Subject"] = self._reply_subject(email_msg.subject)
        reply["In-Reply-To"] = email_msg.id
        reply["References"] = email_msg.id

        try:
            if self._smtp_use_ssl:
                smtp: smtplib.SMTP = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=30)
            else:
                smtp = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30)
                smtp.starttls()
            try:
                smtp.login(self._username, self._password)
                smtp.send_message(reply)
            finally:
                with contextlib.suppress(smtplib.SMTPException, OSError):
                    smtp.quit()
        except smtplib.SMTPAuthenticationError as exc:
            raise ProviderError(
                f"SMTP auth failed for {self._username}@{self._smtp_host}: {exc}. "
                "For 163/QQ, make sure the password is the 16-character 授权码, "
                "not your normal login password."
            ) from exc
        except smtplib.SMTPException as exc:
            raise ProviderError(f"SMTP send failed: {exc}") from exc
        except OSError as exc:
            raise ProviderError(
                f"Cannot reach SMTP {self._smtp_host}:{self._smtp_port}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_folder(self, kind: str, conn: imaplib.IMAP4_SSL) -> str:
        """Resolve a UI-level folder kind to the actual IMAP folder name."""
        if kind in self._folder_cache:
            return self._folder_cache[kind]

        special_use, fallbacks = FOLDER_HINTS[kind]

        # 1) SPECIAL-USE via LIST.
        typ, listing = conn.list()
        if typ == "OK":
            for raw in listing or []:
                if not isinstance(raw, bytes):
                    continue
                line = raw.decode(errors="replace")
                if special_use in line:
                    folder = _parse_list_folder(line)
                    if folder:
                        self._folder_cache[kind] = folder
                        return folder

        # 2) Common-name fallback.
        for candidate in fallbacks:
            typ, _ = conn.select(candidate, readonly=True)
            if typ == "OK":
                conn.close()
                self._folder_cache[kind] = candidate
                return candidate

        raise ProviderError(
            f"Could not locate a {kind} folder. Tried SPECIAL-USE {special_use} and "
            f"fallbacks {fallbacks}."
        )

    def _get_drafts_folder(self, conn: imaplib.IMAP4_SSL) -> str:
        """Back-compat shim used by create_draft."""
        return self._get_folder("drafts", conn)

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


def _extract_flags(envelope_header: bytes) -> set[str]:
    """imaplib responses include flags as '(FLAGS (\\Seen \\Recent) ...)'."""
    text = envelope_header.decode(errors="replace")
    idx = text.find("FLAGS (")
    if idx == -1:
        return set()
    end = text.find(")", idx)
    if end == -1:
        return set()
    return set(text[idx + len("FLAGS (") : end].split())


def _parse_envelope_list(fetched: Sequence[object]) -> list[EmailMsg]:
    """Turn imaplib's mixed-shape envelope FETCH response into EmailMsg list."""
    messages: list[EmailMsg] = []
    for chunk in fetched:
        if not isinstance(chunk, tuple) or len(chunk) < 2:
            continue
        envelope_header = chunk[0]
        header_bytes = chunk[1]
        if not isinstance(envelope_header, bytes) or not isinstance(header_bytes, bytes):
            continue
        uid = _extract_uid(envelope_header)
        if not uid:
            continue
        flags = _extract_flags(envelope_header)
        unread = "\\Seen" not in flags

        msg: Message = email.message_from_bytes(header_bytes, policy=email.policy.default)
        subject = _decode_header_safe(msg.get("Subject", "(no subject)"))
        sender = _decode_header_safe(msg.get("From", "(unknown)"))
        date = msg.get("Date", "")
        messages.append(
            EmailMsg(
                id=uid,
                thread_id=uid,
                sender=sender,
                subject=subject,
                snippet="",
                body="",
                date=date,
                unread=unread,
            )
        )
    return messages


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
