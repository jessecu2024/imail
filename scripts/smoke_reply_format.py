"""Manual smoke test for the reply-format prompt.

Run:  uv run python scripts/smoke_reply_format.py
Cost: one DeepSeek call per case (~0.1¢ each).

Edit CASES below to add your own. The script prints each draft so you
can eyeball whether `Dear <FirstName>,` and `Best regards,\n<signoff>`
are showing up as required.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from imail.config import load_settings
from imail.providers.base import EmailMsg
from imail.reply_generator import ReplyGenerator, extract_first_name

CASES: list[EmailMsg] = [
    EmailMsg(
        id="1", thread_id="1",
        sender="Alex Wang <alex.wang@example.com>",
        subject="Coffee next week?",
        snippet="",
        body=(
            "Hi Jie, are you free for coffee next Tuesday afternoon? "
            "Around 3pm at the usual place. Let me know!"
        ),
    ),
    EmailMsg(
        id="2", thread_id="2",
        sender='"Wang, Alex" <alex@x.com>',
        subject="Reschedule meeting",
        snippet="",
        body="Could we move tomorrow's 10am meeting to Thursday at 2pm?",
    ),
    EmailMsg(
        id="3", thread_id="3",
        sender="xujie.cs@cityu.edu.hk",
        subject="Paper review request",
        snippet="",
        body=(
            "Dear Jie, would you have time to review a 12-page paper for "
            "AAAI 2027? Deadline is in 3 weeks."
        ),
    ),
    EmailMsg(
        id="4", thread_id="4",
        sender="张老师 <zhang@university.cn>",
        subject="开会安排",
        snippet="",
        body="徐杰你好,下周三下午三点开组会,讨论一下你最近的进展,有时间吗?",
    ),
]


def main() -> None:
    s = load_settings()
    print(f"USER_SIGNOFF = {s.user_signoff!r}   (closing will be: 'Best regards,\\n{s.user_signoff}')")
    print(f"model        = {s.model}\n")

    g = ReplyGenerator(
        api_key=s.api_key,
        model=s.model,
        user_signoff=s.user_signoff,
        base_url=s.base_url,
    )

    for i, email in enumerate(CASES, 1):
        first = extract_first_name(email.sender) or "there"
        print("=" * 70)
        print(f"CASE {i}:  from={email.sender}")
        print(f"          parsed first-name → {first!r}   (expected salutation: 'Dear {first},')")
        print(f"          subject={email.subject}")
        print("=" * 70)

        trio = g.generate(email)

        for label, text in (("POSITIVE", trio.positive), ("NEUTRAL", trio.neutral), ("NEGATIVE", trio.negative)):
            print(f"\n--- {label} ---")
            print(text)
            print(f"  ✓ opens with 'Dear': {text.startswith('Dear')}")
            closing = f"Best regards,\n{s.user_signoff}"
            print(f"  ✓ closes with 'Best regards,\\n{s.user_signoff}': {text.rstrip().endswith(closing)}")
        print()


if __name__ == "__main__":
    main()
