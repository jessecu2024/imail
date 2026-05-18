"""Capture README screenshots via Playwright.

Intercepts the listing + message + status APIs so the screenshots show
synthetic demo data instead of the developer's real mailbox contents.

Run:
    uvx --with playwright python scripts/take_screenshots.py

The imail server must be running at http://127.0.0.1:8765 with at least
one account configured — the routes are mocked before any real request
goes out, so the account just needs to exist (no live IMAP traffic).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

URL = "http://127.0.0.1:8765"
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

FAKE_ACCOUNTS = [
    {
        "id": "acct_demo",
        "kind": "imap",
        "label": "work",
        "username": "you@example.com",
        "imap_host": "imap.example.com",
        "imap_preset": "163",
    },
]

FAKE_INBOX = [
    {
        "id": "1001",
        "sender": "Alex Wang <alex.wang@example.com>",
        "subject": "Coffee next Tuesday?",
        "date": "Mon, 18 May 2026 09:14 +0800",
        "unread": True,
        "replied": False,
    },
    {
        "id": "1002",
        "sender": "Sam Lee <sam.lee@example.com>",
        "subject": "Reschedule Thursday review",
        "date": "Mon, 18 May 2026 08:42 +0800",
        "unread": True,
        "replied": False,
    },
    {
        "id": "1003",
        "sender": "registrar@example-uni.edu",
        "subject": "Course registration window opens Friday",
        "date": "Sun, 17 May 2026 22:10 +0800",
        "unread": False,
        "replied": True,
    },
    {
        "id": "1004",
        "sender": "deals@bigshopper.example",
        "subject": "30% OFF YOUR NEXT ORDER — TODAY ONLY",
        "date": "Sun, 17 May 2026 17:55 +0800",
        "unread": True,
        "replied": False,
    },
]

FAKE_SENT = [
    {
        "id": "local:1001",
        "sender": "Alex Wang <alex.wang@example.com>",
        "subject": "Re: Coffee next Tuesday?",
        "date": "2026-05-18T01:18+00:00",
        "unread": False,
        "replied": False,
    },
    {
        "id": "local:1003",
        "sender": "registrar@example-uni.edu",
        "subject": "Re: Course registration window opens Friday",
        "date": "2026-05-17T14:22+00:00",
        "unread": False,
        "replied": False,
    },
    {
        "id": "8001",
        "sender": "you@example.com",
        "subject": "Re: Quarterly report draft",
        "date": "Sat, 16 May 2026 11:30 +0800",
        "unread": False,
        "replied": False,
    },
]

FAKE_TRIAGE = {
    "done": False,
    "remaining": 0,
    "email": {
        "id": "1001",
        "sender": "Alex Wang <alex.wang@example.com>",
        "subject": "Coffee next Tuesday?",
        "body": (
            "Hi! Are you free for coffee next Tuesday afternoon? "
            "Around 3pm at the usual spot. Let me know!"
        ),
        "date": "Mon, 18 May 2026 09:14 +0800",
    },
    "replies": {
        "is_spam": False,
        "positive": (
            "Dear Alex,\n\nI'd love to. Tuesday at 3pm at our usual spot "
            "works — see you then!\n\nBest regards,\nJie Xu"
        ),
        "neutral": (
            "Dear Alex,\n\nThanks for the invite — let me check my "
            "calendar and get back to you by tomorrow.\n\nBest regards,\nJie Xu"
        ),
        "negative": (
            "Dear Alex,\n\nThanks for thinking of me, but next Tuesday "
            "doesn't work this week. Maybe the week after?\n\nBest regards,\nJie Xu"
        ),
    },
    "already_replied": False,
    "chosen_reply": None,
    "replied_at": None,
}


def mock(route: Route) -> None:
    import json

    url = route.request.url
    if url.endswith("/api/status"):
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok": true, "llm_configured": true, "model": "deepseek-chat", '
            '"signoff": "Jie Xu", "config_dir": "/Users/you/.config/imail"}',
        )
    elif url.endswith("/api/accounts"):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_ACCOUNTS))
    elif "/api/folders/acct_demo/inbox" in url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_INBOX))
    elif "/api/folders/acct_demo/sent" in url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_SENT))
    elif "/api/folders/acct_demo" in url:
        route.fulfill(status=200, content_type="application/json", body="[]")
    elif "/api/triage/single" in url:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(FAKE_TRIAGE))
    else:
        route.continue_()


def shot(page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=path, full_page=False)
    print(f"  ✓ {path}")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        ctx.route("**/*", mock)
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_selector(".sidebar", timeout=5_000)
        time.sleep(1.0)

        # Inbox listing — 1 replied row + 3 unread (1 is spam-looking).
        print("01: inbox listing with Replied badge")
        page.wait_for_selector(".message-row", timeout=5_000)
        time.sleep(0.8)
        shot(page, "01-inbox")

        # Triage view — click first inbox row to land on 3-reply picker.
        page.locator(".message-row").first.click()
        page.wait_for_selector(".reply-card", timeout=5_000)
        time.sleep(1.0)
        print("02: triage — 3 reply tones (Dear/Best regards format)")
        shot(page, "02-triage")

        # Back to folder, then Sent.
        page.locator(".link-back").first.click()
        time.sleep(0.5)
        page.locator(".folder-link", has_text="Sent").first.click()
        page.wait_for_selector(".message-row", timeout=5_000)
        time.sleep(1.0)
        print("03: sent — local: rows mixed with real IMAP rows")
        shot(page, "03-sent")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
