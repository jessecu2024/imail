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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from imail.accounts import Account, AccountStore, open_provider
from imail.config import load_settings
from imail.providers.base import EmailMsg, MailProvider, ProviderError
from imail.providers.imap import PRESETS
from imail.reply_generator import ReplyGenerator, ReplyTrio
from imail.reply_store import ReplyStore

logger = logging.getLogger("imail.server")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="imail", version="1.4.2")
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
    """A single open triage session. Holds the current email + the queue but
    NOT a dedicated IMAP provider — operations look up the per-account
    pooled connection (`use_provider`) on demand. The pool persists across
    sessions so subsequent clicks pay no IMAP-login cost.
    """

    def __init__(self, account: Account, generator: ReplyGenerator) -> None:
        self.account = account
        self.generator = generator
        self.queue: list[EmailMsg] = []
        self.current: EmailMsg | None = None

    def close(self) -> None:
        # Pool ownership lives outside the session — nothing to clean up here.
        return None


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
# Pre-generated reply cache for inbox messages — disk-backed per account.
# A ReplyStore tracks two states:
#   pending: DeepSeek already drafted three replies (cached so a restart
#            doesn't re-spend tokens regenerating).
#   done:    the user picked one and we saved / sent it. The trio is dropped;
#            only the chosen reply text + original body is kept. The inbox
#            listing tags these rows `replied=True` so the UI can colour
#            them differently; clicking one re-shows the saved reply instead
#            of redrafting fresh ones.
# Process-wide map of account_id → ReplyStore (lazy-constructed).
# ----------------------------------------------------------------------
_stores: dict[str, ReplyStore] = {}
_stores_lock = threading.Lock()


def _store_for(account_id: str) -> ReplyStore:
    with _stores_lock:
        store = _stores.get(account_id)
        if store is None:
            settings = load_settings(require_api_key=False)
            store = ReplyStore.for_account(settings.config_dir, account_id)
            _stores[account_id] = store
        return store


# A leaner cache for non-inbox folders (Sent / Drafts / Junk). We only need the
# full message body, no LLM replies — the user is just reading. Keyed by
# "{account_id}:{kind}:{message_id}".
_body_cache: dict[str, EmailMsg] = {}
_body_cache_lock = threading.Lock()


def _body_get(account_id: str, kind: str, message_id: str) -> EmailMsg | None:
    with _body_cache_lock:
        return _body_cache.get(f"{account_id}:{kind}:{message_id}")


def _body_put(account_id: str, kind: str, message_id: str, msg: EmailMsg) -> None:
    with _body_cache_lock:
        _body_cache[f"{account_id}:{kind}:{message_id}"] = msg


def _body_drop(account_id: str, kind: str, message_id: str) -> None:
    with _body_cache_lock:
        _body_cache.pop(f"{account_id}:{kind}:{message_id}", None)


# Prefix on synthetic message ids representing locally-cached "I already
# replied to this" entries surfaced inside the Sent folder listing.
_LOCAL_SENT_PREFIX = "local:"

# Cross-folder Flagged scan is expensive (4 IMAP SELECTs + 4 envelope
# FETCHes on 163, ~5-6 s warm). Cache the result per-account for a short
# TTL so back-to-back navigations to the Flagged folder don't redo the
# scan. Invalidated on every set_flag call. Memory-only, lost on restart.
_FLAGGED_CACHE_TTL_SEC = 30.0
_flagged_cache: dict[str, tuple[float, list[Any]]] = {}
_flagged_cache_lock = threading.Lock()


def _flagged_cache_get(account_id: str) -> list[Any] | None:
    import time as _t

    with _flagged_cache_lock:
        entry = _flagged_cache.get(account_id)
        if entry is None:
            return None
        ts, summaries = entry
        if _t.time() - ts > _FLAGGED_CACHE_TTL_SEC:
            _flagged_cache.pop(account_id, None)
            return None
        return summaries


def _flagged_cache_put(account_id: str, summaries: list[Any]) -> None:
    import time as _t

    with _flagged_cache_lock:
        _flagged_cache[account_id] = (_t.time(), summaries)


def _flagged_cache_invalidate(account_id: str) -> None:
    with _flagged_cache_lock:
        _flagged_cache.pop(account_id, None)


def _warm_inbox_cache(account_id: str, message_ids: list[str]) -> None:
    """Background task: pre-generate replies for every inbox message we just listed.

    Runs in FastAPI's threadpool after the inbox listing has already been sent
    to the client, so the user sees the list immediately. Each iteration costs
    one DeepSeek call (~$0.0002), so 50 inbox messages cost about a cent.

    Skips messages already in the on-disk store — either as pending (already
    drafted in a prior run) or as done (already handled by the user).
    """
    try:
        settings = load_settings(require_api_key=True)
    except RuntimeError:
        return  # no API key — nothing to do

    account_store = AccountStore.load()
    account = account_store.get(account_id)
    if account is None:
        return

    reply_store = _store_for(account_id)
    missing = [
        mid
        for mid in message_ids
        if reply_store.get_pending(mid) is None and not reply_store.is_done(mid)
    ]
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

    # Parallelise the DeepSeek calls (3 at a time) so a batch of new arrivals
    # gets drafted in parallel instead of one-by-one. IMAP ops (fetch + move)
    # stay on a single shared connection — serialised via `provider_lock` so
    # at most one IMAP command runs at a time. The win: 50 unread emails
    # finish prefetching in ~55s instead of ~150s, and each result lands in
    # the reply store within ~10ms of its DeepSeek call returning (no waiting
    # for batch completion before storing).
    provider_lock = threading.Lock()

    def _on_complete(fut: Any, mid: str, em: EmailMsg) -> None:
        try:
            trio = fut.result()
        except Exception as exc:
            logger.warning("Prefetch gen failed for %s/%s: %s", account_id, mid, exc)
            return
        with provider_lock:
            if trio.is_spam:
                # Model flagged spam — move it out of inbox so it stops
                # cluttering the UI. Don't store the trio (user only sees
                # the email in Junk).
                try:
                    provider.move_message("inbox", "junk", mid)
                    logger.info(
                        "Spam-moved to Junk: %s/%s subject=%r",
                        account_id,
                        mid,
                        em.subject,
                    )
                except ProviderError as exc:
                    logger.warning("Spam detected but move-to-junk failed for %s: %s", mid, exc)
                    reply_store.put_pending(mid, em, trio)
            else:
                reply_store.put_pending(mid, em, trio)
                logger.info("Prefetched replies for %s/%s", account_id, mid)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for mid in missing:
                if reply_store.get_pending(mid) is not None or reply_store.is_done(mid):
                    continue
                with provider_lock:
                    try:
                        email_msg = provider.fetch_message("inbox", mid)
                    except Exception as exc:
                        logger.warning("Prefetch fetch failed for %s/%s: %s", account_id, mid, exc)
                        continue
                fut = pool.submit(generator.generate, email_msg)
                fut.add_done_callback(lambda f, mid=mid, em=email_msg: _on_complete(f, mid, em))
            # pool.__exit__ joins all workers before continuing
    finally:
        with contextlib.suppress(Exception):
            provider.close()


def _warm_folder_bodies(account_id: str, kind: str, message_ids: list[str]) -> None:
    """Background task: cache full bodies for a non-inbox folder so the first
    click is instant. No DeepSeek call — these messages don't need replies
    drafted (Sent and Junk are read-only; Drafts open into the editor).

    Limits to the first 10 messages — fetching all 50 of Sent at startup is
    expensive on IMAP and the user almost always opens the newest ones first.
    """
    if not message_ids:
        return
    store = AccountStore.load()
    account = store.get(account_id)
    if account is None:
        return

    missing = [mid for mid in message_ids[:10] if _body_get(account_id, kind, mid) is None]
    if not missing:
        return

    try:
        provider = open_provider(account)
    except ProviderError as exc:
        logger.warning("Body prefetch: open_provider failed for %s: %s", account_id, exc)
        return

    try:
        for mid in missing:
            if _body_get(account_id, kind, mid) is not None:
                continue
            try:
                msg = provider.fetch_message(kind, mid)  # type: ignore[arg-type]
                _body_put(account_id, kind, mid, msg)
                logger.info("Prefetched body for %s/%s/%s", account_id, kind, mid)
            except Exception as exc:
                logger.warning("Body prefetch failed for %s/%s/%s: %s", account_id, kind, mid, exc)
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
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"] = "inbox"
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
    replied: bool = False  # inbox-only: true when this message is in the local "done" set
    flagged: bool = False  # IMAP \Flagged / Gmail STARRED — user-set star
    # For rows surfaced inside the cross-folder Flagged virtual view,
    # tells the frontend which real folder the row lives in so operations
    # (delete, flag, open) route to the correct backend kind.
    source_kind: str = ""


class MessageDetail(BaseModel):
    id: str
    sender: str
    subject: str
    body: str
    date: str
    flagged: bool = False
    # When this row is a locally-cached "I replied to this" entry in Sent,
    # surface the original incoming email below the reply so the user can
    # remember *what* they were replying to. None for regular IMAP rows.
    in_reply_to: dict[str, str] | None = None


class TriageNextResponse(BaseModel):
    done: bool
    remaining: int
    email: dict[str, str | int | bool] | None = None
    replies: ReplyTrio | None = None
    # When the user reopens an already-handled inbox message we don't draft
    # three new replies — we surface the one they chose last time instead.
    already_replied: bool = False
    chosen_reply: str | None = None
    replied_at: str | None = None


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
    # Also forget the on-disk reply cache for this account — keeping it would
    # leave a dangling file the user can't reach through the UI.
    with _stores_lock:
        rs = _stores.pop(account_id, None)
    if rs is not None:
        with contextlib.suppress(OSError):
            rs.path.unlink()
    return {"ok": True}


# ----------------------------------------------------------------------
# Folder browsing
# ----------------------------------------------------------------------
@app.get("/api/folders/{account_id}/{kind}", response_model=list[MessageSummary])
def list_folder(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"],
    background_tasks: BackgroundTasks,
) -> list[MessageSummary]:
    # `flagged` is a cross-folder virtual view — pulls each "real" folder,
    # filters to messages with the \\Flagged / STARRED bit set, then
    # concatenates. Same shape as a normal listing so the SPA renders it
    # through the existing code path. Apple Mail / Outlook do this too —
    # a flagged email in Sent should be findable from the Flagged
    # mailbox without having to remember which folder it lives in.
    actual_kind: Literal["inbox", "drafts", "sent", "junk"] = "inbox" if kind == "flagged" else kind

    if kind == "flagged":
        # 30-s cache hit short-circuits the whole cross-folder scan. The
        # cache is invalidated on every set_flag, so the first navigation
        # after a flag toggle still goes to the server (and picks up the
        # change), while back-to-back clicks within the TTL are instant.
        cached_summaries = _flagged_cache_get(account_id)
        if cached_summaries is not None:
            return [MessageSummary(**s) for s in cached_summaries]

        msgs: list[EmailMsg] = []
        # Track each message's source folder so the frontend knows which
        # backend kind to route operations to (delete/flag/open).
        source_kinds: dict[str, str] = {}
        # SEARCH FLAGGED was tried here originally to push the filter to
        # the server, but 163 doesn't keep an index for \Flagged — the
        # server ended up scanning every message in inbox (~50 k for a
        # busy mailbox) and the cross-folder Flagged route took 8-50 s.
        # The simpler list_folder + client-side filter, with a small
        # limit, ends up faster in practice because the server is
        # already accustomed to returning the N-newest envelopes.
        # Skip drafts — flagging a draft is extremely rare and the extra
        # IMAP SELECT shaves ~1 s off the warm-pool case.
        try:
            with use_provider(account_id) as provider:
                for sub_kind in ("inbox", "sent", "junk"):
                    try:
                        for m in provider.list_folder(sub_kind, limit=50):
                            if m.flagged:
                                msgs.append(m)
                                source_kinds[m.id] = sub_kind
                    except ProviderError as exc:
                        logger.warning("flagged: list_folder %s failed: %s", sub_kind, exc)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

        # Also include locally-cached "I replied to this" entries the user
        # flagged. These live only in the reply store — no IMAP analogue —
        # so the cross-folder scan above wouldn't see them otherwise.
        for d in _store_for(account_id).done_entries():
            if d.flagged:
                synthetic_id = f"{_LOCAL_SENT_PREFIX}{d.message_id}"
                msgs.append(
                    EmailMsg(
                        id=synthetic_id,
                        thread_id=synthetic_id,
                        sender=d.sender or "(unknown)",
                        subject=_reply_subject(d.subject),
                        snippet=d.body[:200] if d.body else "",
                        body=d.body,
                        date=d.replied_at,
                        unread=False,
                        flagged=True,
                    )
                )
                source_kinds[synthetic_id] = "sent"
    else:
        try:
            with use_provider(account_id) as provider:
                msgs = provider.list_folder(actual_kind, limit=50)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    # Inbox: tag every message we've already handled so the UI can colour
    # those rows differently. The prefetch skips done rows on its own — we
    # don't pay tokens to redraft replies the user has already chosen.
    handled: set[str] = set()
    if actual_kind == "inbox":
        handled = _store_for(account_id).done_ids()

    # Fire-and-forget warm-up:
    #   - Inbox (real): full triage prefetch (body + 3 DeepSeek replies +
    #     spam-move), scoped to messages that aren't already handled.
    #   - Sent / Drafts / Junk: just cache bodies for the top N so the first
    #     click is instant.
    #   - Flagged (virtual cross-folder view): NO prefetch — the IDs come
    #     from multiple folders, so handing them to _warm_inbox_cache (which
    #     calls provider.fetch_message("inbox", id)) would fail with id-not-found
    #     for the non-inbox ones, and the bodies are usually small/already
    #     cached anyway.
    if msgs:
        if kind == "inbox":
            unhandled_ids = [m.id for m in msgs if m.id not in handled]
            if unhandled_ids:
                background_tasks.add_task(_warm_inbox_cache, account_id, unhandled_ids)
        elif kind in ("sent", "drafts", "junk"):
            ids = [m.id for m in msgs]
            background_tasks.add_task(_warm_folder_bodies, account_id, actual_kind, ids)

    summaries = [
        MessageSummary(
            id=m.id,
            sender=m.sender,
            subject=m.subject,
            date=m.date,
            unread=m.unread,
            replied=(m.id in handled),
            flagged=m.flagged,
            source_kind=(source_kinds.get(m.id, "") if kind == "flagged" else ""),
        )
        for m in msgs
    ]

    # Sent: prepend every locally-recorded reply as a synthetic row. These
    # render instantly (no IMAP round-trip) and let the user re-read past
    # replies even when offline. Ids are prefixed `local:` so get_message
    # knows to serve the chosen reply from the store rather than from IMAP.
    if kind == "sent":
        local_rows = [
            MessageSummary(
                id=f"{_LOCAL_SENT_PREFIX}{e.message_id}",
                sender=e.sender or "(unknown)",
                subject=_reply_subject(e.subject),
                date=e.replied_at,
                unread=False,
            )
            for e in _store_for(account_id).done_entries()
        ]
        summaries = local_rows + summaries

    # Stash the freshly-computed cross-folder list so subsequent navigations
    # to Flagged within the TTL bypass the scan.
    if kind == "flagged":
        _flagged_cache_put(account_id, [s.model_dump() for s in summaries])

    return summaries


@app.get("/api/messages/{account_id}/{kind}/{message_id}", response_model=MessageDetail)
def get_message(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"],
    message_id: str,
) -> MessageDetail:
    # "flagged" is a virtual view of inbox — route the actual provider
    # call through inbox while preserving the API-level kind so the
    # cache stays partitioned per view.
    provider_kind: Literal["inbox", "drafts", "sent", "junk"] = (
        "inbox" if kind == "flagged" else kind
    )

    # Synthetic "Sent" row backed by the local reply store. The IMAP server
    # doesn't know this id; we serve the chosen reply text directly.
    if kind == "sent" and message_id.startswith(_LOCAL_SENT_PREFIX):
        original_id = message_id[len(_LOCAL_SENT_PREFIX) :]
        entry = _store_for(account_id).get_done(original_id)
        if entry is None:
            raise HTTPException(404, "Local sent entry not found.")
        in_reply_to = {
            "sender": entry.sender,
            "subject": entry.subject,
            "date": entry.date,
            "body": entry.body or "",
        }
        return MessageDetail(
            id=message_id,
            sender=entry.sender,
            subject=_reply_subject(entry.subject),
            body=entry.chosen_reply,
            date=entry.replied_at,
            in_reply_to=in_reply_to,
        )

    # Cache check first — the background warmup on list_folder usually has
    # already pulled the body for the top messages.
    cached = _body_get(account_id, provider_kind, message_id)
    if cached is not None:
        logger.info("Body cache HIT for %s/%s/%s", account_id, provider_kind, message_id)
        return MessageDetail(
            id=cached.id,
            sender=cached.sender,
            subject=cached.subject,
            body=cached.body,
            date=cached.date,
            flagged=cached.flagged,
        )

    try:
        with use_provider(account_id) as provider:
            msg = provider.fetch_message(provider_kind, message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Stash for next time so re-opening the same message is instant.
    _body_put(account_id, provider_kind, message_id, msg)

    return MessageDetail(
        id=msg.id,
        sender=msg.sender,
        subject=msg.subject,
        body=msg.body,
        date=msg.date,
        flagged=msg.flagged,
    )


@app.delete("/api/messages/{account_id}/{kind}/{message_id}")
def delete_message(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"],
    message_id: str,
) -> dict[str, bool]:
    """Delete a message everywhere — on the IMAP server (so 163 / other
    clients also see it gone) plus any local reply-store state attached to
    the same id (the "已回复" badge, the pending trio, the synthetic Sent
    row). The synthetic ``local:<mid>`` rows in Sent have no IMAP analog,
    so for those we only touch the local store.
    """
    # Synthetic Sent row — purely a store entry, nothing on the IMAP server.
    if kind == "sent" and message_id.startswith(_LOCAL_SENT_PREFIX):
        original_id = message_id[len(_LOCAL_SENT_PREFIX) :]
        if not _store_for(account_id).drop_done(original_id):
            raise HTTPException(404, "Local sent entry not found.")
        return {"ok": True}

    # Real IMAP message. The STORE +Deleted + EXPUNGE in provider.delete_message
    # is what makes the change sync to 163 webmail and any other client logged
    # into the same mailbox. "flagged" maps to inbox for the actual op.
    provider_kind: Literal["inbox", "drafts", "sent", "junk"] = (
        "inbox" if kind == "flagged" else kind
    )
    try:
        with use_provider(account_id) as provider:
            provider.delete_message(provider_kind, message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    _body_drop(account_id, provider_kind, message_id)

    # Clear any reply-store record tied to this id — the original email is
    # gone, so the "已回复" badge / pending trio / saved-reply mirror would
    # otherwise dangle.
    if provider_kind == "inbox":
        store = _store_for(account_id)
        store.drop_done(message_id)
        store.drop_pending(message_id)
    return {"ok": True}


# ----------------------------------------------------------------------
# Search, draft-edit, junk-restore
# ----------------------------------------------------------------------
@app.get("/api/search/{account_id}/{kind}", response_model=list[MessageSummary])
def search_folder(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"],
    q: str = "",
) -> list[MessageSummary]:
    provider_kind: Literal["inbox", "drafts", "sent", "junk"] = (
        "inbox" if kind == "flagged" else kind
    )
    try:
        with use_provider(account_id) as provider:
            msgs = provider.search(provider_kind, q, limit=50)
            if kind == "flagged":
                msgs = [m for m in msgs if m.flagged]
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return [
        MessageSummary(
            id=m.id,
            sender=m.sender,
            subject=m.subject,
            date=m.date,
            unread=m.unread,
            flagged=m.flagged,
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
    _body_drop(account_id, "drafts", message_id)
    return {"draft_id": new_id}


class FlagRequest(BaseModel):
    flagged: bool


class ComposeSendRequest(BaseModel):
    account_id: str
    to: str = Field(..., min_length=1)
    subject: str = ""
    body: str = Field(..., min_length=1)


@app.post("/api/compose/send")
def compose_send(req: ComposeSendRequest) -> dict[str, str]:
    """Send a free-form message (Reply / Reply all / Forward from the UI)."""
    store = AccountStore.load()
    account = store.get(req.account_id)
    if account is None:
        raise HTTPException(404, "Account not found.")
    try:
        with use_provider(req.account_id) as provider:
            provider.send_compose(req.to, req.subject, req.body)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"status": "sent"}


@app.post("/api/messages/{account_id}/{kind}/{message_id}/flag")
def set_flag(
    account_id: str,
    kind: Literal["inbox", "drafts", "sent", "junk", "flagged"],
    message_id: str,
    req: FlagRequest,
) -> dict[str, bool]:
    """Toggle the IMAP \\Flagged / Gmail STARRED flag on a message."""
    # Any flag change invalidates the cross-folder Flagged cache so the
    # next /api/folders/.../flagged call sees the change.
    _flagged_cache_invalidate(account_id)
    if message_id.startswith(_LOCAL_SENT_PREFIX):
        # Synthetic local rows aren't on the IMAP server. Persist the flag
        # state inside the local reply store so the Flagged virtual folder
        # can list them and so the state survives a restart.
        original_id = message_id[len(_LOCAL_SENT_PREFIX) :]
        _store_for(account_id).set_done_flagged(original_id, req.flagged)
        return {"ok": True, "flagged": req.flagged}
    provider_kind: Literal["inbox", "drafts", "sent", "junk"] = (
        "inbox" if kind == "flagged" else kind
    )
    try:
        with use_provider(account_id) as provider:
            provider.set_flagged(provider_kind, message_id, req.flagged)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True, "flagged": req.flagged}


@app.post("/api/messages/{account_id}/junk/{message_id}/restore")
def restore_from_junk(account_id: str, message_id: str) -> dict[str, bool]:
    """Move a message from Junk back into the Inbox (false-positive recovery)."""
    try:
        with use_provider(account_id) as provider:
            provider.move_message("junk", "inbox", message_id)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    _body_drop(account_id, "junk", message_id)
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
        with use_provider(req.account_id) as provider:
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
    _session = _Session(account=account, generator=generator)
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
            "flagged": email_msg.flagged,
        },
        replies=replies,
    )


@app.post("/api/triage/draft")
def triage_draft(req: DraftRequest) -> dict[str, str]:
    if _session is None or _session.current is None:
        raise HTTPException(400, "No email is currently being triaged.")
    current = _session.current
    account_id = _session.account.id
    try:
        with use_provider(account_id) as provider:
            draft_id = provider.create_draft(current, req.body)
            provider.mark_read(current)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    _store_for(account_id).mark_done(current.id, req.body, email=current)
    return {"draft_id": draft_id}


@app.post("/api/triage/send")
def triage_send(req: SendRequest) -> dict[str, str]:
    """Send the reply right now (via SMTP for IMAP accounts). Marks read on success."""
    if _session is None or _session.current is None:
        raise HTTPException(400, "No email is currently being triaged.")

    current = _session.current
    account_id = _session.account.id

    # The send itself must succeed or we return an error.
    try:
        with use_provider(account_id) as provider:
            provider.send(current, req.body)
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Marking the original as read is best-effort. If the user paused for a
    # long time before clicking send, the IMAP socket may have been idle-killed
    # by the server (163/QQ in particular). We don't want to surface a "failed"
    # state to the user when the actual send went through.
    try:
        with use_provider(account_id) as provider:
            provider.mark_read(current)
    except Exception as exc:
        logger.warning("mark_read after send failed (non-fatal): %s", exc)
    _store_for(account_id).mark_done(current.id, req.body, email=current)
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
    # we already have everything from the prefetch background task (or a
    # prior session, since the store is on disk).
    # "flagged" is a virtual view of inbox — treat it as inbox for triage.
    is_inbox_like = req.kind in ("inbox", "flagged")
    triage_kind: Literal["inbox", "drafts", "sent", "junk"] = (
        "inbox" if req.kind == "flagged" else req.kind
    )
    reply_store = _store_for(req.account_id) if is_inbox_like else None

    # If the user is reopening an already-handled inbox message, serve the
    # saved-reply view directly from the on-disk store. Skip both DeepSeek
    # *and* the IMAP login — this is a read-only view, no provider needed.
    # The previous version spun up a fresh IMAP connection here (1-2 s on
    # 163's "ID handshake then LOGIN") for every re-open, which made the
    # already-replied path feel slower than the original-draft path.
    if reply_store is not None and reply_store.is_done(req.message_id):
        done_entry = reply_store.get_done(req.message_id)
        if done_entry is not None:
            replayed = EmailMsg(
                id=req.message_id,
                thread_id=req.message_id,
                sender=done_entry.sender,
                subject=done_entry.subject,
                snippet=done_entry.body[:200] if done_entry.body else "",
                body=done_entry.body,
                date=done_entry.date,
            )
            # No _session needed — none of /api/triage/{draft,send,skip,end}
            # are reachable from the already-replied UI. End the previous
            # session (already done above) and return.
            return TriageNextResponse(
                done=False,
                remaining=0,
                email={
                    "id": replayed.id,
                    "sender": replayed.sender,
                    "subject": replayed.subject,
                    "body": replayed.body or "(original body was not saved)",
                    "date": replayed.date,
                    "flagged": False,
                },
                replies=None,
                already_replied=True,
                chosen_reply=done_entry.chosen_reply,
                replied_at=done_entry.replied_at,
            )

    cached = reply_store.get_pending(req.message_id) if reply_store is not None else None

    generator = ReplyGenerator(
        api_key=settings.api_key,
        model=settings.model,
        user_signoff=settings.user_signoff,
        base_url=settings.base_url,
    )

    if cached is not None:
        # Pure cache hit — no IMAP fetch, no DeepSeek call, no provider
        # open. Just reuse the email + replies that the prefetch already
        # stored on disk. This is the path that takes 12 seconds without
        # the pool, because every triage_single used to spin up a fresh
        # IMAP login even when it had everything it needed in memory.
        email_msg, replies = cached.email, cached.trio
        logger.info(
            "Cache HIT for %s/%s — replies served from disk", req.account_id, req.message_id
        )
    else:
        # Cold path: need IMAP fetch + a DeepSeek call. Use the pooled
        # provider so subsequent clicks on different messages don't each
        # pay the 1-2 s 163 login cost.
        try:
            with use_provider(req.account_id) as provider:
                email_msg = provider.fetch_message(triage_kind, req.message_id)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        try:
            replies = generator.generate(email_msg)
        except Exception as exc:
            raise HTTPException(502, f"Reply generation failed: {exc}") from exc

        # If live classification flags this as spam, push it out of inbox now.
        if is_inbox_like and replies.is_spam:
            with contextlib.suppress(ProviderError):
                with use_provider(req.account_id) as provider:
                    provider.move_message("inbox", "junk", req.message_id)
                logger.info("Spam-moved on click: %s/%s", req.account_id, req.message_id)
        elif is_inbox_like and reply_store is not None:
            reply_store.put_pending(req.message_id, email_msg, replies)

    # Clicking through to triage is a "read" event — flip the IMAP \Seen
    # flag so other clients (163 webmail, phone) see the same state as
    # the frontend optimistically does. Best-effort via the pool. NOTE:
    # this fires on cache-hit too — the original prefetch (_warm_inbox_cache)
    # only generates replies, it does NOT mark_read. Without this, a
    # cache-hit click would leave IMAP's \Seen unset, and the 30-s inbox
    # poll would later show the message as unread again ("the red dot
    # keeps coming back" bug).
    if is_inbox_like:
        with contextlib.suppress(Exception), use_provider(req.account_id) as provider:
            provider.mark_read(email_msg)

    _session = _Session(account=account, generator=generator)
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
            "flagged": email_msg.flagged,
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


def _reply_subject(original: str) -> str:
    """`Coffee?` → `Re: Coffee?`; idempotent on subjects that already
    start with the reply marker (case-insensitive, allowing `RE:` and
    common locale-prefixed forms like `回复:`)."""
    if not original:
        return "Re:"
    stripped = original.strip()
    head = stripped[:3].lower()
    if head == "re:" or stripped.startswith(("回复:", "回复：", "回复 ")):  # noqa: RUF001
        return stripped
    return f"Re: {stripped}"


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
