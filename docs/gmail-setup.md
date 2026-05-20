# Gmail OAuth Setup (One-time, ~5 minutes)

`imail` reads your inbox and drafts replies on your behalf. It needs an OAuth
**desktop-app** client. You only need to do this once.

## 1. Create a project

1. Open <https://console.cloud.google.com/>.
2. Top bar → project picker → **New Project**, name it `imail-my`.

## 2. Configure the OAuth consent screen

1. Top **search bar** → type `Auth Platform` → open it. (Older Cloud
   Console projects show this under sidebar → APIs & Services → OAuth
   consent screen; same place, just renamed.)
2. If you see a **Get started** button, click it — Google's new
   wizard splits the form across steps. Otherwise the old single
   page works the same way.
3. Fill in:
   - **App name**: `imail-my` (NOT `imail` — Google rejects names
     that look too similar to "Gmail" with "request failed because
     the app name does not meet Google's requirements").
   - **User support email**: your own Gmail.
   - **Audience / User type**: **External**.
   - **Contact information**: your email.
   - Agree to the User Data Policy → **Create**.
4. Open the **Audience** (or **Test users**) tab → **+ Add users** →
   add your own Gmail address.

> Leaving the app in *Testing* is fine — only the test users you added
> can sign in.

## 3. Enable the Gmail API

Top **search bar** → `Gmail API` → **Enable**.

> Enable the API *after* the consent screen exists — newer Cloud
> Console requires consent to be configured before it'll let you
> create credentials that hit the API.

## 4. Create OAuth client credentials

1. Sidebar → **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Name: `imail-cli`.
3. Click **Create**, then **Download JSON**.

## 5. Drop the file in place

```bash
mkdir -p ~/.config/imail
mv ~/Downloads/client_secret_*.json ~/.config/imail/credentials.json
```

(or set `GMAIL_CREDENTIALS_PATH` in your `.env` to point elsewhere)

## 6. First run

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
