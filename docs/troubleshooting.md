# Troubleshooting

Solutions to the recurring problems users have actually hit. New
entries are added as they come up — if you trip over something not
listed here, [open an issue](https://github.com/jessecu2024/imail/issues).

## Homebrew users on macOS: IMAP accounts stop working after `brew upgrade`

### Symptom

After `brew upgrade imail`, every IMAP account (163, Outlook, custom)
errors on every request with messages like:

```
keyring.errors.KeyringError: Can't get password from keychain:
  (-25320, 'Unknown Error')
```

The inbox listing returns HTTP 500. Polling logs an error every 10
seconds. Gmail accounts (which use OAuth + a token file, not
keychain) are unaffected.

### Cause

macOS Keychain binds an ACL to the exact binary path that wrote the
password. `brew upgrade` installs the new version under a new path
(e.g. `/usr/local/Cellar/imail/1.4.1/libexec/bin/python` →
`/usr/local/Cellar/imail/1.4.2/libexec/bin/python`), so the new
binary isn't on the keychain item's trust list and macOS refuses
the read.

### Fix

Add the new binary to each IMAP account's keychain partition list.
No password re-entry required.

For each account ID listed in `~/.config/imail/accounts.json` whose
`type` is *not* `gmail`:

```bash
security set-generic-password-partition-list \
  -s imail -a <account-id> \
  -S "apple-tool:,apple:,codesign:,unsigned:"
```

macOS will pop up a dialog asking for your **macOS login password** —
this unlocks the keychain so the ACL change can be saved. Click
**Always Allow** if it gives you that choice, otherwise enter the
password and click **OK**.

A one-liner that does all IMAP accounts at once:

```bash
python3 -c "
import json, pathlib, subprocess
cfg = json.loads(pathlib.Path.home().joinpath('.config/imail/accounts.json').read_text())
for a in cfg.get('accounts', []):
    if a.get('type') != 'gmail':
        subprocess.run(['security', 'set-generic-password-partition-list',
                        '-s', 'imail', '-a', a['id'],
                        '-S', 'apple-tool:,apple:,codesign:,unsigned:'])
"
```

After this runs, restart imail — IMAP accounts work again.

### Why we don't auto-fix this on launch

imail can't write to the keychain ACL without the user's macOS
login password, and prompting for it on every launch would be both
ugly and indistinguishable from a phishing app. The fix is a
one-time per upgrade — `uv tool upgrade`, `pipx upgrade`, and
Docker users don't hit it because their Python binary path doesn't
change across versions.
