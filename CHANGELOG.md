# Changelog

All notable changes are listed here. The latest release is always also on
[GitHub Releases](https://github.com/jessecu2024/imail/releases) with the wheel
+ sdist attached.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [SemVer](https://semver.org/).

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

[1.3.2]: https://github.com/jessecu2024/imail/releases/tag/v1.3.2
[1.3.1]: https://github.com/jessecu2024/imail/releases/tag/v1.3.1
[1.3.0]: https://github.com/jessecu2024/imail/releases/tag/v1.3.0
[1.2.1]: https://github.com/jessecu2024/imail/releases/tag/v1.2.1
[1.2.0]: https://github.com/jessecu2024/imail/releases/tag/v1.2.0
[1.1.3]: https://github.com/jessecu2024/imail/releases/tag/v1.1.3
[1.1.2]: https://github.com/jessecu2024/imail/releases/tag/v1.1.2
[1.1.1]: https://github.com/jessecu2024/imail/releases/tag/v1.1.1
