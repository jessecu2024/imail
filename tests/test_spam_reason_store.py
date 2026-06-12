"""Tests for the per-account spam-reason sidecar store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from imail.spam_reason_store import SpamReasonStore


@pytest.fixture
def store(tmp_path: Path) -> SpamReasonStore:
    return SpamReasonStore.for_account(tmp_path, account_id="acct1")


def test_put_and_get_roundtrips(store: SpamReasonStore) -> None:
    store.put("m1", "Generic marketing blast from Mailchimp.")
    assert store.get("m1") == "Generic marketing blast from Mailchimp."


def test_get_returns_none_for_unknown_id(store: SpamReasonStore) -> None:
    assert store.get("nope") is None


def test_empty_reason_is_silently_ignored(store: SpamReasonStore, tmp_path: Path) -> None:
    # Whitespace-only is treated the same — no useful reason, nothing to show.
    store.put("m1", "   ")
    assert store.get("m1") is None
    # No file should have been written either, because there's nothing to persist.
    assert not (tmp_path / "spam-reasons-acct1.json").exists()


def test_bulk_get_only_returns_known_ids(store: SpamReasonStore) -> None:
    store.put("m1", "reason 1")
    store.put("m2", "reason 2")
    got = store.bulk_get(["m1", "m2", "missing"])
    assert got == {"m1": "reason 1", "m2": "reason 2"}


def test_bulk_get_on_empty_store(store: SpamReasonStore) -> None:
    assert store.bulk_get(["a", "b", "c"]) == {}


def test_drop_removes_entry(store: SpamReasonStore) -> None:
    store.put("m1", "reason 1")
    store.drop("m1")
    assert store.get("m1") is None


def test_drop_unknown_is_noop(store: SpamReasonStore) -> None:
    store.drop("nope")  # must not raise


def test_drop_many_only_persists_when_something_changed(
    store: SpamReasonStore, tmp_path: Path
) -> None:
    store.put("m1", "reason 1")
    store.put("m2", "reason 2")
    path = tmp_path / "spam-reasons-acct1.json"
    initial_mtime = path.stat().st_mtime_ns

    store.drop_many(["unknown_a", "unknown_b"])
    assert path.stat().st_mtime_ns == initial_mtime, "drop_many of unknowns should not rewrite file"

    store.drop_many(["m1", "m2"])
    assert store.get("m1") is None
    assert store.get("m2") is None


def test_put_persists_to_disk(store: SpamReasonStore, tmp_path: Path) -> None:
    store.put("m1", "reason 1")
    path = tmp_path / "spam-reasons-acct1.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["reasons"]["m1"]["reason"] == "reason 1"
    assert "classified_at" in data["reasons"]["m1"]


def test_load_survives_restart(tmp_path: Path) -> None:
    a = SpamReasonStore.for_account(tmp_path, "acct1")
    a.put("m1", "first round")
    # Fresh store reading the same path picks up the persisted entry.
    b = SpamReasonStore.for_account(tmp_path, "acct1")
    assert b.get("m1") == "first round"


def test_corrupt_file_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "spam-reasons-acct1.json"
    path.write_text("not json {", encoding="utf-8")
    store = SpamReasonStore.for_account(tmp_path, "acct1")
    # Returns None for everything, but accepting puts again works (and
    # overwrites the corrupt file with a clean payload).
    assert store.get("anything") is None
    store.put("m1", "ok")
    assert store.get("m1") == "ok"
