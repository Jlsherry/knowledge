"""Tests for upload filename sanitization."""

import pytest

from app.services.document_service import sanitize_upload_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("notes.txt", "notes.txt"),
        ("report.PDF", "report.pdf"),
        (r"..\..\etc\passwd.pdf", "passwd.pdf"),
        ("/var/tmp/evil.docx", "evil.docx"),
        ("", "upload"),
        ("..", "upload"),
        ("  中文 报告 .pdf  ", "中文 报告.pdf"),
        (".pdf", "upload.pdf"),
        ("bad<script>.txt", "badscript.txt"),
        ("name.with.dots.txt", "name.with.dots.txt"),
        ("only-extension", "only-extension"),
        ("a" * 250 + ".txt", "a" * 200 + ".txt"),
    ],
)
def test_sanitize_upload_filename(raw: str, expected: str) -> None:
    assert sanitize_upload_filename(raw) == expected


def test_sanitize_strips_null_bytes() -> None:
    assert sanitize_upload_filename("no\x00tes.txt") == "notes.txt"
