#!/usr/bin/env python3
"""Test cases for email-save.py date parsing functionality."""

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pytest>=7.0.0",
# ]
# ///

from datetime import datetime
from pathlib import Path
import sys
import json

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_parse_email_headers_with_date():
    """Test parsing headers when Date header is present."""
    from email_save import parse_email_headers

    message_text = """From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Date: Wed, 15 Jan 2026 10:23:00 +0000

Body content here."""

    headers = parse_email_headers(message_text)
    assert headers.get("date") == "Wed, 15 Jan 2026 10:23:00 +0000"
    assert headers.get("from") == "sender@example.com"
    assert headers.get("subject") == "Test Subject"


def test_parse_email_headers_without_date():
    """Test parsing headers when Date header is missing (the problematic case)."""
    from email_save import parse_email_headers

    message_text = """From: Employee <employee@company.example>
To: User <user@example.org>
Subject: Missing Date Header

Body content here."""

    headers = parse_email_headers(message_text)
    assert headers.get("date") is None
    assert headers.get("from") == "Employee <employee@company.example>"
    assert headers.get("subject") == "Missing Date Header"


def test_generate_filename_with_date_prefix_iso8601_with_tz():
    """Test filename generation with ISO 8601 date format with timezone."""
    from email_save import generate_filename

    date_str = "2026-01-15 10:23+00:00"
    filename = generate_filename(
        message_id=57039,
        subject="Test Subject",
        date_str=date_str,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert "Test" in filename
    assert filename.endswith(".md")


def test_generate_filename_with_date_prefix_iso8601_with_seconds():
    """Test filename generation with ISO 8601 date format including seconds."""
    from email_save import generate_filename

    date_str = "2026-01-15 10:23:45+00:00"
    filename = generate_filename(
        message_id=56993,
        subject="Another Test",
        date_str=date_str,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert "Another" in filename
    assert filename.endswith(".md")


def test_generate_filename_with_date_prefix_iso8601_no_tz():
    """Test filename generation with ISO 8601 date format without timezone."""
    from email_save import generate_filename

    date_str = "2026-01-15 10:23:45"
    filename = generate_filename(
        message_id=56993,
        subject="Test Subject",
        date_str=date_str,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert filename.endswith(".md")


def test_generate_filename_with_date_prefix_iso8601_date_only():
    """Test filename generation with date-only ISO 8601 format."""
    from email_save import generate_filename

    date_str = "2026-01-15"
    filename = generate_filename(
        message_id=56993,
        subject="Test Subject",
        date_str=date_str,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert filename.endswith(".md")


def test_generate_filename_with_date_prefix_empty_date():
    """Test filename generation falls back to message ID when date is empty."""
    from email_save import generate_filename

    filename = generate_filename(
        message_id=57039,
        subject="Test Subject",
        date_str="",  # Empty date (the problem case)
        output_format="markdown",
        date_prefix=True,
    )

    # Should fall back to message ID format
    assert filename == "57039.md"


def test_generate_filename_without_date_prefix():
    """Test filename generation without date prefix still works."""
    from email_save import generate_filename

    filename = generate_filename(
        message_id=57039,
        subject="Test Subject with Special Chars",
        date_str="2026-01-15 10:23+00:00",
        output_format="markdown",
        date_prefix=False,
    )

    # Should use subject-based filename even though date is valid
    assert filename == "57039.md"
    assert "Test Subject" not in filename


def test_generate_filename_sanitizes_subject():
    """Test that filename sanitization handles special characters."""
    from email_save import generate_filename

    filename = generate_filename(
        message_id=57039,
        subject="Test/Subject\\With:Invalid|Chars",
        date_str="2026-01-15 10:23+00:00",
        output_format="markdown",
        date_prefix=True,
    )

    # Should sanitize the invalid characters
    assert "/" not in filename
    assert "\\" not in filename
    assert filename.endswith(".md")


def test_date_format_conversion_to_local_time():
    """Test that dates are converted to local time before formatting."""
    from email_save import generate_filename

    date_str = "2026-01-15 10:23+00:00"
    filename = generate_filename(
        message_id=57039,
        subject="Test",
        date_str=date_str,
        output_format="markdown",
        date_prefix=True,
    )

    date_part = filename.split("-")[0:3]
    extracted_date = "-".join(date_part)

    assert extracted_date == "2026-01-15"


def test_generate_filename_various_formats():
    """Test filename generation with different output formats."""
    from email_save import generate_filename

    date_str = "2026-01-15 10:23+00:00"

    for fmt, ext in [("markdown", "md"), ("text", "txt"), ("json", "json")]:
        filename = generate_filename(
            message_id=57039,
            subject="Test",
            date_str=date_str,
            output_format=fmt,
            date_prefix=True,
        )
        assert filename.endswith(f".{ext}")


def test_rfc2822_date_format():
    """Test parsing RFC 2822 formatted dates that may come from message headers."""
    from datetime import datetime

    rfc2822_date = "Wed, 15 Jan 2026 10:23:00 +0000"

    from email.utils import parsedate_to_datetime

    parsed = parsedate_to_datetime(rfc2822_date)

    assert parsed.year == 2026
    assert parsed.month == 1
    assert parsed.day == 15


def test_generate_filename_missing_date_header_scenario():
    """Test filename generation when date_str is completely empty (missing header).

    This is the scenario from issue #18: emails without Date header that would
    previously fall back to message ID-only filename.
    """
    from email_save import generate_filename

    empty_date = ""
    filename = generate_filename(
        message_id=57039,
        subject="Business Report Subject",
        date_str=empty_date,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename == "57039.md"
    assert not filename.startswith("202")


def test_generate_filename_with_envelope_iso8601_format():
    """Test filename generation with envelope date format (ISO 8601 with timezone).

    This tests the envelope fallback format: "2026-01-15 10:23+00:00"
    Real-world scenario: messages 57039 and 56993 from issue #18.
    """
    from email_save import generate_filename

    envelope_date = "2026-01-15 10:23+00:00"
    filename = generate_filename(
        message_id=57039,
        subject="Business Report",
        date_str=envelope_date,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert "Business" in filename
    assert filename.endswith(".md")


def test_generate_filename_envelope_format_with_seconds():
    """Test envelope date format with seconds (another common variation)."""
    from email_save import generate_filename

    envelope_date = "2026-01-15 10:23:45+00:00"
    filename = generate_filename(
        message_id=56993,
        subject="Another Business Matter",
        date_str=envelope_date,
        output_format="markdown",
        date_prefix=True,
    )

    assert filename.startswith("2026-01-15-")
    assert filename.endswith(".md")


def test_parse_email_headers_missing_date_is_failure_scenario():
    """Test that parse_email_headers returns empty date for messages without Date header.

    This confirms the failure scenario from issue #18: messages where the Date
    header is completely missing from the message body. In this case, the code
    must fall back to the envelope date fetching mechanism.
    """
    from email_save import parse_email_headers

    message_without_date = """From: Sender <sender@company.example>
To: Recipient <recipient@company.example>
Subject: Important Business Matter

This is the body of the message.
It contains important information."""

    headers = parse_email_headers(message_without_date)

    assert headers.get("date") is None
    assert headers.get("from") == "Sender <sender@company.example>"
    assert headers.get("subject") == "Important Business Matter"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
