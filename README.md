# mail-triage

> Triage your inbox in seconds. Three LLM-drafted replies per email; pick one with a single keypress.

For people who wake up to dozens of emails and want to clear them in five seconds each.
`mail-triage` walks your unread Gmail inbox, asks Claude to draft **three reply versions**
(*positive · neutral · negative*) for every message, and lets you pick the one you like —
the chosen draft is saved straight to your Gmail Drafts folder.

You still hit "Send" yourself. The tool just removes the staring-at-a-blinking-cursor part.

## Features

- ✦ Fetches unread emails from your Gmail inbox (read + draft scopes; **never sends on its own**).
- ✦ Generates three tonally distinct replies in one Anthropic call.
- ✦ Prompt caching keeps per-email latency low.
- ✦ Single-key picker (`1`/`2`/`3`/`s`/`q`).
- ✦ Saves the chosen draft inside the original thread.
- ✦ Optionally archives processed emails (`--archive`).
- ✦ Drop-in `.env` config; no global state.

## Quick Start

```bash
# 1. Install (uv recommended)
uv sync

# 2. Set up secrets
cp .env.example .env
# → put your ANTHROPIC_API_KEY in .env
# → drop Gmail OAuth `credentials.json` into ~/.config/mail-triage/
#   (see docs/gmail-setup.md for how to get one — 5-minute Google Cloud Console flow)

# 3. Run
uv run mail-triage
```

First run will pop a browser window for Gmail OAuth consent; subsequent runs reuse the
cached token at `~/.config/mail-triage/token.json`.

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
  cli.py               Typer entrypoint — main loop
  config.py            env / secrets loader
  gmail_client.py      Gmail API wrapper (OAuth + fetch + draft)
  reply_generator.py   Anthropic call + JSON parser
  ui.py                Rich-based terminal renderer

tests/                 pytest suites
docs/gmail-setup.md    Google Cloud Console walk-through
```

## License

MIT — see [LICENSE](LICENSE).
