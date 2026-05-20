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

## 3. Enable the Gmail API + create OAuth client credentials

> Enable the API *after* the consent screen exists — newer Cloud
> Console requires consent to be configured before it'll let you
> create credentials that hit the API.

1. Top **search bar** → `Gmail API` → **Enable**.
2. Sidebar → **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**. Name: `imail-cli`.
4. Click **Create**, then **Download JSON**.

## 4. Add the account in imail

1. Run `imail` (or open `http://127.0.0.1:8765` if it's already running)
   → sidebar **+ Add account** → **Gmail**.
2. **Path to credentials.json**: paste the absolute path to the JSON
   file you just downloaded — usually
   `/Users/<you>/Downloads/client_secret_<long-string>.json`. (Drag
   the file into the Terminal to copy its path, or use Finder →
   right-click → **Copy as Pathname**.)
3. Click **Add Gmail account**.
4. A browser tab opens; sign in with the Gmail account you added as a
   test user and grant the requested scopes. Token is cached to
   `~/.config/imail/token-<account-id>.json`; subsequent runs are silent.

That's it — you should be in the inbox triage view.

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
