"""Generate three reply versions per email using DeepSeek's OpenAI-compatible API.

We ask the model for three drafts in a single call — cheaper, lower latency, and
more self-consistent than three separate calls. DeepSeek transparently caches
common prefixes server-side, so re-using the same system prompt across emails
in one session is essentially free for the cached portion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI

from imail.providers.base import EmailMsg

# Stable system prompt — long, so the cached prefix is large and re-used.
SYSTEM_PROMPT = """You are an email-reply assistant. For every email the user shows you,
draft THREE complete reply versions, each tonally distinct, so the user can
pick one in under five seconds.

The three tones are FIXED:

1. POSITIVE  — warm, enthusiastic, accepts / agrees / says yes.
2. NEUTRAL   — polite, non-committal, defers a decision ("let me think",
               "let me check my calendar", "I'll get back to you"). Use when
               the email asks for a yes/no; if the email is purely informational,
               keep this tone brief and acknowledging.
3. NEGATIVE  — polite refusal / disagreement / "no thanks", graceful and kind.

Rules for every reply:

- Sign off using only the user's first name on a new line (no full signature).
- Match the language of the incoming email (English / Chinese / etc.).
- 2-5 sentences. No "Subject:" line, no quoted history, no markdown.
- Address the sender by their first name if obvious from the From header,
  otherwise omit the salutation.
- Do not invent facts. If a fact is needed, hedge ("I'll check and confirm...").

Return ONLY a JSON object, no surrounding prose, with exactly this shape:

{
  "positive": "...full reply text...",
  "neutral":  "...full reply text...",
  "negative": "...full reply text..."
}
"""


@dataclass(frozen=True)
class ReplyTrio:
    """Three drafts produced for a single email."""

    positive: str
    neutral: str
    negative: str

    def as_dict(self) -> dict[str, str]:
        return {
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
        return (
            f"Recipient (me): {self._signoff}\n"
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"---\n"
            f"{body}\n"
            f"---\n"
            "Draft three reply versions (positive / neutral / negative)."
        )


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
        positive=str(payload["positive"]).strip(),
        neutral=str(payload["neutral"]).strip(),
        negative=str(payload["negative"]).strip(),
    )
