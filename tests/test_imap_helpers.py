"""Pure-function tests for IMAP parsing helpers — no network."""

from __future__ import annotations

from imail.providers.imap import (
    _decode_header_safe,
    _extract_uid,
    _first_body,
    _parse_list_folder,
    _parse_status_uidnext,
)


def test_decode_header_handles_rfc2047() -> None:
    encoded = "=?utf-8?B?5L2g5aW9?="
    assert _decode_header_safe(encoded) == "你好"


def test_decode_header_returns_plain_strings_unchanged() -> None:
    assert _decode_header_safe("plain ascii subject") == "plain ascii subject"


def test_extract_uid_finds_digits_after_marker() -> None:
    header = b"1 (UID 1234 BODY[] {12345}\r\n"
    assert _extract_uid(header) == "1234"


def test_extract_uid_returns_none_when_missing() -> None:
    assert _extract_uid(b"1 (BODY[] {12345}\r\n") is None


def test_parse_list_folder_extracts_quoted_name() -> None:
    line = '(\\HasNoChildren \\Drafts) "/" "Drafts"'
    assert _parse_list_folder(line) == "Drafts"


def test_parse_list_folder_handles_chinese_names() -> None:
    line = '(\\HasNoChildren \\Drafts) "/" "草稿箱"'
    assert _parse_list_folder(line) == "草稿箱"


def test_parse_status_uidnext_finds_number() -> None:
    assert _parse_status_uidnext(b'"Drafts" (UIDNEXT 42)') == "42"


def test_parse_status_uidnext_returns_none_when_missing() -> None:
    assert _parse_status_uidnext(b'"Drafts" (MESSAGES 5)') is None


# ----- _first_body: tolerant parser for imaplib FETCH responses ---------- #


def test_first_body_standard_envelope_body_tuple() -> None:
    fetched = [(b"1 (UID 42 BODY[] {25}", b"From: a@x\r\n\r\nhi"), b")"]
    assert _first_body(fetched) == b"From: a@x\r\n\r\nhi"


def test_first_body_skips_empty_payload_in_tuple() -> None:
    """163 sometimes returns the envelope with an empty body — keep looking."""
    fetched = [
        (b"1 (UID 42 BODY[] {0}", b""),
        b"From: a@x\r\n\r\nbody-as-bare-bytes",
        b")",
    ]
    assert _first_body(fetched) == b"From: a@x\r\n\r\nbody-as-bare-bytes"


def test_first_body_accepts_bare_rfc822_chunk_with_header() -> None:
    """163's 已发送 sometimes inlines the body as a top-level bytes chunk
    instead of pairing it with an envelope tuple."""
    fetched = [
        None,
        b"Date: Mon, 01 Jan 2026 10:00:00 +0800\r\nSubject: hi\r\n\r\nbody",
        b")",
    ]
    body = _first_body(fetched)
    assert body is not None
    assert b"Subject: hi" in body


def test_first_body_returns_none_for_empty_response() -> None:
    assert _first_body([None, b")"]) is None
    assert _first_body([]) is None
    assert _first_body(None) is None


def test_first_body_returns_none_when_no_rfc822_marker() -> None:
    """A bare bytes chunk that doesn't look like email shouldn't be returned —
    we'd just pass garbage into the parser."""
    fetched = [b"OK", b"NIL", b")"]
    assert _first_body(fetched) is None
