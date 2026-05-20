# Gmail OAuth Setup (One-time, ~5 minutes)

`imail` reads your inbox and drafts replies on your behalf. It needs an OAuth
**desktop-app** client. You only need to do this once.

## 1. Enable the Gmail API

1. Open <https://console.cloud.google.com/>.
2. Create a new project (top bar → project picker → **New Project**), e.g. `imail`.
3. Search bar → **Gmail API** → **Enable**.

## 2. Configure the OAuth consent screen

> ⚠️ Google reworked this UI in late 2024. The section may show up as
> **"OAuth consent screen"** (older projects) or **"Google Auth
> Platform"** / **"Auth Platform"** (newer projects). The old
> "**User type: Internal / External**" radio is now hidden inside a
> multi-step wizard and renamed **"Audience"**. Pick the path that
> matches what you see.

### New UI (2025+) — "Get started" wizard

1. Sidebar → **APIs & Services → Auth Platform**. If the page shows
   a blue **Get started** button, you're on the new flow.
2. Click **Get started** and walk through the 4 steps:
   - **App information** — App name `imail`, user support email = your own.
   - **Audience** — pick **External**. (This is where the old User-type
     radio went.)
   - **Contact information** — your email.
   - **Finish** — agree to the User Data Policy → **Create**.
3. After the wizard, go to the **Audience** tab → **Test users** →
   **+ Add users** → add your own Gmail.

### Old UI — single page

1. Sidebar → **APIs & Services → OAuth consent screen**.
2. User type: **External** → **Create**.
3. App name: `imail`. Support email: your own.
4. Scopes: skip (we request them at runtime).
5. **Test users**: add your own Gmail.

> Leaving the app in *Testing* status is fine in both UIs — only the
> test users you added can sign in.

## 3. Create OAuth client credentials

1. Sidebar → **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Name: `imail-cli`.
3. Click **Create**, then **Download JSON**.

## 4. Drop the file in place

```bash
mkdir -p ~/.config/imail
mv ~/Downloads/client_secret_*.json ~/.config/imail/credentials.json
```

(or set `GMAIL_CREDENTIALS_PATH` in your `.env` to point elsewhere)

## 5. First run

```bash
uv run imail
```

A browser tab will open; sign in with the Gmail account you added as a test user
and grant the requested scopes. A token is cached to
`~/.config/imail/token.json` — subsequent runs are silent.

## Scopes

| Scope                                          | Why                                                   |
| ---------------------------------------------- | ----------------------------------------------------- |
| `gmail.readonly`                               | Fetch unread messages                                 |
| `gmail.modify`                                 | Mark-as-read / archive                                |
| `gmail.compose`                                | Save the chosen reply as a draft                      |
| `gmail.send`                                   | One-keystroke send (⌘↵) from the triage view           |

If you'd rather have `imail` only ever save drafts — so you have to
open Gmail and press Send yourself — drop the
`https://www.googleapis.com/auth/gmail.send` line from `SCOPES` in
`src/imail/providers/gmail.py`, then revoke the stored OAuth token
at <https://myaccount.google.com/permissions> so the next run prompts
for fresh consent without the send scope.
