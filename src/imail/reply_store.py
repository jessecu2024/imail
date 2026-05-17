"""Per-account on-disk store of pre-generated replies and reply history.

Two states per inbox message:
  - PENDING — DeepSeek drafted three replies, the user hasn't picked yet.
              Stored so a restart doesn't waste tokens regenerating.
  - DONE    — the user picked one (saved as draft or sent). The trio is
              dropped; only the chosen reply text survives. Inbox listing
              hides DONE messages so the user never sees them again.

Why this exists:
  - Tokens. Restarting `imail` used to wipe the in-memory cache and re-call
    DeepSeek on every email. Now the trio survives across restarts.
  - Speed. The done dict doubles as a local mirror of "what I've handled",
    surfaced in the Sent folder listing without an IMAP round-trip.

Storage: ``<config_dir>/replies-<account-id>.json`` (mode 0600). One file
per account so removing an account just deletes one file.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from imail.providers.base import EmailMsg
from imail.reply_generator import ReplyTrio

logger = logging.getLogger("imail.reply_store")


@dataclass(frozen=True)
class PendingEntry:
    """A drafted-but-not-yet-picked email with its three reply candidates."""

    email: EmailMsg
    trio: ReplyTrio


@dataclass(frozen=True)
class DoneEntry:
    """A handled email: trio dropped, original message + chosen reply kept.

    ``body`` is the original incoming email's body — kept so the user can
    re-read what they replied to without an IMAP round-trip (and so the
    inbox view can show the original alongside the saved reply when
    the user clicks an already-replied row).
    """

    message_id: str
    sender: str
    subject: str
    date: str
    chosen_reply: str
    replied_at: str  # ISO-8601 UTC, second precision
    body: str = ""


class ReplyStore:
    """JSON-backed reply cache, one file per mailbox account.

    Not safe for cross-process concurrent use — the imail server is a single
    process, so an internal ``threading.Lock`` is enough. Writes go via a
    tempfile + ``os.replace`` so a crash mid-write can't corrupt the file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._pending: dict[str, PendingEntry] = {}
        self._done: dict[str, DoneEntry] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def for_account(cls, config_dir: Path, account_id: str) -> ReplyStore:
        return cls(config_dir / f"replies-{account_id}.json")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get_pending(self, message_id: str) -> PendingEntry | None:
        with self._lock:
            self._ensure_loaded()
            return self._pending.get(message_id)

    def put_pending(self, message_id: str, email: EmailMsg, trio: ReplyTrio) -> None:
        """Stash a fresh trio. No-ops if the message is already DONE so a
        late prefetch can't resurrect an already-handled email."""
        with self._lock:
            self._ensure_loaded()
            if message_id in self._done:
                return
            self._pending[message_id] = PendingEntry(email=email, trio=trio)
            self._persist()

    def drop_pending(self, message_id: str) -> None:
        """Forget a pending entry without marking it done (e.g. spam moved
        to Junk — we don't want it sitting in 'pending' forever)."""
        with self._lock:
            self._ensure_loaded()
            if self._pending.pop(message_id, None) is not None:
                self._persist()

    def is_done(self, message_id: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            return message_id in self._done

    def done_ids(self) -> set[str]:
        with self._lock:
            self._ensure_loaded()
            return set(self._done)

    def done_entries(self) -> list[DoneEntry]:
        """All handled emails, newest first."""
        with self._lock:
            self._ensure_loaded()
            return sorted(
                self._done.values(),
                key=lambda e: e.replied_at,
                reverse=True,
            )

    def get_done(self, message_id: str) -> DoneEntry | None:
        with self._lock:
            self._ensure_loaded()
            return self._done.get(message_id)

    def mark_done(
        self,
        message_id: str,
        chosen_reply: str,
        *,
        email: EmailMsg | None = None,
    ) -> DoneEntry:
        """Promote pending → done, keeping the chosen reply and the original body.

        Metadata source priority:
          1. ``email`` kwarg, if provided (server has it via ``_session.current``).
          2. The pending entry, if one was prefetched.
          3. Empty strings otherwise — the entry still records that the user
             replied, just without the original body / headers.
        """
        with self._lock:
            self._ensure_loaded()
            pending = self._pending.pop(message_id, None)
            source = email if email is not None else (pending.email if pending else None)
            if source is not None:
                sender = source.sender
                subject = source.subject
                date = source.date
                body = source.body
            else:
                sender = subject = date = body = ""
            entry = DoneEntry(
                message_id=message_id,
                sender=sender,
                subject=subject,
                date=date,
                chosen_reply=chosen_reply,
                replied_at=datetime.now(UTC).isoformat(timespec="seconds"),
                body=body,
            )
            self._done[message_id] = entry
            self._persist()
            return entry

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ReplyStore: failed to load %s (%s) — starting fresh", self._path, exc)
            return
        for mid, raw in (data.get("pending") or {}).items():
            try:
                self._pending[mid] = PendingEntry(
                    email=EmailMsg(**raw["email"]),
                    trio=ReplyTrio(**raw["trio"]),
                )
            except (KeyError, TypeError) as exc:
                logger.warning("ReplyStore: skipping malformed pending %s: %s", mid, exc)
        for mid, raw in (data.get("done") or {}).items():
            try:
                self._done[mid] = DoneEntry(message_id=mid, **raw)
            except (KeyError, TypeError) as exc:
                logger.warning("ReplyStore: skipping malformed done %s: %s", mid, exc)

    def _persist(self) -> None:
        """Atomic write — tempfile + rename. Caller must hold ``self._lock``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pending": {
                mid: {
                    "email": _email_as_dict(p.email),
                    "trio": p.trio.as_dict(),
                }
                for mid, p in self._pending.items()
            },
            "done": {
                mid: {
                    "sender": d.sender,
                    "subject": d.subject,
                    "date": d.date,
                    "chosen_reply": d.chosen_reply,
                    "replied_at": d.replied_at,
                    "body": d.body,
                }
                for mid, d in self._done.items()
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self._path)
        with contextlib.suppress(OSError):
            os.chmod(self._path, 0o600)


def _email_as_dict(e: EmailMsg) -> dict[str, object]:
    return {
        "id": e.id,
        "thread_id": e.thread_id,
        "sender": e.sender,
        "subject": e.subject,
        "snippet": e.snippet,
        "body": e.body,
        "date": e.date,
        "unread": e.unread,
    }
