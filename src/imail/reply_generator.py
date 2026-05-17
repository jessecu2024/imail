"""Generate three reply versions per email using DeepSeek's OpenAI-compatible API.

We ask the model for three drafts in a single call — cheaper, lower latency, and
more self-consistent than three separate calls. DeepSeek transparently caches
common prefixes server-side, so re-using the same system prompt across emails
in one session is essentially free for the cached portion.
"""

from __future__ import annotations

import email.utils
import json
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
- Match the language of the incoming email body for the middle content,
  but keep the `Dear ... ,` salutation and `Best regards,` sign-off in
  English as shown — even if the email is in Chinese.
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

    Used to feed the LLM a clean `Dear <FirstName>,` opener. Handles
    `Display Name <addr>`, `"Last, First" <addr>` (comma-reversed
    surname-first form common in directory listings), and bare addresses
    by capitalising the local-part. Returns "" when nothing usable is
    parseable so the caller can pick its own fallback.
    """
    if not sender_header or not sender_header.strip():
        return ""
    name, addr = email.utils.parseaddr(sender_header)
    name = name.strip().strip('"').strip()
    if name:
        if "," in name:
            last, _, first = name.partition(",")
            first = first.strip()
            if first:
                return first.split()[0]
            # Fall through to using the part before the comma if the
            # right side was empty for some reason.
            return last.strip().split()[0] if last.strip() else ""
        return name.split()[0]
    local = addr.split("@", 1)[0] if addr else ""
    tokens = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return tokens[0].capitalize() if tokens else ""


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
