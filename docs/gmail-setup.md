# Gmail OAuth Setup (One-time, ~5 minutes)

`imail` reads your inbox and drafts replies on your behalf. It needs an OAuth
**desktop-app** client. You only need to do this once.

## 1. Enable the Gmail API

1. Open <https://console.cloud.google.com/>.
2. Create a new project (top bar → project picker → **New Project**), e.g. `imail`.
3. Search bar → **Gmail API** → **Enable**.

## 2. Configure the OAuth consent screen

1. Left sidebar → **APIs & Services → OAuth consent screen**.
2. User type: **External** → Create.
3. App name: `imail`. Support email: your own.
4. Scopes: skip (we request them at runtime).
5. **Test users**: add your own Gmail address.

> Leaving the app in *Testing* status is fine — only your test users can use it.

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

| Scope                                          | Why                       |
| ---------------------------------------------- | ------------------------- |
| `gmail.readonly`                               | Fetch unread messages     |
| `gmail.modify`                                 | Mark-as-read / archive    |
| `gmail.compose`                                | Create drafts             |

**No `gmail.send` is requested.** The tool never sends mail; you always press Send manually in Gmail.
