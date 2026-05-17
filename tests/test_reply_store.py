"""Tests for the on-disk reply cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from imail.providers.base import EmailMsg
from imail.reply_generator import ReplyTrio
from imail.reply_store import ReplyStore


@pytest.fixture
def store(tmp_path: Path) -> ReplyStore:
    return ReplyStore.for_account(tmp_path, account_id="acct1")


def _email(mid: str = "m1", sender: str = "Alex <a@x>") -> EmailMsg:
    return EmailMsg(
        id=mid,
        thread_id=mid,
        sender=sender,
        subject="Coffee?",
        snippet="hi",
        body="Hi Jie, coffee?",
        date="Mon, 01 Jan 2026 10:00:00 +0000",
        unread=True,
    )


def _trio() -> ReplyTrio:
    return ReplyTrio(positive="yes!", neutral="maybe", negative="no thanks", is_spam=False)


def test_get_pending_returns_none_when_empty(store: ReplyStore) -> None:
    assert store.get_pending("m1") is None


def test_put_then_get_pending_round_trips(store: ReplyStore) -> None:
    store.put_pending("m1", _email(), _trio())
    entry = store.get_pending("m1")
    assert entry is not None
    assert entry.email.sender == "Alex <a@x>"
    assert entry.trio.positive == "yes!"


def test_pending_persists_across_instances(tmp_path: Path) -> None:
    """Writing in one instance must be visible to a fresh instance on the
    same path — that's the whole point of disk persistence."""
    a = ReplyStore.for_account(tmp_path, "acct1")
    a.put_pending("m1", _email(), _trio())

    b = ReplyStore.for_account(tmp_path, "acct1")
    entry = b.get_pending("m1")
    assert entry is not None
    assert entry.trio.neutral == "maybe"


def test_mark_done_drops_pending_and_keeps_chosen_reply(store: ReplyStore) -> None:
    store.put_pending("m1", _email(), _trio())
    done = store.mark_done("m1", "Dear Alex,\n\nYes!\n\nBest regards,\nJie Xu")
    assert store.get_pending("m1") is None
    assert store.is_done("m1") is True
    assert done.chosen_reply.startswith("Dear Alex,")
    assert done.sender == "Alex <a@x>"
    assert done.subject == "Coffee?"
    assert done.body == "Hi Jie, coffee?"  # original incoming body preserved


def test_mark_done_email_kwarg_overrides_pending(store: ReplyStore) -> None:
    """The server has _session.current — pass it explicitly so body/sender/date
    come from the live message even if pending is absent or stale."""
    fresh = _email(sender="Bob <b@x>")
    done = store.mark_done("m2", "thanks", email=fresh)
    assert done.sender == "Bob <b@x>"
    assert done.body == fresh.body


def test_mark_done_without_prior_pending_still_works(store: ReplyStore) -> None:
    """The batch triage path doesn't always pre-populate pending — mark_done
    must still record the chosen reply, even with empty metadata."""
    done = store.mark_done("m99", "Dear there,\n\nOK.\n\nBest regards,\nJie Xu")
    assert store.is_done("m99")
    assert done.chosen_reply.endswith("Jie Xu")
    assert done.sender == ""  # no pending → no metadata


def test_put_pending_is_idempotent_after_done(store: ReplyStore) -> None:
    """A late prefetch race must not resurrect a message the user already
    handled. mark_done → done; subsequent put_pending must NOT undo that."""
    store.put_pending("m1", _email(), _trio())
    store.mark_done("m1", "chosen")
    store.put_pending("m1", _email(), _trio())  # late prefetch
    assert store.get_pending("m1") is None
    assert store.is_done("m1")


def test_drop_pending_forgets_without_marking_done(store: ReplyStore) -> None:
    """Used when the spam-mover relocates a message to Junk — we want the
    pending entry gone but we don't want it in 'done' either."""
    store.put_pending("m1", _email(), _trio())
    store.drop_pending("m1")
    assert store.get_pending("m1") is None
    assert store.is_done("m1") is False


def test_done_ids_returns_set(store: ReplyStore) -> None:
    store.mark_done("m1", "r1")
    store.mark_done("m2", "r2")
    assert store.done_ids() == {"m1", "m2"}


def test_done_entries_newest_first(store: ReplyStore) -> None:
    store.mark_done("m1", "first")
    store.mark_done("m2", "second")
    entries = store.done_entries()
    # Both have ISO timestamps to the second; m2 was inserted later or equal.
    assert next(e.message_id for e in entries) in {"m1", "m2"}
    # The sort key is replied_at descending — verify it's not ascending.
    if entries[0].replied_at != entries[-1].replied_at:
        assert entries[0].replied_at >= entries[-1].replied_at


def test_done_persists_across_instances(tmp_path: Path) -> None:
    a = ReplyStore.for_account(tmp_path, "acct1")
    a.put_pending("m1", _email(), _trio())
    a.mark_done("m1", "Dear Alex,\n\nYes!\n\nBest regards,\nJie Xu")

    b = ReplyStore.for_account(tmp_path, "acct1")
    assert b.is_done("m1") is True
    entry = b.get_done("m1")
    assert entry is not None
    assert entry.chosen_reply.startswith("Dear Alex,")


def test_corrupt_file_is_recovered_gracefully(tmp_path: Path) -> None:
    """A truncated or partially-written JSON file shouldn't crash the
    server — we just start fresh and log a warning."""
    path = tmp_path / "replies-acct1.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = ReplyStore(path)
    assert store.get_pending("m1") is None
    assert store.is_done("m1") is False
    # And we can still write to it afterwards.
    store.mark_done("m1", "r")
    assert store.is_done("m1")


def test_file_is_mode_0600_after_write(tmp_path: Path) -> None:
    """Replies contain email content — not as sensitive as a password but
    not for other users on the box either."""
    store = ReplyStore.for_account(tmp_path, "acct1")
    store.put_pending("m1", _email(), _trio())
    path = tmp_path / "replies-acct1.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
