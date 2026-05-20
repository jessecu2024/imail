"""Parser tests — the network-dependent code is exercised separately at runtime."""

from __future__ import annotations

import pytest

from imail.reply_generator import (
    SYSTEM_PROMPT,
    ReplyTrio,
    build_salutation,
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


# ---------- salutation building ---------- #


def test_build_salutation_personal_sender() -> None:
    """A real person gets a first-name salutation."""
    assert build_salutation("Alex Wang <alex@stanford.edu>") == "Dear Alex,"


def test_build_salutation_bare_address_personal() -> None:
    """A bare address without obvious institutional markers is treated as a person."""
    assert build_salutation("alex.wang@stanford.edu") == "Dear Alex,"


def test_build_salutation_institutional_service_desk() -> None:
    """`Japan Visa Service Desk <evisa@vfsglobal.com>` previously opened
    replies with `Dear Japan,`. Now it should use a brand-team salutation
    derived from the domain so the recipient isn't named after a country."""
    salutation = build_salutation("Japan Visa Service Desk <evisa.jphk@vfsglobal.com>")
    assert salutation.startswith("Dear ")
    assert salutation.endswith(" Team,")
    assert "Japan," not in salutation


def test_build_salutation_no_reply_localpart() -> None:
    """`no-reply@…` is institutional even with no display name."""
    salutation = build_salutation("no-reply@vfsglobal.com")
    assert salutation.startswith("Dear ")
    assert salutation.endswith(" Team,")


def test_build_salutation_uppercases_short_brand() -> None:
    """`hsbc.com` → `HSBC`, not `Hsbc`."""
    assert build_salutation("HSBC <noreply@hsbc.com>") == "Dear HSBC Team,"


def test_build_salutation_strips_transactional_subdomain() -> None:
    """`messaging.hsbc.com.hk` should resolve to `HSBC`, not `Messaging`."""
    salutation = build_salutation("HSBC <hsbc.communications@messaging.hsbc.com.hk>")
    assert salutation == "Dear HSBC Team,"


def test_build_salutation_github_notifications() -> None:
    """`notifications@github.com` → a Github team salutation."""
    salutation = build_salutation("sourcery-ai[bot] <notifications@github.com>")
    assert salutation == "Dear Github Team,"


def test_build_salutation_empty_input_returns_hello() -> None:
    """Nothing to work with → fall back to `Hello,`."""
    assert build_salutation("") == "Hello,"
    assert build_salutation("   ") == "Hello,"


def test_build_salutation_cjk_only_falls_back() -> None:
    """A non-Latin sender with no usable Latin local-part → `Hello,`."""
    assert build_salutation("张老师 <张老师@中国.cn>") == "Hello,"


# ---------- system prompt enforces the Dear / Best regards format ---------- #


def test_system_prompt_requires_dear_salutation() -> None:
    assert "Dear" in SYSTEM_PROMPT


def test_system_prompt_requires_best_regards_closing() -> None:
    assert "Best regards" in SYSTEM_PROMPT


def test_system_prompt_requires_english_only_replies() -> None:
    """Replies are always English regardless of incoming language."""
    assert "ENTIRE reply in English" in SYSTEM_PROMPT


def test_system_prompt_references_salutation_field() -> None:
    """The prompt instructs the model to use the Salutation field verbatim
    rather than building a salutation from a first-name field."""
    assert "Salutation" in SYSTEM_PROMPT
