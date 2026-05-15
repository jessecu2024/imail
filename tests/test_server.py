"""Smoke tests for the FastAPI surface.

These do not touch real mail servers; they exercise the routes that work without
opening a provider connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Isolate config dir per test so accounts.json doesn't leak between runs."""
    monkeypatch.setenv("MAIL_TRIAGE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    # Reimport server after env is set so it picks up the patched config dir.
    import importlib

    import mail_triage.server as server_module

    importlib.reload(server_module)

    with TestClient(server_module.app) as c:
        yield c


def test_status_endpoint(client: TestClient) -> None:
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["anthropic_configured"] is True


def test_accounts_starts_empty(client: TestClient) -> None:
    r = client.get("/api/accounts")
    assert r.status_code == 200
    assert r.json() == []


def test_add_imap_account_with_preset(client: TestClient) -> None:
    payload = {
        "label": "Test 163",
        "username": "user@163.com",
        "password": "auth-code-from-163",
        "preset": "163",
    }
    r = client.post("/api/accounts/imap", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "imap"
    assert body["label"] == "Test 163"
    assert body["imap_host"] == "imap.163.com"
    assert body["imap_preset"] == "163"


def test_add_imap_account_without_preset_or_host_rejected(client: TestClient) -> None:
    payload = {"label": "Bad", "username": "user@x.com", "password": "x"}
    r = client.post("/api/accounts/imap", json=payload)
    assert r.status_code == 400


def test_delete_unknown_account_returns_404(client: TestClient) -> None:
    r = client.delete("/api/accounts/acct_doesnotexist")
    assert r.status_code == 404


def test_triage_next_without_session_returns_400(client: TestClient) -> None:
    r = client.get("/api/triage/next")
    assert r.status_code == 400
