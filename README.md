# mail-triage

> Inbox triage as a local app. Log in once to Gmail, Outlook, or 163 — then clear your unread
> emails by picking from three LLM-drafted replies per message.

You wake up to 30 emails. Each one needs a yes / no / "let me get back to you." This app fetches
your unread inbox, asks Claude for **three reply versions** per email (*positive · neutral · negative*),
and saves your pick as a Gmail/IMAP draft. You stay in control of every Send button.

```
┌──────────────────────────────────────────────────────────────┐
│  From       advisor@uni.edu                                  │
│  Subject    Can you join the panel on Thursday?              │
│  …                                                           │
└──────────────────────────────────────────────────────────────┘
  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │ 1·POSITIVE  │   │ 2·NEUTRAL   │   │ 3·NEGATIVE  │
  │ Yes, I'll … │   │ Let me  …   │   │ Thanks for  │
  │             │   │             │   │ asking, but │
  └─────────────┘   └─────────────┘   └─────────────┘
   1 / 2 / 3 → save draft     S → skip     Q → end session
```

## Features

- ✦ **Multi-provider** — Gmail (OAuth), and any IMAP mailbox: Outlook, 163, 126, QQ, Yahoo, iCloud, custom hosts.
- ✦ **Local web app** — `mail-triage` boots a FastAPI server and pops your browser to `http://127.0.0.1:8765`.
- ✦ **Drafts only** — never sends mail on your behalf. You press *Send* yourself in your normal mail client.
- ✦ **Secrets in OS keyring** — IMAP app passwords go to macOS Keychain (or platform equivalent), not a plain text file.
- ✦ **Three drafts per email in a single API call** — fast, cheap, self-consistent.
- ✦ **Prompt caching** keeps per-email latency low across a session.
- ✦ **Keyboard-first** — `1` / `2` / `3` to save a draft, `S` to skip, `Q` to end.

## Quick Start

```bash
# 1. Install deps
uv sync

# 2. Set your Anthropic key
cp .env.example .env
# → put your ANTHROPIC_API_KEY in .env

# 3. Launch the app
uv run mail-triage
# → opens http://127.0.0.1:8765 in your browser
```

First run will show an "Add account" screen. Pick a provider:

- **Gmail** — drop your `credentials.json` (see [docs/gmail-setup.md](docs/gmail-setup.md))
  and the first triage triggers the OAuth consent screen.
- **Outlook / 163 / 126 / QQ / Yahoo / iCloud** — sign in with your email + an
  **app password / 授权码** (see [docs/imap-setup.md](docs/imap-setup.md)).
- **Custom** — enter any IMAPS host + port.

After that, click your mailbox card → walk through unread emails → press 1/2/3 → drafts land in your Drafts folder.

## Configuration

All settings come from `.env` (see `.env.example`):

| Variable                  | Default                            | Notes                                    |
|---------------------------|------------------------------------|------------------------------------------|
| `ANTHROPIC_API_KEY`       | *(required)*                       | Your Anthropic key                       |
| `ANTHROPIC_MODEL`         | `claude-haiku-4-5-20251001`        | Use `claude-sonnet-4-6` for sharper drafts |
| `USER_SIGNOFF`            | `Jie`                              | Name used in reply sign-offs              |
| `MAIL_TRIAGE_PORT`        | `8765`                             | Local server port                         |
| `MAIL_TRIAGE_CONFIG_DIR`  | `~/.config/mail-triage`            | Where accounts.json and tokens live      |

## Development

```bash
uv sync                      # install dev + runtime deps
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy src              # type check
uv run pytest                # tests
```

## Project Structure

```
src/mail_triage/
  cli.py                  Launcher — boots uvicorn + opens browser
  config.py               .env loader
  server.py               FastAPI app — status, accounts, triage session
  accounts.py             Account manifest + keyring-backed secrets
  reply_generator.py      Anthropic call + JSON parser
  providers/
    base.py               EmailMsg + MailProvider Protocol
    gmail.py              Gmail API provider (OAuth)
    imap.py               Generic IMAP provider with presets
  static/
    index.html            Single-page UI
    app.js                Alpine.js component
    style.css             Dark theme

docs/
  gmail-setup.md          One-time Google Cloud Console walk-through
  imap-setup.md           How to get app passwords on each provider

tests/                    pytest suites
```

## Security Notes

- **No `gmail.send` scope is requested**; the Gmail provider can only fetch, draft, mark-read, archive.
- **IMAP app passwords are stored in the OS keyring**, not in `accounts.json` or `.env`.
- **OAuth tokens** are saved to `~/.config/mail-triage/token-<account-id>.json` (mode 0600).
- This is a personal tool. Don't host it on a shared machine without thinking about who can reach `127.0.0.1:8765`.

## License

MIT — see [LICENSE](LICENSE).
