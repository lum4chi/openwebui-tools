"""Auto-generated test module."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

from pop3_mailbox import Tools

from .conftest import (
    _make_mock_server,
    _make_raw_email,
)


class TestPOP3SearchWithFrom:
    """Test search_emails with from filter."""

    @pytest.mark.asyncio
    async def test_search_emails_empty_from_filter(self, tools):
        """Test search_emails with from: filter that matches nothing."""
        raw = _make_raw_email("bob@example.com", "user@example.com", "Hello", "Hi!")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="from:nobody@example.com", count=5)
        assert "No emails found" in result




class TestPOP3SearchWithBeforeAfter:
    """Test search_emails with date range filters."""

    @pytest.mark.asyncio
    async def test_search_emails_before_and_after_date(self, tools):
        """Test search_emails with both before and after date filters."""
        raw = _make_raw_email("a@b.com", "c@d.com", "Hello", "Body")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2020-01-01 before:2030-12-31", count=5)
        # Email from 2025-04-21 should match
        assert "Found" in result or "1" in result

    @pytest.mark.asyncio
    async def test_search_emails_date_range_no_match(self, tools):
        """Test search_emails with date range that excludes all emails."""
        raw = _make_raw_email("a@b.com", "c@d.com", "Hello", "Body")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2030-01-01", count=5)
        assert "No emails found" in result




class TestPOP3SearchWithAttachments:
    """Test search_emails attachment display (line 371)."""

    @pytest.mark.asyncio
    async def test_search_emails_with_attachments_shows_count(self):
        """Test that search_emails shows attachment count when emails have attachments (line 371)."""
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

        assert "Attachment" in result or "attachment" in result
        assert "1" in result
