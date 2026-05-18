# Recording the 30-second demo

A short GIF or MP4 at the top of the README converts visitors into
users far better than a static screenshot. Aim for **30 seconds, no
voice-over, no cuts** — let the keyboard shortcuts speak for themselves.

## Tools (macOS)

[**Kap**](https://getkap.co/) — free, open source, exports straight to
optimised GIF or MP4. Better than QuickTime because it can do a small
crop region and not 4K of your whole monitor.

```bash
brew install --cask kap
```

Alternatives if you're not on macOS:
- **OBS Studio** (cross-platform, more knobs than you need)
- **Peek** (Linux, GIF-focused)
- **ScreenToGif** (Windows)

## Storyboard (30 s, 7 beats)

| t (s) | What's on screen | Why this beat |
|------:|------------------|---------------|
| 0–2   | imail icon + wordmark, blank page | Brand recognition |
| 2–6   | An inbox listing — three rows visible, one with the green Replied badge | Show that imail tracks state |
| 6–10  | Cursor clicks an unread row → page transitions to triage view | "Click a thing, see a thing" |
| 10–18 | The triage view's email card + three reply cards (POSITIVE/NEUTRAL/NEGATIVE). Reader has time to scan the drafts. | This is the product |
| 18–22 | Keyboard "2" appears on screen (or animated key cap), reply card flips to confirm view, send-button visible | "Two keystrokes total" |
| 22–26 | Bounce back to inbox — the row now shows the Replied badge | Closes the loop |
| 26–30 | Optional: text overlay "uv tool install imail-cli" | Where to get it |

A **15-second** version dropping beats 0–2 and 26–30 also works for X /
Hacker News header thumbnails.

## Settings that matter for embedded GIFs

| Setting        | Value                | Why                          |
|----------------|----------------------|------------------------------|
| Resolution     | 1280×800 (or 1100×700 if cropped to app) | Renders crisp on Retina without bloating the file |
| Frame rate     | 24 fps               | Smooth enough for cursor motion; ~50% smaller than 30 fps |
| Loop           | yes                  | GitHub auto-loops; viewers see the cycle |
| Format         | MP4 for the README, GIF as a fallback | MP4 is 10–20× smaller. GitHub renders MP4 inline since 2018. |
| Max size       | <3 MB                | Otherwise README load is slow on mobile |

In Kap: trim to 30 s, export → MP4 → "Web Optimized". Should land
around 1.5–2.5 MB for the storyboard above.

## Capturing demo data (no real contacts on screen)

Same data set the screenshots use — see
[`scripts/take_screenshots.py`](../scripts/take_screenshots.py). Run
imail with the route-mock active (or temporarily seed a test account
and inbox), record, then revert.

A truly canned demo is on the roadmap (a `--demo` flag that loads a
fake mailbox from in-memory). For now, recording against the mocked
playwright session is the cleanest path:

```bash
# Window 1: imail (real one for static asset serving)
uv run imail

# Window 2: a separate Chromium with the mocked routes — record this one
uvx --with playwright python scripts/take_screenshots.py --interactive
```

(`--interactive` is a flag the script doesn't have yet; for now run
the mock setup snippet manually before recording.)

## Where to embed it

Once recorded, drop the file at `docs/screenshots/demo.mp4` (or `.gif`)
and update the README's hero `<img>` to a `<video>` or animated GIF
reference. GitHub renders `<video autoplay loop muted playsinline>`
correctly.
