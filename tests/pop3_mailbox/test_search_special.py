"""Auto-generated test module."""

from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

import pytest

from pop3_mailbox import Tools

from .conftest import (
    _make_mock_server,
    _make_raw_email,
)


class TestPOP3SearchWithFrom:
    """Test search_emails with from filter."""

    @pytest.mark.asyncio
    async def test_search_emails_empty_from_filter(self, tools):
        # T1-SEARCH-FROM-EMPTY
        # Given a POP3 mailbox with one email from bob@example.com
        # When the tool searches with a from: filter for a different address
        # Then no emails are found
        raw = _make_raw_email("bob@example.com", "user@example.com", "Hello", "Hi!")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="from:nobody@example.com", count=5)
        assert "No emails found" in result


class TestPOP3SearchWithBeforeAfter:
    """Test search_emails with date range filters."""

    @pytest.mark.asyncio
    async def test_search_emails_before_and_after_date(self, tools):
        # T1-RED-3
        # Given two POP3 emails, one dated inside a date range and one dated outside the range
        # When the tool searches with after: and before: filters
        # Then the in-range email is returned
        # And the out-of-range email is not returned
        in_range = _make_raw_email("a@b.com", "c@d.com", "Hello", "Body")
        out_msg = MIMEText("BodyOut", "plain")
        out_msg["From"] = "x@y.com"
        out_msg["To"] = "z@w.com"
        out_msg["Subject"] = "TooNew"
        out_msg["Date"] = "Mon, 01 Jan 2035 10:00:00 +0000"
        out_of_range = out_msg.as_bytes()
        mock_server = _make_mock_server(2, [in_range, out_of_range])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2020-01-01 before:2030-12-31", count=5)
        assert "Found 1 email(s)" in result and "Hello" in result and "TooNew" not in result

    @pytest.mark.asyncio
    async def test_search_emails_date_range_no_match(self, tools):
        # T1-SEARCH-RANGE-NO-MATCH
        # Given a POP3 mailbox with one email dated 2025-04-21
        # When the tool searches with an after: filter dated after the email
        # Then no emails are found
        raw = _make_raw_email("a@b.com", "c@d.com", "Hello", "Body")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2030-01-01", count=5)
        assert "No emails found" in result


class TestPOP3SearchWithAttachments:
    """Test search_emails attachment display (line 371)."""

    @pytest.mark.asyncio
    async def test_search_emails_with_attachments_shows_count(self):
        # T1-SEARCH-ATTACHMENT
        # Given a POP3 mailbox with one email carrying a single attachment
        # When the tool searches and the email matches
        # Then the result includes the attachment count
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.pop3_server = "mail.example.com"

        msg = MIMEMultipart()
        msg["From"] = "sender@example.com"
        msg["To"] = "user@example.com"
        msg["Subject"] = "Document Attached"
        msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
        msg.attach(MIMEText("body text", "plain"))
        part = MIMEBase("application", "octet-stream")
        part.set_payload(b"fake-attachment-content")
        part.add_header("Content-Disposition", "attachment", filename="document.pdf")
        msg.attach(part)
        raw = msg.as_bytes()

        mock_server = _make_mock_server(1, [raw])

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.search_emails(query="Attached", count=5)

        assert "[1 attachment(s)]" in result
