# IMAP / App Password Setup

For every IMAP provider, you sign in with your **email** and an **app password / 授权码** —
*not* your normal account password. Most providers require this for security (2FA accounts cannot use the regular password over IMAP).

> imail never asks for your real password. Generate a dedicated app password,
> paste it once, and it's stored in your OS keyring.

---

## Outlook / Office 365

1. Enable IMAP in your mailbox: Outlook web → **Settings** → **Mail** → **Sync email** → **POP and IMAP** → turn on **Let devices and apps use POP/IMAP**.
2. Go to <https://account.microsoft.com/security> → **Advanced security options** → **App passwords** → **Create a new app password**.
3. Copy the 16-character password. Paste it into imail when adding the account.

Host: `outlook.office365.com:993`

---

## 163 / 126 / Yeah

1. Sign in to <https://mail.163.com>.
2. Top bar → **设置 (Settings)** → **POP3/SMTP/IMAP**.
3. Enable **IMAP/SMTP 服务**.
4. Follow the SMS verification prompt; you'll receive a **授权码** (16 characters).
5. Use your full email (`you@163.com`) and the 授权码 in imail.

Hosts: `imap.163.com:993`, `imap.126.com:993`

> 163 returns "Unsafe Login" without an IMAP `ID` command. imail sends it automatically.

---

## QQ Mail

1. Sign in to <https://mail.qq.com>.
2. **设置 (Settings)** → **账户 (Account)** → scroll to **POP3/IMAP/SMTP**.
3. Enable **IMAP/SMTP 服务** (verify with SMS).
4. Copy the **授权码** (16 characters).
5. Use your full email (`you@qq.com`) and the 授权码.

Host: `imap.qq.com:993`

---

## Yahoo Mail

1. <https://login.yahoo.com/account/security> → **Generate app password**.
2. Name it `imail`. Copy the password.

Host: `imap.mail.yahoo.com:993`

---

## iCloud

1. <https://appleid.apple.com> → **Sign-In and Security** → **App-Specific Passwords** → **Generate**.
2. Use your iCloud email (`you@icloud.com`) and the generated password.

Host: `imap.mail.me.com:993`

---

## Custom IMAP host

If your provider isn't listed, choose **Custom** and supply:

- **IMAPS host** (e.g. `imap.fastmail.com`)
- **Port** — almost always `993`
- **Email** + **password / app password**

imail uses IMAPS (TLS on port 993) only — no plaintext IMAP, no STARTTLS.

---

## What gets stored where?

| Item                              | Location                                      |
|-----------------------------------|-----------------------------------------------|
| Account label, host, username     | `~/.config/imail/accounts.json`         |
| App password / 授权码              | OS keyring (macOS Keychain on this machine)   |
| Gmail OAuth refresh token         | `~/.config/imail/token-<account-id>.json` (mode 0600) |

You can remove an account from the UI at any time — the keyring entry and any token files are deleted with it.
