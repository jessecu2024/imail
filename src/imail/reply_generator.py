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

- Use the "Salutation" field provided below VERBATIM as the first line
  (e.g. `Dear Alex,` for a person, `Dear HSBC Team,` for an organisation,
  or `Hello,` when nothing identifiable is available). Follow it with a
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
        salutation = build_salutation(email.sender)
        return (
            f"Recipient (me): {self._signoff}\n"
            f"From: {email.sender}\n"
            f"Salutation (use VERBATIM as the first line): {salutation}\n"
            f"Subject: {email.subject}\n"
            f"---\n"
            f"{body}\n"
            f"---\n"
            "Draft three reply versions (positive / neutral / negative)."
        )


# ---------- Salutation building ---------- #

# Local-part tokens that strongly indicate an organisation mailbox.
_INSTITUTIONAL_LOCALPART_TOKENS: frozenset[str] = frozenset(
    {
        "noreply",
        "no_reply",
        "donotreply",
        "do_not_reply",
        "info",
        "support",
        "help",
        "service",
        "services",
        "contact",
        "admin",
        "notifications",
        "notification",
        "alerts",
        "alert",
        "team",
        "hello",
        "hi",
        "mail",
        "mailer",
        "postmaster",
        "visa",
        "evisa",
        "billing",
        "accounts",
        "account",
        "office",
        "enquiry",
        "enquiries",
        "feedback",
        "marketing",
        "news",
        "newsletter",
        "press",
        "media",
        "careers",
        "jobs",
        "automated",
        "robot",
        "bot",
        "system",
    }
)

# Substrings that, if present anywhere in the local-part, mark the
# mailbox as institutional even when it isn't an exact token match.
_INSTITUTIONAL_LOCALPART_SUBSTRINGS: tuple[str, ...] = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "notification",
    "newsletter",
    "no_reply",
    "communications",
)

# Words in the display name that mark the sender as an organisation.
_INSTITUTIONAL_DISPLAY_KEYWORDS: tuple[str, ...] = (
    "team",
    "service",
    "services",
    "desk",
    "center",
    "centre",
    "support",
    "office",
    "department",
    "dept",
    "group",
    "newsletter",
    "notification",
    "notifications",
    "alerts",
    "no reply",
    "noreply",
    "no-reply",
    "do not reply",
)

# Domain-name prefixes used for transactional/marketing sub-domains that
# shouldn't appear in a brand label (e.g. "messaging.hsbc.com" → "hsbc").
_DOMAIN_NOISE_PREFIXES: frozenset[str] = frozenset(
    {
        "mail",
        "email",
        "messaging",
        "messages",
        "send",
        "sendgrid",
        "smtp",
        "mta",
        "marketing",
        "promo",
        "newsletter",
        "notifications",
        "notification",
        "alerts",
        "noreply",
        "no-reply",
        "donotreply",
        "info",
        "support",
        "help",
        "auto",
        "system",
        "service",
    }
)

# Common public TLDs (and country-code suffixes) to strip when deriving
# a brand label from a domain.
_DOMAIN_TLDS: frozenset[str] = frozenset(
    {
        "com",
        "net",
        "org",
        "edu",
        "gov",
        "co",
        "io",
        "ai",
        "app",
        "uk",
        "us",
        "cn",
        "hk",
        "tw",
        "jp",
        "kr",
        "sg",
        "au",
        "ca",
        "de",
        "fr",
        "es",
        "it",
        "nl",
        "se",
        "no",
        "fi",
        "dk",
        "ch",
        "in",
        "br",
        "mx",
        "ru",
        "info",
        "biz",
    }
)

# Generic suffix words that get stripped from a display-name-derived
# brand label so it reads cleanly when "Team" is appended.
_DISPLAY_BRAND_TAIL_NOISE: frozenset[str] = frozenset(
    {
        "team",
        "desk",
        "center",
        "centre",
        "department",
        "dept",
        "group",
        "office",
        "support",
        "service",
        "services",
        "hong",
        "kong",
        "tokyo",
        "shanghai",
        "beijing",
        "sydney",
        "london",
        "paris",
        "berlin",
        "new",
        "york",
        "francisco",
        "international",
        "global",
        "worldwide",
        "limited",
        "ltd",
        "inc",
        "incorporated",
        "co",
        "corp",
        "corporation",
        "llc",
    }
)


def build_salutation(sender_header: str) -> str:
    """Pick a context-appropriate salutation for the `Dear ...,` opener.

    Personal senders get `Dear <FirstName>,`. Institutional senders
    (no-reply / service desks / banks / bots) get `Dear <Brand> Team,`,
    derived from the email domain rather than parsing the display name —
    this avoids the surprise of mis-naming the brand as a person (e.g.
    a "Japan Visa Service Desk <evisa@vfsglobal.com>" header used to
    open replies with `Dear Japan,` because "Japan" is the first Latin
    token in the display name).

    Falls back to `Hello,` when nothing identifiable can be derived.
    """
    if not sender_header or not sender_header.strip():
        return "Hello,"

    name, addr = _parseaddr_tolerant(sender_header)
    local, domain = _split_addr(addr)

    if _looks_institutional(name, local):
        brand = _brand_from_domain(domain) or _brand_from_display(name)
        return f"Dear {brand} Team," if brand else "Hello,"

    first = extract_first_name(sender_header)
    return f"Dear {first}," if first else "Hello,"


def _split_addr(addr: str) -> tuple[str, str]:
    """Split an email address into (local-part, domain), lowercased.

    Returns empty strings for parts that aren't present.
    """
    if not addr or "@" not in addr:
        return ("", "")
    local, _, domain = addr.partition("@")
    return (local.lower(), domain.lower())


# Match an `addr@host` substring as a fallback when RFC parsing fails.
_ADDR_FALLBACK_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _parseaddr_tolerant(sender_header: str) -> tuple[str, str]:
    """Parse a From header without choking on `[bot]`-style display names.

    `email.utils.parseaddr` follows RFC 2822 strictly and returns `('', '')`
    when the display name contains square brackets (e.g.
    `sourcery-ai[bot] <notifications@github.com>` — the brackets confuse the
    address parser into treating the whole thing as malformed). Strip
    bracketed comments out of the display name first, then fall back to a
    regex-based address extraction if parsing still fails.
    """
    cleaned = re.sub(r"\[[^\]]*\]", "", sender_header).strip()
    name, addr = email.utils.parseaddr(cleaned)
    name = name.strip().strip('"').strip()
    if not addr:
        match = _ADDR_FALLBACK_RE.search(sender_header)
        if match:
            addr = match.group(0)
            if not name:
                # Display name is whatever comes before the address.
                head = sender_header[: match.start()].strip().strip("<").strip()
                head = re.sub(r"\[[^\]]*\]", "", head).strip().strip('"').strip()
                name = head
    return (name, addr)


def _looks_institutional(display_name: str, local: str) -> bool:
    """Heuristic: does this sender look like an organisation, not a person?"""
    local_tokens = re.split(r"[._\-+]+", local) if local else []
    if any(tok in _INSTITUTIONAL_LOCALPART_TOKENS for tok in local_tokens):
        return True
    if any(sub in local for sub in _INSTITUTIONAL_LOCALPART_SUBSTRINGS):
        return True
    lowered = display_name.lower()
    return any(kw in lowered for kw in _INSTITUTIONAL_DISPLAY_KEYWORDS)


def _brand_from_domain(domain: str) -> str:
    """Best-effort short brand label derived from an email domain.

    Strips TLDs and common transactional sub-domain prefixes, then
    capitalises the remaining label. Short labels (≤4 chars, all-letter)
    are upper-cased so `hsbc.com` → `HSBC` and `bbc.co.uk` → `BBC`,
    while longer ones get title-cased so `github.com` → `Github`.
    """
    if not domain:
        return ""
    parts = [p for p in domain.split(".") if p]
    # Strip trailing TLDs (handles both `.com` and `.co.uk`).
    while parts and parts[-1] in _DOMAIN_TLDS:
        parts.pop()
    # Strip transactional-subdomain prefixes ("messaging.hsbc" → "hsbc").
    while len(parts) > 1 and parts[0] in _DOMAIN_NOISE_PREFIXES:
        parts.pop(0)
    if not parts:
        return ""
    label = parts[0]
    if not _has_latin(label):
        return ""
    if len(label) <= 4 and label.isalpha():
        return label.upper()
    return label.capitalize()


def _brand_from_display(display_name: str) -> str:
    """Fallback: derive a brand label from the display name.

    Drops trailing generic words ("Team", "Desk") and location/legal
    suffixes ("Hong Kong", "Limited") so the result reads cleanly when
    "Team" is appended by the caller.
    """
    if not display_name:
        return ""
    raw_tokens = [t for t in re.split(r"\s+", display_name.strip()) if t]
    # Drop bracketed-suffix junk like "[bot]" or "(noreply)".
    raw_tokens = [t for t in raw_tokens if not re.fullmatch(r"[\[(].+[\])]", t)]
    while raw_tokens and raw_tokens[-1].lower() in _DISPLAY_BRAND_TAIL_NOISE:
        raw_tokens.pop()
    if not raw_tokens:
        return ""
    label = " ".join(raw_tokens[:3])
    return label if _has_latin(label) else ""


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
    its own fallback (e.g. `Hello,`).
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
