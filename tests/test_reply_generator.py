"""Parser tests — the network-dependent code is exercised separately at runtime."""

from __future__ import annotations

import pytest

from imail.reply_generator import (
    SYSTEM_PROMPT,
    ReplyTrio,
    extract_first_name,
    parse_reply_json,
)


def test_parse_clean_json() -> None:
    raw = (
        '{"is_spam": false, "positive": "Yes!", "neutral": "Thanks, let me think.", '
        '"negative": "Sorry, no."}'
    )
    trio = parse_reply_json(raw)
    assert trio == ReplyTrio(
        positive="Yes!",
        neutral="Thanks, let me think.",
        negative="Sorry, no.",
        is_spam=False,
    )


def test_parse_json_with_code_fence() -> None:
    raw = '```json\n{"is_spam": false, "positive": "a", "neutral": "b", "negative": "c"}\n```'
    trio = parse_reply_json(raw)
    assert (trio.positive, trio.neutral, trio.negative) == ("a", "b", "c")


def test_parse_json_with_leading_prose() -> None:
    raw = 'Here you go:\n{"positive": "a", "neutral": "b", "negative": "c"}\nLet me know.'
    trio = parse_reply_json(raw)
    assert trio.positive == "a"


def test_parse_spam_email_returns_empty_replies() -> None:
    raw = '{"is_spam": true, "positive": "", "neutral": "", "negative": ""}'
    trio = parse_reply_json(raw)
    assert trio.is_spam is True
    assert trio.positive == ""


def test_parse_legacy_missing_is_spam_defaults_to_false() -> None:
    """Older responses without is_spam still parse, treating as non-spam."""
    raw = '{"positive": "ok", "neutral": "ok", "negative": "ok"}'
    trio = parse_reply_json(raw)
    assert trio.is_spam is False


def test_parse_raises_when_no_json() -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_reply_json("the model went rogue and produced only prose")


# ---------- first-name extraction (used for `Dear <FirstName>,` salutation) ---------- #


def test_extract_first_name_display_name() -> None:
    assert extract_first_name("Alex Wang <alex@x.com>") == "Alex"


def test_extract_first_name_last_comma_first() -> None:
    assert extract_first_name('"Wang, Alex" <alex@x.com>') == "Alex"


def test_extract_first_name_email_local_part_with_dot() -> None:
    assert extract_first_name("alex.wang@x.com") == "Alex"


def test_extract_first_name_email_only_no_separators() -> None:
    assert extract_first_name("alex@x.com") == "Alex"


def test_extract_first_name_empty_returns_empty() -> None:
    assert extract_first_name("") == ""


def test_extract_first_name_malformed_returns_empty() -> None:
    assert extract_first_name("   <>   ") == ""


def test_extract_first_name_cjk_display_falls_back_to_local_part() -> None:
    """Chinese-only display name → fall back to email local-part so the
    English-only reply opens with `Dear Zhang,` not `Dear 张老师,`."""
    assert extract_first_name("张老师 <zhang@university.cn>") == "Zhang"


def test_extract_first_name_japanese_display_falls_back_to_local_part() -> None:
    assert extract_first_name("山田太郎 <yamada@x.co.jp>") == "Yamada"


def test_extract_first_name_mixed_script_picks_latin_token() -> None:
    """A mixed display like `张 Alex Wang <...>` prefers the Latin
    token rather than the Chinese surname."""
    assert extract_first_name("张 Alex Wang <alex@x.com>") == "Alex"


def test_extract_first_name_all_non_latin_returns_empty() -> None:
    """No Latin anywhere — display, local-part — return empty so the
    caller falls back to `there` rather than emitting `Dear 张老师,`."""
    assert extract_first_name("张老师 <张老师@中国.cn>") == ""


# ---------- system prompt enforces the Dear / Best regards format ---------- #


def test_system_prompt_requires_dear_salutation() -> None:
    assert "Dear" in SYSTEM_PROMPT


def test_system_prompt_requires_best_regards_closing() -> None:
    assert "Best regards" in SYSTEM_PROMPT


def test_system_prompt_requires_english_only_replies() -> None:
    """Replies are always English regardless of incoming language."""
    assert "ENTIRE reply in English" in SYSTEM_PROMPT


def test_system_prompt_instructs_reading_conversation_history() -> None:
    """The prompt must tell the model to read quoted earlier messages so
    it doesn't re-promise actions the user has already completed."""
    assert "CONVERSATION HISTORY" in SYSTEM_PROMPT
    assert "Do NOT redo or re-promise" in SYSTEM_PROMPT
