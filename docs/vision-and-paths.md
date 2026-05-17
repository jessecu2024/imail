# imail — vision, current state, and paths forward

A snapshot of where this project stands as of 2026-05-17, after a week of
intense iteration. Written so future-Jie (or future-anyone) can re-enter
the project cold and pick up the right next step.

---

## 1. The original wish

> *"我每天一睁眼有好多email要回复，我期望做成每个email你都给我准备好了
> 2-3个回复，比如积极版本回复，消极版本回复，和中间状态回复，让我选择
> 这样我可以5秒一个邮件处理。"*

The seed: turn morning email from an interrupt-driven dread into a
**5-second-per-email batch task**. For every unread message in the inbox,
have three pre-drafted reply options (yes / maybe / no) already on screen
when the user looks at it. The user spends their attention on the
*decision*, not on the *prose*.

That seed grew over the week into a broader thesis:

> **imail is a personal mail-triage cockpit.** It should:
>
> 1. Detect spam and dispose of it without the user's attention
> 2. Surface only what actually needs a human reply
> 3. Pre-draft three tonally distinct responses for each of those
> 4. Make the click-to-send loop feel like flicking through Tinder, not
>    composing email
> 5. Keep the user in control of the Send button at all times

The user is a researcher who corresponds with PIs, students, journals,
admins, and family across two universities and several personal mailboxes.
The cockpit metaphor isn't aspirational — it's the only way to keep all
those streams flowing without losing a morning to inbox triage.

---

## 2. What works today — v1.2.1

A complete capability matrix as of the v1.2.1 tag. All features below have
been used end-to-end on a real mailbox.

### Mail backends — proven working

| Provider | Auth | Send | Drafts | Junk | Notes |
| --- | --- | --- | --- | --- | --- |
| **Gmail** | OAuth2 | ✅ | ✅ | ✅ | Full Microsoft-Graph-equivalent native support |
| **163 / 126 / Yeah** | IMAP + 授权码 | ✅ via SMTP | ✅ | ✅ | IMAP ID quirk handled |
| **QQ Mail** | IMAP + 授权码 | ✅ via SMTP | ✅ | ✅ | Same family as 163 |
| **Outlook (personal)** | IMAP + app password | ✅ via SMTP | ✅ | ✅ | smtp-mail.outlook.com |
| **Microsoft 365 (work/school)** | IMAP + app password | ✅ via SMTP | ✅ | ✅ | Only when the tenant allows it — see §3 |
| **Yahoo / iCloud / Custom IMAP** | IMAP + app password | ✅ via SMTP | ✅ | ✅ | Generic IMAPS + STARTTLS/SSL |

### Core UX

- **Auto-jump on boot**: open the app, you land on the latest unread email
  with replies already drafted. No welcome screen.
- **Three reply versions per email**, classified by tone (positive /
  neutral / negative). Single DeepSeek call also produces an `is_spam` flag.
- **Spam auto-move**: if the classifier flags spam, the message moves to
  Junk before the user ever sees it. No DeepSeek dollar wasted on garbage.
- **Editable preview + single Send button**: the chosen reply lands in a
  textarea with a big Send in the top-right. Edit if you want; if you don't,
  hit Send. No "edit mode" vs "send mode" distinction.
- **Save-as-draft fallback** stays as a quiet secondary option, plus
  "pick another tone" to re-roll.
- **Keyboard-driven**: 1/2/3 picks tone, Cmd+Enter sends, D saves draft,
  Esc backs out. Whole triage loop is finger-on-home-row.
- **Single-email and batch triage**: clicking any inbox email goes single;
  there's also a "Triage all unread" button for the morning blitz.

### Folders

- **Sidebar** with each account → Inbox / Drafts / Sent / Junk.
- **Drafts** opens directly into an editor; can update body, send, or delete.
- **Junk** lets you restore (false positive → back to Inbox) or permanently
  delete.
- **Search** in any folder, IMAP-side or Gmail-side (UTF-8, matches body + headers).

### Speed

- **Prefetch on folder open**: inbox warms full triage cache (body + 3
  replies + spam-move) in the background; Sent/Drafts/Junk warm the top 10
  bodies. Cache hit returns in 0 IMAP round-trips.
- **Per-account IMAP connection pool**: one long-lived IMAP socket per
  account, NOOP-probed and auto-reconnected. Avoids paying the 1.5-second
  163 login on every click.
- **localStorage stale-while-revalidate**: the message list from the last
  visit renders *instantly* when you click a folder; the fresh fetch runs
  in the background and swaps in.

### Quality / Ops

- 20 passing tests (`ruff check` / `ruff format --check` / `mypy strict`
  all green; GitHub Actions CI runs them on every push).
- DeepSeek key in `.env` (gitignored); IMAP passwords in macOS Keychain
  via `keyring`.
- Browser notifications + a 660 Hz beep for new mail (only after
  classifier confirms not-spam).
- Static assets served with `Cache-Control: no-store` so Cmd+R always
  picks up the latest JS/CSS during dev.

### The validated CityU workflow

CityU's alumni tenant (`my.cityu.edu.hk`) blocks **everything** imail
could use: basic-auth IMAP/POP, user-level Azure app registration, even
Microsoft's own Graph Explorer (Mail.Read = admin-consent-only). The
workaround:

```
CityU mailbox (Outlook web)
  └─ Auto-forward (server-side, no API access needed)
       └─ 163 inbox
            └─ imail (via 163 IMAP) → full triage pipeline
```

Caveat: replies from imail go out as `@163.com`, not `@cityu.edu.hk`.
That's fine for daily triage and personal correspondence, not for formal
correspondence — those get composed in Outlook web directly.

See [forwarding-workflow.md](forwarding-workflow.md) for the setup steps.

---

## 3. The wall — tenants that block all third-party access

Some Microsoft 365 tenants (universities especially) configure
**all three** of:

1. Basic-auth IMAP/POP disabled
2. User-level Azure app registration disabled
3. Mail.* OAuth scopes require admin consent (even for pre-trusted
   Microsoft apps like Graph Explorer)

On those tenants there is **no third-party-client path** to the mailbox.
This isn't an imail limitation — Apple Mail, Thunderbird, Outlook for
Mac, Spark, and Mimestream all hit the exact same wall. The only ways
through are:

- Getting tenant IT to grant admin consent for the specific app
- The forwarding workaround in §2
- Acting from *inside* a trusted client (see paths §4.4 and §4.5 below)

This wall was definitively encountered for CityU's alumni tenant on
2026-05-17. The staff tenant (`cityu.edu.hk`, separate) was not tested
but is presumed to have the same posture.

---

## 4. Paths forward — when direct API access is blocked

Ordered by effort/reward ratio. Each path is a different compromise.

### 4.1 Browser extension (Chrome / Firefox / Edge)

Run imail's logic as a webextension that injects UI into Gmail / Outlook /
163 webmail tabs. The extension reads the open email from the page DOM,
calls DeepSeek, and offers 3 reply buttons inline.

- **Effort**: 5-10 hours (significant rewrite — DOM injection per
  provider, message-passing between content script and background, store
  state in extension's storage API)
- **Bypasses**: All tenant restrictions, all OAuth requirements. The user
  is already authenticated in their browser; the extension just reads
  what's on screen.
- **Loses**: Batch triage (extension only acts on the currently-open
  email). Background prefetch is awkward (can't open hidden tabs without
  user noticing). Cross-folder search becomes a non-starter.
- **Best for**: Users on locked-down tenants who can't use anything else.

### 4.2 Bookmarklet (zero-install)

A JavaScript bookmark the user clicks while reading an email in webmail.
The bookmarklet scrapes the rendered email body and POSTs it to imail's
local server (`localhost:8765`). imail returns the 3 replies; user picks
one and copies it back.

- **Effort**: 1-2 hours
- **Bypasses**: All tenant restrictions
- **Loses**: Auto-send. The user manually pastes the chosen reply into
  the webmail's reply box and hits Send themselves.
- **Best for**: Quick prototyping path to validate the extension approach
  without the per-browser packaging overhead.

### 4.3 Copy-paste assistant — macOS menu bar app

A small native app that sits in the menu bar. Global hotkey (e.g.,
Cmd+Shift+R) grabs the currently-selected text from any app (using
NSPasteboard), runs DeepSeek, shows 3 replies in a popover, copies the
chosen one to clipboard. User pastes into the mail client.

- **Effort**: 3-5 hours (Tauri / SwiftUI / pywebview wrapping the
  existing FastAPI backend with a menu-bar-app shell)
- **Bypasses**: Works in any mail client (Outlook desktop, Apple Mail,
  webmail, IMAP-only clients) because it operates on selected text.
- **Loses**: List view, prefetch, batch triage, automatic spam handling
  — degraded to "ad-hoc assistant for the email I'm currently looking
  at". And no native Inbox concept; this is purely "draft a reply to
  this thing I've selected".
- **Best for**: A tool that works across any mailbox even when its API
  is unreachable.

### 4.4 Outlook Add-in (Office Add-in framework)

Microsoft has an Office Add-in API: a manifest-driven plugin that runs
*inside Outlook desktop and Outlook web*, with access to the current
email via JavaScript. Add-ins authenticate as Outlook itself, so they
bypass tenant restrictions on third-party Mail.* scopes.

- **Effort**: 8-15 hours (manifest XML, sandboxed JS inside Outlook's
  iframe, certificate-signed for sideloading, AppSource submission for
  distribution — non-trivial dev story)
- **Bypasses**: Tenant blocks on third-party clients, because the
  add-in *is* Outlook.
- **Loses**: Apple Mail / 163 / Gmail support (this is Outlook-only). You
  end up maintaining a second codebase for "outside Outlook" anyway.
- **Best for**: A user who lives in Outlook desktop and wants the
  triage cockpit feel inside it without any external app.

### 4.5 Server-side forwarding-bot

Run a small hosted service. User forwards individual emails (or sets
auto-forward) to `triage@imail.dev` (or wherever). The bot calls
DeepSeek, generates 3 replies, sends them back to the user as a reply
to the forwarded email with the three options inline. User replies with
their pick; bot sends to the original sender.

- **Effort**: 4-8 hours code + ongoing hosting / domain / abuse handling
- **Bypasses**: All tenant restrictions (forwarding works on most
  mailboxes regardless of API access). User can be on any device,
  including mobile, with no app installed.
- **Loses**: Latency (multiple email round-trips per triage). Tone is
  awkward — From: addresses get rewritten unless you handle DKIM/SPF
  carefully. Becomes a real service, not just "an app I run locally."
- **Best for**: Scaling beyond one user, or for the mobile-only case.

### 4.6 IT cooperation

Ask CityU IT (or whichever tenant) to grant admin consent for a specific
multi-tenant Azure app registration that imail ships. Once admin
consents, every user in that tenant can self-consent to that app for the
named scopes.

- **Effort**: Variable. Could be 1 email reply to a friendly IT person,
  or 6 months of a security review process.
- **Bypasses**: Nothing technically — it just unblocks the existing
  Microsoft Graph path.
- **Loses**: The political-capital cost of asking. The bureaucratic time.
- **Best for**: Users at smaller institutions, or where the user has IT
  rapport.

### 4.7 Multi-imail: own paid Microsoft 365 mailbox

Buy a personal Microsoft 365 subscription (≈$7/mo) for a single mailbox
the user fully controls. Forward CityU to that mailbox. Use *that*
mailbox as the imail account — its Graph API is unblocked because the
user is the tenant admin.

- **Effort**: A subscription click. Zero code.
- **Bypasses**: Tenant-level lockdowns by simply not living in that
  tenant.
- **Loses**: Money. Outbound identity is still not the CityU address.
- **Best for**: A user who is fine paying for a personal Microsoft
  mailbox to use as the consolidation point.

### 4.8 Local-only LLM (orthogonal — privacy not access)

Replace DeepSeek with Ollama running a local model (Llama 3.1, Qwen
3, etc.). The mailbox content never leaves the machine.

- **Effort**: 1-2 hours (config knob to point reply_generator at
  `localhost:11434/v1/chat/completions`)
- **Bypasses**: Nothing access-wise. This is about *privacy*, not
  tenant access. If the mailbox is reachable, this is a strict
  improvement.
- **Loses**: Quality (local models are noticeably weaker than DeepSeek
  V3) and speed (depends on machine).
- **Best for**: A user who needs to keep email content off cloud LLMs
  for compliance/privacy reasons. Could be paired with any of §4.1-4.7.

---

## 5. Recommended next move (when this project resumes)

**For Jie's actual situation as of 2026-05-17**:

The forwarding workflow is working. The CityU IT wall is real and won't
move. None of paths §4.1-4.8 are urgent — the current setup processes
real CityU mail through 163 fine.

When this project resumes, the order of priority should be:

1. **Confirm the staff `xujie.cs@cityu.edu.hk` tenant has the same
   posture** (one Graph Explorer test). If it does, write off direct
   CityU forever and skip to step 3.
2. *Only if* the staff tenant allows user-level Mail.Read consent: build
   the Microsoft Graph provider in imail. Similar shape to the existing
   Gmail provider; estimated 2-3 hours.
3. *Otherwise*: build path §4.2 (bookmarklet) as a 2-hour spike to
   validate whether the "draft from selected text" workflow has legs.
   It's the cheapest way to see whether imail-as-an-assistant is as
   useful as imail-as-a-mail-client.
4. If the bookmarklet is loved: invest in path §4.3 (menu bar app) for
   the better native UX.
5. Path §4.1 (browser extension) is the right long-term form for
   "imail as an everywhere overlay", but it's a bigger commitment and
   should wait until the lighter-weight prototypes confirm demand.

The current local app + 163 forwarding combo is sustainable for daily
use indefinitely. Don't break it for the sake of the next milestone —
add new paths alongside.

---

## 6. References

- [README.md](../README.md) — quick-start
- [forwarding-workflow.md](forwarding-workflow.md) — CityU recipe
- [gmail-setup.md](gmail-setup.md) — Google Cloud Console walk-through
- [imap-setup.md](imap-setup.md) — provider-specific app-password steps
- GitHub: <https://github.com/jessecu2024/imail>
- Latest stable: <https://github.com/jessecu2024/imail/releases/tag/v1.2.1>
