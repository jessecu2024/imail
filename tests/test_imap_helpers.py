"""Pure-function tests for IMAP parsing helpers — no network."""

from __future__ import annotations

from imail.providers.imap import (
    _decode_header_safe,
    _extract_uid,
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
