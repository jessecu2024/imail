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

import contextlib
import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from imail.accounts import Account, AccountStore, open_provider
from imail.config import load_settings
from imail.providers.base import EmailMsg, MailProvider, ProviderError
from imail.providers.imap import PRESETS
from imail.reply_generator import ReplyGenerator, ReplyTrio

logger = logging.getLogger("imail.server")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="imail", version="1.1.1")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Static assets change every release; tell the browser not to cache them so a
# plain Cmd+R is always enough to pick up new JS/CSS.
@app.middleware("http")
async def _no_cache_static(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# Make every uncaught exception return JSON so the frontend can always parse it.
@app.exception_handler(Exception)
async def _json_exception_handler(_request: object, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


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
# Per-account IMAP connection pool.
# Logging into IMAP (especially 163) takes 1-2 seconds — paying that on every
# folder/message click makes the UI feel sluggish. By keeping ONE long-lived
# provider per account, the second-onwards click is instant. Concurrent use of
# a single imaplib connection is unsafe, so each account gets its own lock and
# routes hold the lock for the duration of an operation. Background tasks
# (prefetch, polling) still get their own dedicated providers — they shouldn't
# steal the lock and starve the user's click.
# ----------------------------------------------------------------------
_provider_pool: dict[str, MailProvider] = {}
_provider_locks: dict[str, threading.Lock] = {}
_pool_meta_lock = threading.Lock()


def _pool_acquire(account_id: str) -> tuple[MailProvider, threading.Lock]:
    """Return (provider, lock) for the account, creating both lazily."""
    with _pool_meta_lock:
        lock = _provider_locks.setdefault(account_id, threading.Lock())
        provider = _provider_pool.get(account_id)
        if provider is None:
            store = AccountStore.load()
            account = store.get(account_id)
            if account is None:
                raise HTTPException(404, "Account not found.")
            try:
                provider = open_provider(account)
            except ProviderError as exc:
                raise HTTPException(502, str(exc)) from exc
            _provider_pool[account_id] = provider
        return provider, lock


def _pool_evict(account_id: str) -> None:
    with _pool_meta_lock:
        p = _provider_pool.pop(account_id, None)
        _provider_locks.pop(account_id, None)
    if p:
        with contextlib.suppress(Exception):
            p.close()


@contextlib.contextmanager
def use_provider(account_id: str) -> Iterator[MailProvider]:
    """Borrow the pooled provider for one operation. Holds the per-account
    lock so two concurrent requests can't trample imaplib state."""
    provider, lock = _pool_acquire(account_id)
    with lock:
        yield provider


# ----------------------------------------------------------------------
# Pre-generated reply cache for inbox messages.
# Keyed by "{account_id}:{message_id}". Filled by a background task fired
# every time the inbox is listed; checked by /api/triage/single before doing
# a fresh DeepSeek call. Memory-only, cleared at process restart.
# ----------------------------------------------------------------------
_inbox_cache: dict[str, tuple[EmailMsg, ReplyTrio]] = {}
_inbox_cache_lock = threading.Lock()


def _cache_get(account_id: str, message_id: str) -> tuple[EmailMsg, ReplyTrio] | None:
    with _inbox_cache_lock:
        return _inbox_cache.get(f"{account_id}:{message_id}")


def _cache_put(account_id: str, message_id: str, email_msg: EmailMsg, trio: ReplyTrio) -> None:
    with _inbox_cache_lock:
        _inbox_cache[f"{account_id}:{message_id}"] = (email_msg, trio)


def _cache_drop(account_id: str, message_id: str) -> None:
    with _inbox_cache_lock:
        _inbox_cache.pop(f"{account_id}:{message_id}", None)


def _warm_inbox_cache(account_id: str, message_ids: list[str]) -> None:
    """Background task: pre-generate replies for every inbox message we just listed.

    Runs in FastAPI's threadpool after the inbox listing has already been sent
    to the client, so the user sees the list immediately. Each iteration costs
    one DeepSeek call (~$0.0002), so 50 inbox messages cost about a cent.
    """
    try:
        settings = load_settings(require_api_key=True)
    except RuntimeError:
        return  # no API key — nothing to do

    store = AccountStore.load()
    account = store.get(account_id)
    if account is None:
        return

    missing = [mid for mid in message_ids if _cache_get(account_id, mid) is None]
    if not missing:
        return

    try:
        provider = open_provider(account)
    except ProviderError as exc:
        logger.warning("Prefetch: open_provider failed for %s: %s", account_id, exc)
        return

    generator = ReplyGenerator(
        api_key=settings.api_key,
        model=settings.model,
        user_signoff=settings.user_signoff,
        base_url=settings.base_url,
    )

    try:
        for mid in missing:
            if _cache_get(account_id, mid) is not None:
                continue
            try:
                email_msg = provider.fetch_message("inbox", mid)
                trio = generator.generate(email_msg)
                if trio.is_spam:
                    # The model called this spam — move it out of inbox so it
                    # stops cluttering the UI. Don't bother caching (the user
                    # will only see it in the Junk folder).
                    try:
                        provider.move_message("inbox", "junk", mid)
                        logger.info(
                            "Spam-moved to Junk: %s/%s subject=%r",
                            account_id,
                            mid,
                            email_msg.subject,
                        )
                    except ProviderError as exc:
                        logger.warning("Spam detected but move-to-junk failed for %s: %s", mid, exc)
                        _cache_put(account_id, mid, email_msg, trio)
                else:
                    _cache_put(account_id, mid, email_msg, trio)
                    logger.info("Prefetched replies for %s/%s", account_id, mid)
            except Exception as exc:
                logger.warning("Prefetch failed for %s/%s: %s", account_id, mid, exc)
    finally:
        with contextlib.suppress(Exception):
            provider.close()


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


class SingleTriageRequest(BaseModel):
    account_id: str
    kind: Literal["inbox", "drafts", "sent", "junk"] = "inbox"
    message_id: str


class DraftRequest(BaseModel):
    body: str = Field(..., min_length=1)


class SendRequest(BaseModel):
    body: str = Field(..., min_length=1)


class MessageSummary(BaseModel):
    id: str
    sender: str
    subject: str
    date: str
    unread: bool


class MessageDetail(BaseModel):
    id: str
    sender: str
    subject: str
    body: str
    date: str


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
        smtp_host=preset.smtp_host if preset else "",
        smtp_port=preset.smtp_port if preset else 465,
        smtp_use_ssl=preset.smtp_use_ssl if preset else True,
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
    _pool_evict(account_id)
    return {"ok": True}


# ----------------------------------------------------------------------
# Folder browsing
# ----------------------------------------------------------------------
@app.get("/api/folders/{account_id}/{kind}", response_model=list[MessageSummary])
def list_folder(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk"],
    background_tasks: BackgroundTasks,
) -> list[MessageSummary]:
    try:
        with use_provider(account_id) as provider:
            msgs = provider.list_folder(kind, limit=50)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Fire-and-forget: pre-generate replies for the inbox so the user gets an
    # instant response when they click any email. Drafts/Sent don't need this.
    if kind == "inbox" and msgs:
        background_tasks.add_task(_warm_inbox_cache, account_id, [m.id for m in msgs])

    return [
        MessageSummary(
            id=m.id,
            sender=m.sender,
            subject=m.subject,
            date=m.date,
            unread=m.unread,
        )
        for m in msgs
    ]


@app.get("/api/messages/{account_id}/{kind}/{message_id}", response_model=MessageDetail)
def get_message(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk"],
    message_id: str,
) -> MessageDetail:
    try:
        with use_provider(account_id) as provider:
            msg = provider.fetch_message(kind, message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return MessageDetail(
        id=msg.id,
        sender=msg.sender,
        subject=msg.subject,
        body=msg.body,
        date=msg.date,
    )


@app.delete("/api/messages/{account_id}/{kind}/{message_id}")
def delete_message(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk"],
    message_id: str,
) -> dict[str, bool]:
    try:
        with use_provider(account_id) as provider:
            provider.delete_message(kind, message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


# ----------------------------------------------------------------------
# Search, draft-edit, junk-restore
# ----------------------------------------------------------------------
@app.get("/api/search/{account_id}/{kind}", response_model=list[MessageSummary])
def search_folder(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk"],
    q: str = "",
) -> list[MessageSummary]:
    try:
        with use_provider(account_id) as provider:
            msgs = provider.search(kind, q, limit=50)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return [
        MessageSummary(
            id=m.id,
            sender=m.sender,
            subject=m.subject,
            date=m.date,
            unread=m.unread,
        )
        for m in msgs
    ]


class EditDraftRequest(BaseModel):
    body: str = Field(..., min_length=1)


@app.post("/api/messages/{account_id}/drafts/{message_id}/edit")
def edit_draft(account_id: str, message_id: str, req: EditDraftRequest) -> dict[str, str]:
    """Replace a draft's body. Returns the new draft id."""
    try:
        with use_provider(account_id) as provider:
            new_id = provider.update_draft(message_id, req.body)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"draft_id": new_id}


@app.post("/api/messages/{account_id}/junk/{message_id}/restore")
def restore_from_junk(account_id: str, message_id: str) -> dict[str, bool]:
    """Move a message from Junk back into the Inbox (false-positive recovery)."""
    try:
        with use_provider(account_id) as provider:
            provider.move_message("junk", "inbox", message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}


# ----------------------------------------------------------------------
# Triage — both batch (queue) and single-email modes
# ----------------------------------------------------------------------
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
    except Exception as exc:
        logger.exception("Unexpected error opening provider")
        raise HTTPException(500, f"Provider failed unexpectedly: {exc!r}") from exc

    generator = ReplyGenerator(
        api_key=settings.api_key,
        model=settings.model,
        user_signoff=settings.user_signoff,
        base_url=settings.base_url,
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

    # Snapshot into a local — concurrent /api/triage/next or /skip would otherwise
    # race on _session.current and we'd read None mid-flight.
    email_msg = _session.queue.pop(0)
    _session.current = email_msg
    try:
        replies = _session.generator.generate(email_msg)
    except Exception as exc:
        raise HTTPException(502, f"Reply generation failed: {exc}") from exc

    return TriageNextResponse(
        done=False,
        remaining=len(_session.queue),
        email={
            "id": email_msg.id,
            "sender": email_msg.sender,
            "subject": email_msg.subject,
            "body": email_msg.body or email_msg.snippet,
            "date": email_msg.date,
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
    _cache_drop(_session.account.id, _session.current.id)
    return {"draft_id": draft_id}


@app.post("/api/triage/send")
def triage_send(req: SendRequest) -> dict[str, str]:
    """Send the reply right now (via SMTP for IMAP accounts). Marks read on success."""
    if _session is None or _session.current is None:
        raise HTTPException(400, "No email is currently being triaged.")

    # The send itself must succeed or we return an error.
    try:
        _session.provider.send(_session.current, req.body)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Marking the original as read is best-effort. If the user paused for a
    # long time before clicking send, the IMAP socket may have been idle-killed
    # by the server (163/QQ in particular). We don't want to surface a "failed"
    # state to the user when the actual send went through.
    try:
        _session.provider.mark_read(_session.current)
    except Exception as exc:
        logger.warning("mark_read after send failed (non-fatal): %s", exc)
    _cache_drop(_session.account.id, _session.current.id)
    return {"status": "sent"}


@app.post("/api/triage/single")
def triage_single(req: SingleTriageRequest) -> TriageNextResponse:
    """Open a triage session against a single specific email (no queue).

    After this returns, /api/triage/send /draft /skip /end work the same way as
    they do during a batch session — they operate on _session.current.
    """
    global _session
    if _session is not None:
        _session.close()
        _session = None

    settings = load_settings(require_api_key=True)
    store = AccountStore.load()
    account = store.get(req.account_id)
    if account is None:
        raise HTTPException(404, "Account not found.")

    # Cache hit? Skip both the IMAP fetch_message AND the DeepSeek call —
    # we already have everything from the prefetch background task.
    cached = _cache_get(req.account_id, req.message_id) if req.kind == "inbox" else None

    try:
        provider = open_provider(account)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    generator = ReplyGenerator(
        api_key=settings.api_key,
        model=settings.model,
        user_signoff=settings.user_signoff,
        base_url=settings.base_url,
    )

    if cached is not None:
        email_msg, replies = cached
        logger.info(
            "Cache HIT for %s/%s — replies served instantly", req.account_id, req.message_id
        )
    else:
        try:
            email_msg = provider.fetch_message(req.kind, req.message_id)
        except ProviderError as exc:
            provider.close()
            raise HTTPException(502, str(exc)) from exc
        try:
            replies = generator.generate(email_msg)
        except Exception as exc:
            provider.close()
            raise HTTPException(502, f"Reply generation failed: {exc}") from exc

        # If live classification flags this as spam, push it out of inbox now.
        if req.kind == "inbox" and replies.is_spam:
            with contextlib.suppress(ProviderError):
                provider.move_message("inbox", "junk", req.message_id)
                logger.info("Spam-moved on click: %s/%s", req.account_id, req.message_id)
        elif req.kind == "inbox":
            _cache_put(req.account_id, req.message_id, email_msg, replies)

    _session = _Session(account=account, provider=provider, generator=generator)
    _session.queue = []  # empty — no auto-advance after the user picks
    _session.current = email_msg

    return TriageNextResponse(
        done=False,
        remaining=0,
        email={
            "id": email_msg.id,
            "sender": email_msg.sender,
            "subject": email_msg.subject,
            "body": email_msg.body or email_msg.snippet,
            "date": email_msg.date,
        },
        replies=replies,
    )


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


def _account_provider(account_id: str) -> tuple[Account, MailProvider]:
    """Look up an account by id and open a fresh provider. 404s if missing."""
    store = AccountStore.load()
    account = store.get(account_id)
    if account is None:
        raise HTTPException(404, "Account not found.")
    try:
        provider = open_provider(account)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return account, provider
