"""Auto-generated test module."""

from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

import pytest

from .conftest import _make_mock_server, _make_raw_email_with_attachment


class TestAttachmentDisplay:
    """Test attachment info display in listing and reading."""

    @pytest.mark.asyncio
    async def test_list_emails_with_attachments(self, tools):
        """Test that list_emails shows attachment count."""

        msg = MIMEMultipart("mixed")
        msg["From"] = "sender@test.com"
        msg["To"] = "recv@test.com"
        msg["Subject"] = "AttachMsg"
        plain = MIMEText("Body text", "plain")
        msg.attach(plain)

        for i in range(3):
            att = MIMEBase("application", "octet-stream")
            att.set_payload(f"data{i}".encode())
            att.add_header("Content-Disposition", "attachment", filename=f"file{i}.pdf")
            msg.attach(att)

        emails = [(msg.as_bytes(), "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)

        assert "AttachMsg" in result
        assert "3 attachment(s)" in result

    @pytest.mark.asyncio
    async def test_read_email_with_attachments(self, tools):
        """Test that read_email shows attachment info."""

        msg = MIMEMultipart("mixed")
        msg["From"] = "sender@test.com"
        msg["To"] = "recv@test.com"
        msg["Subject"] = "ReadAttach"
        plain = MIMEText("Body text here", "plain")
        msg.attach(plain)

        att = MIMEBase("application", "pdf")
        att.set_payload(b"data")
        att.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(att)

        emails = [(msg.as_bytes(), "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)

        assert "ReadAttach" in result
        assert "Attachments:" in result
        assert "1 file(s) attached" in result


class TestIMAPListEmailsAttachmentDisplay:
    """Test attachment info display in list_emails output."""

    @pytest.mark.asyncio
    async def test_list_emails_with_attachments_shows_count(self, tools):
        """Test that list_emails shows attachment count when emails have attachments."""
        # Create a multipart email with attachment
        email_bytes = _make_raw_email_with_attachment(
            "sender@example.com", "user@example.com", "Document Attached", "Please see the attached file."
        )
        emails = [(email_bytes, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)
        assert "attachment" in result and "1" in result


class TestIMAPSearchWithAttachments:
    """Test attachment info display in search_emails output."""

    @pytest.mark.asyncio
    async def test_search_emails_with_attachments_shows_count(self, tools):
        """Test that search_emails shows attachment count when emails have attachments."""
        email_bytes = _make_raw_email_with_attachment(
            "sender@example.com", "user@example.com", "Invoice Attached", "Invoice attached for your review."
        )
        emails = [(email_bytes, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Invoice", count=5, folder="INBOX")
        assert "attachment" in result.lower() and "1" in result
