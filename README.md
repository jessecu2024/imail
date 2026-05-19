<p align="center">
  <img src="src/imail/static/icon.svg" alt="imail" width="96" />
</p>

<h1 align="center">imail</h1>

<p align="center">
  <img src="docs/screenshots/01-shell.png" alt="imail screenshot — three reply tones for the same email" width="100%" />
</p>

<p align="center">
  <a href="https://pypi.org/project/imail-cli/"><img alt="PyPI" src="https://img.shields.io/pypi/v/imail-cli.svg"></a>
  <a href="https://pypi.org/project/imail-cli/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/imail-cli.svg"></a>
  <a href="https://github.com/jessecu2024/imail/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0%20or%20Commercial-blue.svg"></a>
  <a href="https://github.com/jessecu2024/imail/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/jessecu2024/imail/actions/workflows/ci.yml/badge.svg"></a>
</p>

> Inbox triage as a local app. Log in once to Gmail, Outlook, or 163 — then clear your unread
> emails by picking from three LLM-drafted replies per message. Powered by DeepSeek.

You wake up to 30 emails. Each one needs a yes / no / "let me get back to you." `imail` fetches
your unread inbox, asks the model for **three reply versions** per email (*positive · neutral · negative*),
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

## Why this exists

Email is mostly **acknowledging or deferring** — yes / no / "let me check
and get back to you." Each one of those takes 30 seconds of phrasing
even though the *decision* takes one. `imail` flips the workflow so
phrasing is one keystroke and you're left with the decision:

- **3 drafts in one round-trip.** DeepSeek sees the email once and
  returns *positive / neutral / negative* together — one API call,
  three angles, ~$0.0002. The model never sees a second prompt to
  "rephrase more polite" or "try again less eager".
- **Your mailbox stays where it is.** imail logs into your existing
  Gmail / Outlook / 163 via OAuth or IMAP. Saved drafts land in the
  same Drafts folder you already use — they show up on your phone too.
- **Local-first.** Email content stays on your machine. The only
  network hop is to DeepSeek for the draft itself. No imail server,
  no inbox copy uploaded anywhere.
- **One UI across providers.** Three reply tones, the same keyboard
  shortcuts (1 / 2 / 3 / S / Q), whether your work mail is Microsoft
  365 and your personal is Gmail or your school is 163.
- **Persists what you've handled.** Already-replied emails are tagged
  with a green "Replied" badge in the inbox and surfaced in Sent so
  you can re-read the reply you actually chose — no token waste on
  re-drafting.

## Features

- ✦ **Multi-provider** — Gmail (OAuth), and any IMAP mailbox: Outlook, 163, 126, QQ, Yahoo, iCloud, custom hosts.
- ✦ **Local web app** — `imail` boots a FastAPI server and pops your browser to `http://127.0.0.1:8765`.
- ✦ **Drafts only** — never sends mail on your behalf. You press *Send* yourself in your normal mail client.
- ✦ **Secrets in OS keyring** — IMAP app passwords go to macOS Keychain (or platform equivalent), not a plain text file.
- ✦ **DeepSeek by default** — cheap, fast, OpenAI-compatible. Point `IMAIL_BASE_URL` at any other OpenAI-compatible endpoint (Together, Groq, Moonshot, 302.AI, an Anthropic-proxy, etc.) and it just works.
- ✦ **Three drafts per email in a single API call** — fast, cheap, self-consistent. DeepSeek auto-caches the system prefix server-side.
- ✦ **Keyboard-first** — `1` / `2` / `3` to save a draft, `S` to skip, `Q` to end.

## Install

**The easy way** (any platform — macOS / Linux / Windows; just needs Python ≥ 3.11):

```bash
# Recommended: uv (fastest, no extra setup if you already have it).
uv tool install imail-cli

# Or pipx (if you don't have uv).
pipx install imail-cli
```

> Note: distribution name on PyPI is **`imail-cli`** (the bare `imail` slot
> was taken). The command you run after install is still **`imail`**.

Then export your DeepSeek API key and launch:

```bash
export DEEPSEEK_API_KEY=sk-...      # get one at https://platform.deepseek.com/api_keys
imail                                # opens http://127.0.0.1:8765
```

First run shows an "Add account" screen. Pick Gmail / Outlook / 163 / etc.,
sign in, and you're triaging.

**Try without installing** (uv only):

```bash
uvx --from imail-cli imail
```

**Or run via Docker** (no Python install needed):

```bash
docker run --rm -p 8765:8765 \
  -v ~/.config/imail:/root/.config/imail \
  -e DEEPSEEK_API_KEY=sk-... \
  ghcr.io/jessecu2024/imail:latest
# → open http://localhost:8765 in your browser
```

The mounted `~/.config/imail` keeps your accounts + saved replies between
container restarts.

> Releases are also attached as `.whl` and `.tar.gz` on
> [GitHub Releases](https://github.com/jessecu2024/imail/releases)
> if you'd rather download the artefact yourself. See
> [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Quick Start (from source)

```bash
# 1. Install deps
uv sync

# 2. Set your DeepSeek key
cp .env.example .env
# → put your DEEPSEEK_API_KEY in .env (get one at https://platform.deepseek.com/api_keys)

# 3. Launch the app
uv run imail
# → opens http://127.0.0.1:8765 in your browser
```

First run will show an "Add account" screen. Pick a provider:

- **Gmail** — drop your `credentials.json` (see [docs/gmail-setup.md](docs/gmail-setup.md))
  and the first triage triggers the OAuth consent screen.
- **Microsoft 365 / Outlook / 163 / 126 / QQ / Yahoo / iCloud** — sign in with your
  email + an **app password / 授权码** (see [docs/imap-setup.md](docs/imap-setup.md)).
- **Custom** — enter any IMAPS host + port.

After that, click your mailbox card → walk through unread emails → press 1/2/3 → drafts land in your Drafts folder.

> **Work or school account that blocks IMAP and won't let you register an Azure app?**
> (CityU and many other universities.) See
> [docs/forwarding-workflow.md](docs/forwarding-workflow.md) for the validated
> forwarding-to-personal fallback — adds your work mail to imail in 5 minutes
> of server-side setup, no code needed.

> **Where this project is heading + what would unblock more mailboxes:**
> [docs/vision-and-paths.md](docs/vision-and-paths.md) — the project's big
> picture, current capability matrix, and a ranked list of compromise paths
> (browser extension, bookmarklet, menu-bar app, Outlook add-in, etc.) for
> when direct API access is blocked.

## Configuration

All settings come from `.env` (see `.env.example`):

| Variable             | Default                       | Notes                                                                 |
|----------------------|-------------------------------|-----------------------------------------------------------------------|
| `DEEPSEEK_API_KEY`   | *(required)*                  | DeepSeek API key. `OPENAI_API_KEY` is a fallback for non-DeepSeek endpoints. |
| `IMAIL_BASE_URL`     | `https://api.deepseek.com`    | OpenAI-compatible endpoint                                            |
| `IMAIL_MODEL`        | `deepseek-chat`               | Or `deepseek-reasoner` for sharper, slower drafts                      |
| `USER_SIGNOFF`       | `Jie`                         | Name used in reply sign-offs                                          |
| `IMAIL_PORT`         | `8765`                        | Local server port                                                     |
| `IMAIL_HOST`         | `127.0.0.1`                   | Bind address (only listens on loopback by default)                    |
| `IMAIL_CONFIG_DIR`   | `~/.config/imail`             | Where accounts.json and OAuth tokens live                              |

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
src/imail/
  cli.py                  Launcher — boots uvicorn + opens browser
  config.py               .env loader
  server.py               FastAPI app — status, accounts, triage session
  accounts.py             Account manifest + keyring-backed secrets
  reply_generator.py      DeepSeek (OpenAI-compatible) call + JSON parser
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
- **OAuth tokens** are saved to `~/.config/imail/token-<account-id>.json` (mode 0600).
- Server listens on `127.0.0.1` by default. Don't move it to `0.0.0.0` on a shared machine.
- **Email content reaches DeepSeek's servers.** If you'd rather not share message bodies with any third party, point `IMAIL_BASE_URL` at a self-hosted Ollama / vLLM endpoint running an instruction model.

## License

Dual-licensed. Pick whichever fits your use:

- **AGPL-3.0-or-later** (default, free) — full text in [LICENSE](LICENSE).
  You're free to use, modify, fork, and self-host imail. The catch: if you
  modify the code and **either redistribute it or run it as a network
  service** (a SaaS, a hosted product, anything end users reach over a
  network), you must release your modifications under AGPL-3.0 too. This
  is the standard "no closed-source forks, no proprietary SaaS rebrand"
  guarantee — see the [GNU AGPL FAQ](https://www.gnu.org/licenses/why-affero-gpl.html)
  for the rationale.
- **Commercial license** — if AGPL's copyleft obligations don't fit your
  product (you want to ship a proprietary version, host imail inside a
  closed-source SaaS, or distribute imail as a library without exposing
  your own source), email **wzh4464@gmail.com** with what you'd like to
  do and we'll work out a commercial license.

> Versions ≤ 1.3.0 on PyPI were published under MIT. From v1.3.1 onward
> the license switches to AGPL-3.0-or-later (or commercial). If you
> installed `imail-cli==1.3.0` you remain on MIT terms for that copy.
