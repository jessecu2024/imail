"""Diagnostic: dump the raw IMAP FETCH response 163 returns for a problem
message, so we can build a parser that handles its actual shape.

Run:  uv run python scripts/diag_163_fetch.py <account_id> <folder_kind> <message_id>

Example:  uv run python scripts/diag_163_fetch.py acct_6e604472c0_95331e junk 1778901483
"""

from __future__ import annotations

import contextlib
import imaplib
import sys

from imail.accounts import AccountStore, open_provider
from imail.providers.imap import ImapProvider


def dump(label: str, fetched: object) -> None:
    print(f"\n--- {label} ---")
    if not isinstance(fetched, (list, tuple)):
        print(f"  type={type(fetched).__name__} value={fetched!r}")
        return
    print(f"  list len={len(fetched)}")
    for i, chunk in enumerate(fetched):
        if chunk is None:
            print(f"  [{i}] None")
        elif isinstance(chunk, tuple):
            shapes = [type(x).__name__ for x in chunk]
            print(
                f"  [{i}] tuple({shapes}) len_each={[len(x) if hasattr(x, '__len__') else '-' for x in chunk]}"
            )
            for j, part in enumerate(chunk):
                preview = part[:120] if isinstance(part, (bytes, bytearray)) else part
                print(f"      [{i}][{j}] {type(part).__name__} {preview!r}")
        elif isinstance(chunk, bytes):
            print(f"  [{i}] bytes(len={len(chunk)}) {chunk[:120]!r}")
        else:
            print(f"  [{i}] {type(chunk).__name__} {chunk!r}")


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(f"usage: {sys.argv[0]} <account_id> <folder_kind> <message_id>")
    account_id, kind, message_id = sys.argv[1], sys.argv[2], sys.argv[3]

    store = AccountStore.load()
    account = store.get(account_id)
    if account is None:
        sys.exit(f"no such account: {account_id}")

    provider = open_provider(account)
    if not isinstance(provider, ImapProvider):
        sys.exit("only IMAP accounts supported")

    conn = provider._ensure_connected()  # type: ignore[attr-defined]
    folder = provider._get_folder(kind, conn)  # type: ignore[attr-defined]
    print(f"account={account_id} kind={kind} folder={folder!r} message_id={message_id}")

    # Re-select R/O.
    typ, _ = conn.select(folder, readonly=True)
    print(f"SELECT {folder!r} → {typ}")

    # Probe 1: UID FETCH BODY.PEEK[]
    typ, fetched = conn.uid("FETCH", message_id, "(BODY.PEEK[])")
    print(f"\nProbe 1 (UID FETCH BODY.PEEK[]): typ={typ}")
    dump("probe1", fetched)

    # Probe 2: SEARCH UID
    typ, search_data = conn.uid("SEARCH", "UID", message_id)
    print(f"\nProbe 2a (UID SEARCH UID {message_id}): typ={typ} data={search_data!r}")
    if typ == "OK" and search_data and search_data[0]:
        seq = search_data[0].split()[0] if search_data[0] else None
        if seq:
            typ, fetched = conn.fetch(seq, "(BODY.PEEK[])")
            print(f"Probe 2b (FETCH {seq} BODY.PEEK[]): typ={typ}")
            dump("probe2b", fetched)

    # Probe 3: UID FETCH RFC822
    typ, fetched = conn.uid("FETCH", message_id, "(RFC822)")
    print(f"\nProbe 3 (UID FETCH RFC822): typ={typ}")
    dump("probe3", fetched)

    # Probe 4: smaller pieces — HEADER and TEXT separately
    typ, fetched = conn.uid("FETCH", message_id, "(BODY.PEEK[HEADER])")
    print(f"\nProbe 4a (UID FETCH BODY.PEEK[HEADER]): typ={typ}")
    dump("probe4a", fetched)
    typ, fetched = conn.uid("FETCH", message_id, "(BODY.PEEK[TEXT])")
    print(f"\nProbe 4b (UID FETCH BODY.PEEK[TEXT]): typ={typ}")
    dump("probe4b", fetched)

    # Probe 5: bodystructure to see what 163 thinks the message looks like
    typ, fetched = conn.uid("FETCH", message_id, "(BODYSTRUCTURE)")
    print(f"\nProbe 5 (UID FETCH BODYSTRUCTURE): typ={typ}")
    dump("probe5", fetched)

    # Probe 6: ALL fetch
    typ, fetched = conn.uid("FETCH", message_id, "(FLAGS RFC822.SIZE INTERNALDATE)")
    print(f"\nProbe 6 (UID FETCH FLAGS+SIZE+INTERNALDATE): typ={typ}")
    dump("probe6", fetched)

    with contextlib.suppress(imaplib.IMAP4.error):
        conn.logout()


if __name__ == "__main__":
    main()
