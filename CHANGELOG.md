# Changelog

All notable changes are listed here. The latest release is always also on
[GitHub Releases](https://github.com/jessecu2024/imail/releases) with the wheel
+ sdist attached.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [SemVer](https://semver.org/).

---

## [1.4.3] — 2026-05-21

Spam handling visibility + Junk folder bulk operations.

### Added

- **Spam classifier now gives one-sentence reasons.** The DeepSeek
  prompt asks for a concise `spam_reason` whenever a message is
  classified as spam (e.g. `"Generic marketing blast from Mailchimp"`,
  `"Phishing — sender impersonates HSBC but reply-to is gmail.com"`,
  `"Automated GitHub deploy notification, no reply expected"`). The
  reason is persisted in a per-account sidecar at
  `~/.config/imail/spam-reasons-<account-id>.json` and surfaced as a
  single-line caption under each row in the Junk folder. Turns the
  Junk folder from a black box into something the user can audit, and
  makes false positives easy to spot at a glance. Pre-1.4.3 junk rows
  have no reason recorded — those just render without the caption,
  not as an error.
- **Junk folder bulk operations.** A leading checkbox now appears on
  every row in Junk; ticking ≥ 1 reveals an action bar with
  *Restore N to Inbox* and *Delete N* buttons. The folder toolbar
  also gains a one-click **Empty Junk** that wipes everything
  currently visible. Both go through new endpoints —
  `POST /api/folders/<acct>/junk/bulk` (`action: restore|delete`,
  `message_ids: [...]`) and `POST /api/folders/<acct>/junk/empty` —
  which serialise the IMAP commands on the pool's per-account lock,
  drop the corresponding spam-reason sidecar entries, and return
  per-id outcomes so the UI can surface partial failures instead of
  claiming success for the whole batch.

### Notes

- Restoring a junk message from Inbox (single or bulk) now also
  drops its persisted `spam_reason` — the user just told us we were
  wrong, no point keeping the rationale around.

## [1.4.2] — 2026-05-20

A small but felt UX patch — when new mail arrives, the three pre-drafted
replies are now usually ready by the time the user gets around to clicking.

### Changed

- **Inbox poll dropped from 30s → 10s.** Every poll triggers the
  server-side `_warm_inbox_cache` background task for any unhandled
  inbox ids, so the window between *mail arrives at the IMAP server*
  and *DeepSeek has drafted three replies for it* used to be up to 33
  seconds in the worst case (30s polling delay + 3s for the
  DeepSeek call). It's now closer to 13s worst case. IMAP polls are
  cheap; the extra requests don't measurably affect any provider's
  rate limits.
- **Prefetch generates three drafts in parallel.** The background
  prefetch loop used to chew through unread emails one at a time —
  each iteration cost ~3 seconds of waiting for DeepSeek. With 50
  unread emails on first boot, that took ~150 seconds, during which
  most of the inbox was still a cache miss for the user. The pool
  now runs three DeepSeek calls concurrently (IMAP fetches stay
  serial — one shared connection — but the slow part runs in
  parallel), dropping the same 50-email batch to ~55 seconds. Each
  result is stored to the on-disk reply cache the instant its
  DeepSeek call returns, instead of waiting for the batch to
  complete, so emails 1–3 are warm at t≈3s instead of "anywhere
  between t=3s and t=5s depending on submission order."

## [1.4.1] — 2026-05-20

A round of fixes contributed by the first external user
([@wzh4464](https://github.com/wzh4464)) — three real bugs, one UX
upgrade.

### Fixed

- **`~/.config/imail/.env` is now actually loaded.** The user guide
  documented dropping `DEEPSEEK_API_KEY` into `~/.config/imail/.env`
  but the code's bare `load_dotenv()` walks up from
  `src/imail/config.py`, not from the documented path. Followers of
  the guide ended up with `llm_configured: false` after every
  restart. `config.py` now resolves `.env` from CWD then from the
  config dir (honouring `IMAIL_CONFIG_DIR`); CWD wins on conflict.
- **Salutation no longer addresses brands as people.** Replies to
  institutional senders (`Japan Visa Service Desk <…>`, `HSBC <…>`,
  `sourcery-ai[bot]`, bare `no-reply@…`) opened with `Dear Japan,`
  / `Dear HSBC,` / `Dear There,`. The new `build_salutation`
  detects institutional senders by local-part / display-name
  keywords, derives a brand from the email domain (with TLD and
  sub-domain stripping), and opens `Dear <Brand> Team,`. Acronyms
  preserved (`HSBC` stays uppercase); display names with `Team`,
  `Hong Kong`, `Limited` suffixes are normalised.
- **Gmail OAuth scope docs match reality.** The README,
  `docs/gmail-setup.md`, and the Settings → Privacy panel all
  claimed "no `gmail.send` scope is requested." The code actually
  requests four scopes including `gmail.send` (used by triage's
  `⌘↵ Send` and the new compose view's Send button). Every site
  now lists the four scopes explicitly and explains how to drop
  `gmail.send` if the user prefers draft-only.

### Added

- **The reply model now reads quoted conversation history.** A new
  `CONVERSATION HISTORY` section in the system prompt tells the
  model to look at quoted earlier exchanges (`>`, `From:`, `Sent:`,
  `On <date> … wrote:`) and avoid re-promising actions the user
  already completed in a prior reply, re-asking for info already
  supplied, or inventing numbers / dates / names. Same JSON output
  shape — purely a prompt-content upgrade. Cost impact: ~700 extra
  cached input tokens, well under \$0.0001 per email.

---

## [1.4.0] — 2026-05-20

A big visual + UX overhaul. Same install command (`uv tool install
imail-cli` / `brew install jessecu2024/tap/imail` / `docker pull
ghcr.io/jessecu2024/imail`), drop-in upgrade — but most surfaces of
the app are unrecognisable from 1.3.x.

### Added

- **Light theme** (default), Gmail-adjacent palette. Replaces the
  dark-navy 1.3.x look.
- **macOS-Mail-style logo** — sky-blue gradient tile, white
  envelope, centred red "i" dot. Used as the favicon, the brand
  glyph in the sidebar, and the README hero.
- **Chinese (简体中文) UI option.** Settings → Language toggles
  English ↔ 中文; the choice persists in `localStorage`. ~80 string
  keys translated, covering sidebar / triage / Settings / shortcuts
  / privacy / about. Reply *content* drafted by DeepSeek stays
  English regardless (a deliberate product choice).
- **Settings page** with sticky anchored navigation: Language /
  Accounts / Replies / Keyboard shortcuts / Privacy & security /
  Local data / About. Accounts card is the single source of truth
  for "remove account" — the destructive button is no longer in the
  sidebar.
- **Reply / Reply all / Forward.** Toolbar buttons on both the
  message-detail and triage views open a compose form pre-filled
  for the chosen mode (with `>`-quoted original for Forward).
  Send goes via `/api/compose/send` → provider's new
  `send_compose(to, subject, body)` (SMTP for IMAP, Gmail API for
  Gmail). After sending, the user lands in Sent with the new
  message visible at the top.
- **Flagged virtual folder.** Cross-folder view of every message
  with `\Flagged` / Gmail STARRED set. Sidebar entry between
  Inbox and Drafts. Optimistic local cache so a freshly-flagged
  email shows instantly; a 30-second per-account server-side cache
  makes back-to-back navigations to Flagged effectively free.
  Local `:` synthetic Sent rows can also be flagged — the bit is
  persisted in the reply store.
- **Per-row flag (red flag) and delete (trash) buttons** revealed
  on hover, plus a Reply / Reply all / Forward / Flag / Delete
  toolbar at the top of every open message.
- **Sender avatars** in list rows (Gmail-style coloured initial
  circles, deterministic per sender).
- **Folder icons are SVG** (inbox / drafts / sent / junk / flagged)
  instead of emoji — consistent across OSes.
- **Sender prefix `→`** on Sent listing rows (and Flagged rows
  with source_kind=sent) so the reader can tell a sent message
  from an incoming one at a glance.
- **In-reply-to card** below a local `:` Sent row's reply text —
  shows the original incoming email so the user can remember what
  they replied to.
- **Read-on-open.** Clicking an inbox email immediately marks it
  read (server-side IMAP \Seen + frontend optimistic update), so
  the unread red dot and the sidebar count badge drop the moment
  the user opens it.
- **Red unread indicator dot** before unread-and-not-yet-replied
  rows. Sidebar count badge also red, matching.
- **Newest-first ordering** for IMAP listings (UID-descending sort
  applied after envelope fetch — IMAP servers were returning
  sequence-ascending and showing oldest first).
- **Setup banner** at the top of the page when `DEEPSEEK_API_KEY`
  is missing — three concrete setup steps with a free-signup link.
- **GitHub issue templates** (bug / feature request, modern YAML
  form schema).

### Changed

- All triage operations route through the per-account IMAP
  connection pool now; sessions no longer hold a private provider.
  Click-to-open of a cached pending email dropped from ~3-12 s to
  ~30 ms; re-open of an already-replied email dropped from ~3 s
  to ~25 ms.
- Sidebar layout cleaned up: account header, folder list with
  unread count, "+ Add account" CTA at the bottom.
- README repaginated with emoji-anchored H2s and a four-column
  install matrix (uv / pipx / Homebrew / Docker).
- Distribution channels documented in About: PyPI · imail-cli,
  GHCR Docker, Homebrew tap.

### Fixed

- The unread red dot used to keep reappearing on the top inbox
  row after a 30-second poll because the cached-pending path
  never called `mark_read` — fixed by always firing mark_read on
  triage_single, cache hit or not.
- Sidebar inbox count badge counted IMAP-unread rows the user had
  already replied to; now only counts `unread && !replied`.
- The Flagged folder used to be empty for messages flagged in Sent
  because the scan only looked at Inbox; now scans inbox + sent +
  junk (drafts intentionally skipped).
- Operations on rows surfaced in the Flagged virtual folder used
  to route to inbox regardless of the row's actual source; now
  routes to `source_kind` so delete / flag / open hit the correct
  underlying folder.
- 163's `已发送邮件` / `已删除邮件` empty-body fetches now produce
  a clear "message no longer exists, refresh the folder" error
  with auto-refresh on the frontend, instead of a confusing
  "empty body" message.

### Notes

- Reply all currently behaves identically to Reply (no Cc parsing
  yet). The button is visible because the toolbar's shape should
  match what users expect from Gmail / Outlook; Cc support is on
  the roadmap.
- The cross-folder Flagged scan takes 5-6 s cold against 163 —
  unavoidable given the four IMAP SELECT + envelope-fetch
  round-trips. The optimistic-cache + 30 s server cache mask this
  in practice.

---

## [1.3.2] — 2026-05-19

### Fixed

- README images now use absolute `raw.githubusercontent.com` URLs so
  they render on the PyPI project page. The previous relative paths
  (`src/imail/static/icon.svg`, `docs/screenshots/01-shell.png`)
  only worked on GitHub, which resolves relative links against the
  repo root; PyPI renders the README standalone and broke both
  images. No code changes — version bump only to force PyPI to
  re-fetch the README.

---

## [1.3.1] — 2026-05-19

### Changed

- **License switched to AGPL-3.0-or-later** (was MIT). The project is
  also available under a commercial license — email
  `wzh4464@gmail.com` if AGPL's copyleft obligations don't fit your
  product. Existing 1.3.0 installs retain their MIT grant; the new
  terms apply from 1.3.1 onward. See [LICENSE](LICENSE) for the full
  AGPL text and [README "License"](README.md#license) for the dual
  arrangement.
- Repository is now public on GitHub so PyPI's homepage link
  resolves, brew audit passes, and external contributors can file
  issues / PRs.

---

## [1.3.0] — 2026-05-18

First release on PyPI as `imail-cli`. Bundles everything since v1.2.1 and
adds the install-and-distribute pipeline.

### Added

- **Persistent reply store** — DeepSeek-drafted replies survive across
  process restarts, stored under `~/.config/imail/replies-<account-id>.json`
  (mode 0600, atomic writes). No more re-spending tokens after `imail`
  closes and reopens.
- **"Replied" tagging in the inbox** — emails the user has already
  handled get a green ✓ badge instead of disappearing, and clicking
  them re-shows the saved reply alongside the original body (no
  DeepSeek call).
- **Local Sent mirror** — every reply the user picks (`1` / `2` / `3`)
  surfaces in the Sent folder as a `local:<mid>` synthetic row,
  rendered instantly without an IMAP round-trip.
- **Delete that syncs to other devices** — `STORE +Deleted` + `EXPUNGE`
  on the IMAP server, so a delete in `imail` also removes the email
  from 163 webmail / phone / any other IMAP client logged into the
  mailbox. A small × button anchored to the email card and an
  on-hover × in each list row both trigger the same path.
- **English-only reply format** — every drafted reply opens with
  `Dear <FirstName>,` and closes with `Best regards,\n<USER_SIGNOFF>`,
  regardless of the incoming email's language. Chinese names that
  can't be romanised cleanly fall back to the email local-part.
- **Logo + brand** — square SVG mark used as favicon, top-bar logo,
  and README hero. A wordmark variant for inline use.
- **First-run setup banner** — a loud red bar with three concrete
  setup steps appears when `DEEPSEEK_API_KEY` is missing, replacing
  the easy-to-miss small pill in the corner.
- **GitHub issue templates** for bug reports and feature requests
  (modern YAML form schema).
- **PyPI release pipeline** — `.github/workflows/release.yml` builds
  sdist + wheel and publishes to PyPI via Trusted Publishing (OIDC,
  no API token) on every `v*` tag push, then attaches the artefacts
  to a GitHub release.

### Changed

- All user-facing strings are now English (`Replied` badge, delete
  prompts, banner copy). Internal data references like the Chinese
  IMAP folder names returned by 163 (`已发送邮件` / `已删除邮件`) are
  kept as data, not text.
- IMAP `fetch_message` distinguishes "message no longer exists on the
  server" from "fetch returned an empty body". The former message
  ID's missing case is detected via UID SEARCH and produces a
  dedicated error (`Refresh the folder`). The frontend reacts to that
  error by dropping the stale row from its localStorage cache and
  refreshing automatically.
- Distribution name on PyPI: `imail-cli` (the bare `imail` slot was
  already taken). Import name and CLI command both stay `imail`.

### Fixed

- 163's quirky `已发送` / `已删除` folders no longer fail with a
  confusing "empty body" message — empty payloads in the standard
  tuple shape now fall through to a second-pass parser that accepts
  a bare RFC822 chunk, plus an RFC822 fallback fetch.

---

## [1.2.1] — 2026-05-17 (validated forwarding workflow)

### Added

- Documented the validated CityU-via-163 forwarding workflow in
  `docs/forwarding-workflow.md` — a 5-minute setup that lets imail
  process locked-down work mailboxes (CityU and similar tenants that
  refuse user-level Microsoft Graph consent).
- `docs/vision-and-paths.md` — full capability matrix + 8 ranked
  paths forward (browser extension, bookmarklet, menu-bar app, etc.)
  for tenants where direct API access stays blocked.

---

## [1.2.0] — 2026-05-16

### Added

- Microsoft 365 / Office 365 preset (separate from personal Outlook;
  uses `smtp.office365.com` instead of the consumer SMTP host).

---

## [1.1.3] — 2026-05-15

### Changed

- Prefetch message bodies for Sent / Drafts / Junk on folder open so
  the first click on any message is instant instead of paying the
  IMAP round-trip cost.

---

## [1.1.2] — earlier

### Fixed

- Tolerant Sent-folder fetch; concrete date/time format across views.

---

## [1.1.1] — earlier

### Added

- Pooled IMAP connections so the second-onward folder/message click
  is instant (163/QQ logins take 1-2 seconds; reusing the connection
  is essential for the UI to feel snappy).

---

## [1.1.0] and earlier

History before semver discipline. See `git log` for individual commits.

[1.4.1]: https://github.com/jessecu2024/imail/releases/tag/v1.4.1
[1.4.0]: https://github.com/jessecu2024/imail/releases/tag/v1.4.0
[1.3.2]: https://github.com/jessecu2024/imail/releases/tag/v1.3.2
[1.3.1]: https://github.com/jessecu2024/imail/releases/tag/v1.3.1
[1.3.0]: https://github.com/jessecu2024/imail/releases/tag/v1.3.0
[1.2.1]: https://github.com/jessecu2024/imail/releases/tag/v1.2.1
[1.2.0]: https://github.com/jessecu2024/imail/releases/tag/v1.2.0
[1.1.3]: https://github.com/jessecu2024/imail/releases/tag/v1.1.3
[1.1.2]: https://github.com/jessecu2024/imail/releases/tag/v1.1.2
[1.1.1]: https://github.com/jessecu2024/imail/releases/tag/v1.1.1
