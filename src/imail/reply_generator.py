"""Generate three reply versions per email using DeepSeek's OpenAI-compatible API.

We ask the model for three drafts in a single call — cheaper, lower latency, and
more self-consistent than three separate calls. DeepSeek transparently caches
common prefixes server-side, so re-using the same system prompt across emails
in one session is essentially free for the cached portion.
"""

from __future__ import annotations

import email.utils
import json
import re
from dataclasses import dataclass

from openai import OpenAI

from imail.providers.base import EmailMsg

# Stable system prompt — long, so the cached prefix is large and re-used.
SYSTEM_PROMPT = """You are an email triage assistant. For every email the user shows you,
do TWO things in one response:

STEP 1 — Spam classification. Set "is_spam" to true if the email is:
  - Bulk advertising / marketing / newsletter / promo blast
  - Phishing / scam / fake invoice / fake "account locked" warning
  - Automated notification with no realistic reply expected (receipts,
    "your password was changed", system pings)
  - Sender's domain mismatches the supposed brand
Set "is_spam" to false for genuine person-to-person mail (work, school,
friends, real questions, real requests) — even if it's an automated
calendar invite or commercial transaction where a reply would be useful.

STEP 2 — Draft THREE reply versions, each tonally distinct, so the user
can pick one in under five seconds.

The three tones are FIXED:

1. POSITIVE  — warm, enthusiastic, accepts / agrees / says yes.
2. NEUTRAL   — polite, non-committal, defers a decision ("let me think",
               "let me check my calendar", "I'll get back to you"). Use when
               the email asks for a yes/no; if the email is purely informational,
               keep this tone brief and acknowledging.
3. NEGATIVE  — polite refusal / disagreement / "no thanks", graceful and kind.

CONVERSATION HISTORY: the email body may contain earlier messages
quoted below the new content — typically after lines starting with `>`,
`From:`, `Sent:`, `On <date> ... wrote:`, or a similar marker. READ
THEM. They show what the user (the recipient drafting this reply) has
already said, asked, or attached in prior exchanges.

  - Do NOT redo or re-promise actions the user has already completed.
    If a quoted earlier reply from the user says "Please find attached
    Documents A, B, and C", don't have them re-commit to attaching A
    and C — only address what the latest incoming message actually
    asks for.
  - Acknowledge what was already submitted. Focus the new reply on the
    delta between what's already done and what the latest message
    requests.
  - If the user previously gave concrete numbers, dates, or names,
    reuse them faithfully — don't invent new ones.

Rules for every reply (this format is REQUIRED, no variants):

- Open with `Dear <FirstName>,` on its own line, where FirstName is taken
  from the "Sender first name" field provided below. Follow it with a
  blank line, then the body.
- Close with exactly two lines at the end:
      Best regards,
      <Recipient name from the "Recipient (me)" field>
  No "Thanks", no "Cheers", no "Sincerely" — always `Best regards,` then
  the recipient name on the next line.
- 2-5 sentences in the body. No "Subject:" line, no quoted history,
  no markdown.
- Write the ENTIRE reply in English, regardless of what language the
  incoming email is in. Even if the original email is in Chinese,
  Japanese, German, French, etc., the reply you draft is always in
  natural, professional English. Do not mix languages.
- Do not invent facts. If a fact is needed, hedge ("I'll check and confirm...").

If is_spam is true, set all three reply fields to the empty string "" —
don't waste tokens drafting replies the user will never send.

Return ONLY a JSON object, no surrounding prose, with exactly this shape:

{
  "is_spam": true|false,
  "positive": "...full reply text or empty...",
  "neutral":  "...full reply text or empty...",
  "negative": "...full reply text or empty..."
}
"""


@dataclass(frozen=True)
class ReplyTrio:
    """Triage output: spam flag + three tonally distinct draft replies."""

    positive: str
    neutral: str
    negative: str
    is_spam: bool = False

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "is_spam": self.is_spam,
            "positive": self.positive,
            "neutral": self.neutral,
            "negative": self.negative,
        }


class ReplyGenerator:
    """OpenAI-SDK client pointed at DeepSeek (or any OpenAI-compatible host)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        user_signoff: str,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._signoff = user_signoff

    def generate(self, email: EmailMsg) -> ReplyTrio:
        user_msg = self._build_user_message(email)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            max_tokens=1024,
            temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        return parse_reply_json(text)

    def _build_user_message(self, email: EmailMsg) -> str:
        body = email.body[:4000] if email.body else email.snippet
        first_name = extract_first_name(email.sender) or "there"
        return (
            f"Recipient (me): {self._signoff}\n"
            f"From: {email.sender}\n"
            f"Sender first name (use in 'Dear ...,'): {first_name}\n"
            f"Subject: {email.subject}\n"
            f"---\n"
            f"{body}\n"
            f"---\n"
            "Draft three reply versions (positive / neutral / negative)."
        )


def extract_first_name(sender_header: str) -> str:
    """Best-effort parse of the sender's first name from a From header.

    Used to feed the LLM a clean `Dear <FirstName>,` opener for replies
    drafted in English. Handles `Display Name <addr>`, `"Last, First"
    <addr>` (comma-reversed surname-first form common in directory
    listings), and bare addresses by capitalising the local-part.

    Display names with no Latin letters (e.g. `张老师 <zhang@…>`) fall
    through to the local-part so the salutation reads cleanly in an
    English reply (`Dear Zhang,` rather than `Dear 张老师,`).

    Returns "" when nothing usable is parseable so the caller can pick
    its own fallback (e.g. "there").
    """
    if not sender_header or not sender_header.strip():
        return ""
    name, addr = email.utils.parseaddr(sender_header)
    name = name.strip().strip('"').strip()
    if name:
        tokens = _name_tokens(name)
        for tok in tokens:
            if _has_latin(tok):
                return tok
        # Display name had no Latin tokens — fall through to local-part.
    local = addr.split("@", 1)[0] if addr else ""
    tokens = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    for tok in tokens:
        if _has_latin(tok):
            return tok.capitalize()
    return ""


def _name_tokens(name: str) -> list[str]:
    """Split a display name into ordered candidate tokens.

    `"Wang, Alex"` returns `["Alex", "Wang"]` (first-name first), while
    `"Alex Wang"` returns `["Alex", "Wang"]`. The caller picks the first
    token that looks like a Latin-script first name.
    """
    if "," in name:
        last, _, first = name.partition(",")
        ordered = first.strip().split() + last.strip().split()
    else:
        ordered = name.split()
    return ordered


def _has_latin(token: str) -> bool:
    return bool(re.search(r"[A-Za-z]", token))


def parse_reply_json(raw: str) -> ReplyTrio:
    """Tolerantly parse the model's JSON response."""
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Could not find JSON object in model response: {raw!r}")

    payload = json.loads(cleaned[start : end + 1])

    return ReplyTrio(
        positive=str(payload.get("positive", "")).strip(),
        neutral=str(payload.get("neutral", "")).strip(),
        negative=str(payload.get("negative", "")).strip(),
        is_spam=bool(payload.get("is_spam", False)),
    )
