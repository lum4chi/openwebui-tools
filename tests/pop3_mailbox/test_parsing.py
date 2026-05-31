"""Auto-generated test module."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

import pytest

from pop3_mailbox import EncryptionMode, Tools

from .conftest import (
    _make_mock_server,
    _make_raw_email,
)


class TestPOP3DecodeMime:
    """Test _decode_mime_header RFC 2047 encoded values (missing vs IMAP tests)."""

    @pytest.mark.asyncio
    async def test_decode_mime_header_encoded_utf8(self, tools):
        """Test decoding RFC 2047 base64-encoded UTF-8 header."""
        encoded = "=?utf-8?b?VGVzdCBzdWJqZWN0?="
        result = tools._decode_mime_header(encoded)
        assert result == "Test subject"

    @pytest.mark.asyncio
    async def test_decode_mime_header_encoded_q(self, tools):
        """Test decoding RFC 2047 encoded-Q header."""
        encoded = "=?utf-8?q?Test_Subject?="
        result = tools._decode_mime_header(encoded)
        assert result == "Test Subject"

    @pytest.mark.asyncio
    async def test_decode_mime_header_multiple_encoded(self, tools):
        """Test header with multiple encoded parts."""
        encoded = "=?utf-8?b?VGVzdA==?= =?utf-8?b?IFN1YmplY3Q?="
        result = tools._decode_mime_header(encoded)
        assert "Test" in result


class TestPOP3GetEmailBody:
    """Test _get_email_body extraction logic (missing vs IMAP tests)."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_plain_only(self, tools):
        """Extract plain text from multipart email."""
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Multibody"
        text_part = MIMEText("Plain body content", "plain")
        html_part = MIMEText("<p>HTML body</p>", "html")
        msg.attach(text_part)
        msg.attach(html_part)
        body = tools._get_email_body(msg)
        assert body == "Plain body content"

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_html_only(self, tools):
        """Extract body — if no plain part, should return empty string."""
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "HtOnly"
        html_part = MIMEText("<p>HTML only</p>", "html")
        msg.attach(html_part)
        body = tools._get_email_body(msg)
        assert body == ""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_with_attachment(self, tools):
        """Test that attachment parts in multipart are skipped."""
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Attach test"
        plain_part = MIMEText("Real content here", "plain")
        msg.attach(plain_part)
        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(b"fake pdf data")
        attachment.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(attachment)
        body = tools._get_email_body(msg)
        assert body == "Real content here"

    @pytest.mark.asyncio
    async def test_get_email_body_truncation(self, tools):
        """Test that body is truncated at max_chars."""
        from email.mime.text import MIMEText

        msg = MIMEText("A" * 500, "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Long"
        body = tools._get_email_body(msg, max_chars=50)
        assert len(body) <= 50 + len("\n\n... [truncated]")

    @pytest.mark.asyncio
    async def test_get_email_body_single_non_multipart(self, tools):
        """Extract body from a non-multipart email."""
        from email.mime.text import MIMEText

        msg = MIMEText("Hello world plain text", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Simple"
        body = tools._get_email_body(msg)
        assert body == "Hello world plain text"

    @pytest.mark.asyncio
    async def test_get_email_body_unicode(self, tools):
        """Test body extraction preserves unicode characters."""
        from email.mime.text import MIMEText

        msg = MIMEText("Accents: caf\u00e9 r\u00e9sum\u00e9", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Accents"
        body = tools._get_email_body(msg)
        assert "caf\u00e9" in body


class TestPOP3ReadNonSSL:
    """Test non-SSL path for methods other than list_emails."""

    @pytest.mark.asyncio
    async def test_read_email_non_ssl(self):
        """Test read_email uses poplib.POP3 with STARTTLS when encryption_method='starttls'."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.encryption_method = EncryptionMode.starttls
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
        ]
        mock_server = _make_mock_server(1, emails)
        with patch("poplib.POP3", return_value=mock_server) as mock_pop3:
            result = await t.read_email(email_index=1)
        mock_pop3.assert_called_once()
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_non_ssl(self):
        """Test search_emails uses poplib.POP3 with STARTTLS when encryption_method='starttls'."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.encryption_method = EncryptionMode.starttls
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
        ]
        mock_server = _make_mock_server(1, emails)
        with patch("poplib.POP3", return_value=mock_server) as mock_pop3:
            result = await t.search_emails(query="hello", count=10)
        mock_pop3.assert_called_once()
        assert "alice@example.com" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_delete_email_non_ssl(self):
        """Test delete_email uses poplib.POP3 with STARTTLS when encryption_method='starttls'."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.encryption_method = EncryptionMode.starttls
        t.valves.allow_delete_single = True
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
        ]
        mock_server = _make_mock_server(1, emails)
        with patch("poplib.POP3", return_value=mock_server) as mock_pop3:
            result = await t.delete_email(email_index=1)
        mock_pop3.assert_called_once()
        assert "deleted successfully" in result

    @pytest.mark.asyncio
    async def test_get_email_count_non_ssl(self):
        """Test get_email_count uses poplib.POP3 with STARTTLS when encryption_method='starttls'."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.encryption_method = EncryptionMode.starttls
        mock_server = _make_mock_server(5, [])
        with patch("poplib.POP3", return_value=mock_server) as mock_pop3:
            result = await t.get_email_count()
        mock_pop3.assert_called_once()
        assert "5" in result


class TestPOP3ListEmailsAttachment:
    """Test list_emails with attachments."""

    @pytest.mark.asyncio
    async def test_list_emails_shows_attachment_count(self, tools):
        """Test list_emails shows attachment info when emails have attachments."""
        from email.mime.base import MIMEBase

        msg = MIMEMultipart()
        msg["From"] = "sender@example.com"
        msg["To"] = "user@example.com"
        msg["Subject"] = "Document Attached"
        msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
        msg.attach(MIMEText("body text", "plain"))
        part = MIMEBase("application", "octet-stream")
        part.set_payload(b"fake-attachment-content")
        part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(part)
        email_bytes = msg.as_bytes()

        mock_server = _make_mock_server(1, [email_bytes])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5)
        assert "attachment" in result.lower() and "1" in result


class TestPOP3ReadEmailAttachment:
    """Test read_email with attachments."""

    @pytest.mark.asyncio
    async def test_read_email_shows_attachment_count(self, tools):
        """Test read_email shows attachment info when email has attachments."""
        from email.mime.base import MIMEBase

        msg = MIMEMultipart()
        msg["From"] = "sender@example.com"
        msg["To"] = "user@example.com"
        msg["Subject"] = "Invoice Attached"
        msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
        msg.attach(MIMEText("invoice content", "plain"))
        part = MIMEBase("application", "octet-stream")
        part.set_payload(b"pdf data")
        part.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
        msg.attach(part)
        email_bytes = msg.as_bytes()

        mock_server = _make_mock_server(1, [email_bytes])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "Attachment" in result and "1" in result
