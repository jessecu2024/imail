"""Per-account on-disk store of why each junk message was classified as spam.

When DeepSeek flags a message as spam, it also writes one short English
sentence into ``ReplyTrio.spam_reason``. We move the message to Junk and
DROP the trio (no replies needed for spam), so the reason has nowhere
natural to live in ``ReplyStore``. This sidecar keeps it, keyed by the
message id, so the Junk folder can show the user *why* each item ended
up there — turning the Junk folder from a black box into something they
can audit and use to spot false positives.

Storage: ``<config_dir>/spam-reasons-<account-id>.json`` (mode 0600).
One file per account so removing an account just deletes one file.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("imail.spam_reason_store")


class SpamReasonStore:
    """JSON-backed map of message_id → spam reason + when it was classified.

    Not safe for cross-process concurrent use — the imail server is a
    single process, so an internal ``threading.Lock`` is enough. Writes go
    via a tempfile + ``os.replace`` so a crash mid-write can't corrupt the
    file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._reasons: dict[str, dict[str, str]] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def for_account(cls, config_dir: Path, account_id: str) -> SpamReasonStore:
        return cls(config_dir / f"spam-reasons-{account_id}.json")

    def put(self, message_id: str, reason: str) -> None:
        """Record (or overwrite) the spam reason for a message. Empty
        reasons are silently dropped — the UI has nothing to show."""
        reason = reason.strip()
        if not reason:
            return
        with self._lock:
            self._ensure_loaded()
            self._reasons[message_id] = {
                "reason": reason,
                "classified_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._persist()

    def get(self, message_id: str) -> str | None:
        with self._lock:
            self._ensure_loaded()
            entry = self._reasons.get(message_id)
            return entry["reason"] if entry else None

    def bulk_get(self, message_ids: list[str]) -> dict[str, str]:
        """Look up several at once. Missing ids are simply absent from the
        returned dict — callers don't need to pre-check existence."""
        with self._lock:
            self._ensure_loaded()
            return {
                mid: self._reasons[mid]["reason"] for mid in message_ids if mid in self._reasons
            }

    def drop(self, message_id: str) -> None:
        """Forget a single entry — e.g. user restored the message from
        Junk, or the message was permanently deleted."""
        with self._lock:
            self._ensure_loaded()
            if self._reasons.pop(message_id, None) is not None:
                self._persist()

    def drop_many(self, message_ids: list[str]) -> None:
        with self._lock:
            self._ensure_loaded()
            changed = False
            for mid in message_ids:
                if self._reasons.pop(mid, None) is not None:
                    changed = True
            if changed:
                self._persist()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "SpamReasonStore: failed to load %s (%s) — starting fresh",
                self._path,
                exc,
            )
            return
        for mid, raw in (data.get("reasons") or {}).items():
            if isinstance(raw, dict) and "reason" in raw:
                self._reasons[mid] = {
                    "reason": str(raw["reason"]),
                    "classified_at": str(raw.get("classified_at", "")),
                }

    def _persist(self) -> None:
        """Atomic write — tempfile + rename. Caller must hold ``self._lock``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"reasons": self._reasons}
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
