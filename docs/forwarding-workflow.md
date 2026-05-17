# Locked-down work/school mailbox — forwarding workaround

If your work or school tenant blocks **both**:

- Basic-auth IMAP/POP (in Outlook web → Settings → Mail → Sync email, the
  "POP and IMAP" toggle is greyed out)
- User-level Azure app registration ("You don't have permission to create
  app registration" when you try in <https://portal.azure.com>)

…imail can't talk to your mailbox directly — same blockers Apple Mail,
Thunderbird, Spark and every other indie mail client hit on those tenants.
Validated workaround: **forward into a personal mailbox imail already speaks
to** (163 / Gmail / QQ / iCloud / etc.).

## Setup (5 minutes, server-side only — no code changes)

1. Log into your work mailbox web UI (e.g. <https://outlook.office.com>)
2. **Settings** → **Mail** → **Forwarding**
3. Enable forwarding; target = your personal account (e.g. `you@163.com`)
4. **Tick "Keep a copy of forwarded messages"** so the original mailbox
   keeps a permanent history
5. Save

That's it. Your work mail now arrives in the personal inbox within seconds.
imail (configured for the personal account) treats the forwarded copies as
normal mail and runs the full pipeline on them — prefetch, spam triage,
3-reply drafting, the lot.

## Trade-off

Replies sent from imail come from your **personal** address (the one imail
is actually authenticated against), **not** your work address.

| Use case | Acceptable? |
| --- | --- |
| Daily notifications, mailing lists, casual exchanges | ✅ |
| PI / supervisor / collaborator chats | ✅ |
| Formal IT / HR / admin emails | ⚠ Reads as personal email |
| Conference / journal correspondence | ❌ Reply via the work webmail directly |
| Replying to students from a teaching account | ⚠ May confuse them |

**Practical pattern**: use imail for triage + first-pass drafting. For replies
that must come from your work identity, open the kept copy in the work
webmail and send from there.

## To restore your work address as the reply identity

You'd need imail to authenticate against the work mailbox itself, which means
either:

1. Talking work IT into enabling IMAP for your account
2. Talking work IT into granting admin consent for an Azure-registered version
   of imail
3. Registering a multi-tenant app in a **personal** Microsoft account and
   asking imail to use Microsoft Graph + OAuth2 (this is buildable — see the
   notes around v1.1.0+ and ping if you want it implemented)

For most users, the forwarding workflow above is good enough indefinitely.

## Validated tenants

- **City University of Hong Kong** (Microsoft 365, IMAP blocked, user-level
  app registration blocked) — confirmed working 2026-05-17 via Outlook
  forwarding to 163.

If you set this up on another tenant, add it here.
