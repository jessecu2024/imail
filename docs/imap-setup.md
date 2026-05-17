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

## Microsoft 365 / Office 365 (work or school — incl. CityU, ETH, etc.)

University and corporate accounts hosted on Microsoft 365 use the **same**
IMAP host as personal Outlook but a **different SMTP host**, and most tenants
require an **app password** because MFA is forced.

### Step 1 — Check that IMAP is allowed at all

Some tenants disable basic IMAP/SMTP entirely (in favour of OAuth2). To find out:

1. Sign in to <https://outlook.office.com/mail/options/mail/accounts>
2. Look for **POP and IMAP** → confirm IMAP shows the server name `outlook.office365.com`
3. If you don't see this section at all, your IT has disabled it — imail can't
   reach this mailbox via IMAP. Tell me and we'll wire up Microsoft Graph
   (OAuth2) instead, which is what Outlook desktop / Mac Mail use.

### Step 2 — Generate an app password

Only needed if MFA is on (it almost always is on a university account).

1. Open <https://account.activedirectory.windowsazure.com/AppPasswords.aspx>
   (or: <https://mysignins.microsoft.com/security-info> → **Add sign-in method**
   → **App password**)
2. Click **Create**, name it `imail`
3. Copy the long random password — it's shown **once**

> ⚠ If "App passwords" is missing from your security options, the tenant has
> turned them off too. That also means you need OAuth2 (Microsoft Graph).

### Step 3 — Add the account in imail

1. Sidebar → **+ Add account** → **Microsoft 365**
2. Email: your work/school address (e.g. `you@cityu.edu.hk`)
3. App password: the value from Step 2
4. **Add**

Hosts (already filled in by the preset):
- IMAP: `outlook.office365.com:993` (TLS)
- SMTP: `smtp.office365.com:587` (STARTTLS)

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
