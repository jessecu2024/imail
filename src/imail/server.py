"""FastAPI server — the backend behind the web UI.

Endpoints:
    GET  /                       → serve the SPA shell
    GET  /api/status             → app health + whether LLM key is set
    GET  /api/accounts           → list configured accounts
    POST /api/accounts/imap      → add an IMAP account (Outlook / 163 / QQ / custom)
    POST /api/accounts/gmail     → add a Gmail account (OAuth flow runs server-side)
    DELETE /api/accounts/{id}    → remove an account
    POST /api/triage/start       → open a session against the given account
    GET  /api/triage/next        → fetch the next email + three reply drafts
    POST /api/triage/draft       → save the chosen reply to the Drafts folder
    POST /api/triage/skip        → skip the current email
    POST /api/triage/end         → close the session
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from imail.accounts import Account, AccountStore, open_provider
from imail.config import load_settings
from imail.providers.base import EmailMsg, MailProvider, ProviderError
from imail.providers.imap import PRESETS
from imail.reply_generator import ReplyGenerator, ReplyTrio

logger = logging.getLogger("imail.server")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="imail", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ----------------------------------------------------------------------
# Session state — single in-process triage session at a time.
# ----------------------------------------------------------------------
class _Session:
    def __init__(self, account: Account, provider: MailProvider, generator: ReplyGenerator) -> None:
        self.account = account
        self.provider = provider
        self.generator = generator
        self.queue: list[EmailMsg] = []
        self.current: EmailMsg | None = None

    def close(self) -> None:
        try:
            self.provider.close()
        except Exception:
            logger.exception("provider close failed")


_session: _Session | None = None


# ----------------------------------------------------------------------
# Request / response schemas
# ----------------------------------------------------------------------
class StatusResponse(BaseModel):
    ok: bool
    llm_configured: bool
    model: str
    signoff: str
    config_dir: str


class AccountResponse(BaseModel):
    id: str
    kind: Literal["gmail", "imap"]
    label: str
    username: str
    imap_host: str
    imap_preset: str


class AddImapRequest(BaseModel):
    label: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)
    preset: str = ""  # 'outlook' | '163' | '126' | 'qq' | 'yahoo' | 'icloud'
    host: str = ""  # required when preset is empty
    port: int = 993


class AddGmailRequest(BaseModel):
    label: str = Field(..., min_length=1)
    credentials_path: str = Field(..., min_length=1)


class StartRequest(BaseModel):
    account_id: str
    limit: int = Field(20, ge=1, le=100)


class DraftRequest(BaseModel):
    body: str = Field(..., min_length=1)


class TriageNextResponse(BaseModel):
    done: bool
    remaining: int
    email: dict[str, str | int] | None = None
    replies: ReplyTrio | None = None


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    settings = load_settings(require_api_key=False)
    return StatusResponse(
        ok=True,
        llm_configured=bool(settings.api_key),
        model=settings.model,
        signoff=settings.user_signoff,
        config_dir=str(settings.config_dir),
    )


@app.get("/api/accounts", response_model=list[AccountResponse])
def list_accounts() -> list[AccountResponse]:
    store = AccountStore.load()
    return [_account_view(a) for a in store.accounts]


@app.post("/api/accounts/imap", response_model=AccountResponse)
def add_imap_account(req: AddImapRequest) -> AccountResponse:
    preset = PRESETS.get(req.preset) if req.preset else None
    host = req.host or (preset.host if preset else "")
    if not host:
        raise HTTPException(400, "Need either a preset or an explicit IMAP host.")

    store = AccountStore.load()
    account = Account(
        id=AccountStore.fresh_id(),
        kind="imap",
        label=req.label,
        username=req.username,
        imap_host=host,
        imap_port=req.port or 993,
        imap_preset=req.preset,
    )
    store.add(account, secret=req.password)
    return _account_view(account)


@app.post("/api/accounts/gmail", response_model=AccountResponse)
def add_gmail_account(req: AddGmailRequest) -> AccountResponse:
    if not Path(req.credentials_path).exists():
        raise HTTPException(400, f"credentials.json not found at {req.credentials_path}")

    store = AccountStore.load()
    account = Account(
        id=AccountStore.fresh_id(),
        kind="gmail",
        label=req.label,
        username="",  # filled on first OAuth round-trip
        gmail_credentials_path=req.credentials_path,
    )
    store.add(account)
    return _account_view(account)


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str) -> dict[str, bool]:
    store = AccountStore.load()
    if store.get(account_id) is None:
        raise HTTPException(404, "Account not found.")
    store.remove(account_id)
    return {"ok": True}


@app.post("/api/triage/start")
def triage_start(req: StartRequest) -> dict[str, int]:
    global _session
    if _session is not None:
        _session.close()
        _session = None

    settings = load_settings(require_api_key=True)
    store = AccountStore.load()
    account = store.get(req.account_id)
    if account is None:
        raise HTTPException(404, "Account not found.")

    try:
        provider = open_provider(account)
        emails = provider.fetch_unread(limit=req.limit)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    generator = ReplyGenerator(
        api_key=settings.api_key,
        model=settings.model,
        user_signoff=settings.user_signoff,
    )
    _session = _Session(account=account, provider=provider, generator=generator)
    _session.queue = emails
    return {"queued": len(emails)}


@app.get("/api/triage/next", response_model=TriageNextResponse)
def triage_next() -> TriageNextResponse:
    if _session is None:
        raise HTTPException(400, "No active session. Call /api/triage/start first.")

    if not _session.queue:
        _session.current = None
        return TriageNextResponse(done=True, remaining=0)

    _session.current = _session.queue.pop(0)
    try:
        replies = _session.generator.generate(_session.current)
    except Exception as exc:
        raise HTTPException(502, f"Reply generation failed: {exc}") from exc

    return TriageNextResponse(
        done=False,
        remaining=len(_session.queue),
        email={
            "id": _session.current.id,
            "sender": _session.current.sender,
            "subject": _session.current.subject,
            "body": _session.current.body or _session.current.snippet,
        },
        replies=replies,
    )


@app.post("/api/triage/draft")
def triage_draft(req: DraftRequest) -> dict[str, str]:
    if _session is None or _session.current is None:
        raise HTTPException(400, "No email is currently being triaged.")
    try:
        draft_id = _session.provider.create_draft(_session.current, req.body)
        _session.provider.mark_read(_session.current)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"draft_id": draft_id}


@app.post("/api/triage/skip")
def triage_skip() -> dict[str, bool]:
    if _session is None or _session.current is None:
        raise HTTPException(400, "No email is currently being triaged.")
    _session.current = None
    return {"ok": True}


@app.post("/api/triage/end")
def triage_end() -> dict[str, bool]:
    global _session
    if _session is not None:
        _session.close()
        _session = None
    return {"ok": True}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _account_view(account: Account) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        kind=account.kind,
        label=account.label,
        username=account.username,
        imap_host=account.imap_host,
        imap_preset=account.imap_preset,
    )
