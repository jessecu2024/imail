"""Parser tests — the network-dependent code is exercised separately at runtime."""

from __future__ import annotations

import pytest

from mail_triage.reply_generator import ReplyTrio, parse_reply_json


def test_parse_clean_json() -> None:
    raw = '{"positive": "Yes!", "neutral": "Thanks, let me think.", "negative": "Sorry, no."}'
    trio = parse_reply_json(raw)
    assert trio == ReplyTrio(
        positive="Yes!", neutral="Thanks, let me think.", negative="Sorry, no."
    )


def test_parse_json_with_code_fence() -> None:
    raw = '```json\n{"positive": "a", "neutral": "b", "negative": "c"}\n```'
    trio = parse_reply_json(raw)
    assert (trio.positive, trio.neutral, trio.negative) == ("a", "b", "c")


def test_parse_json_with_leading_prose() -> None:
    raw = 'Here you go:\n{"positive": "a", "neutral": "b", "negative": "c"}\nLet me know.'
    trio = parse_reply_json(raw)
    assert trio.positive == "a"


def test_parse_raises_when_no_json() -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_reply_json("the model went rogue and produced only prose")
