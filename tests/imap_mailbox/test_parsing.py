"""Auto-generated test module."""
import imaplib as _imaplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)





class TestMimeHeaderDecodingEncoded:
    """Test MIME header decoding with RFC 2047 encoded values."""

    @pytest.mark.asyncio
    async def test_decode_mime_header_encoded_utf8(self, tools):
        """Test decoding RFC 2047 encoded UTF-8 header."""
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
    async def test_decode_mime_header_multiple_encoded_parts(self, tools):
        """Test decoding header with multiple encoded parts."""
        encoded = "=?utf-8?b?VGVzdA==?= =?utf-8?b?IFN1YmplY3Q?="
        result = tools._decode_mime_header(encoded)
        assert "Test" in result

    @pytest.mark.asyncio
    async def test_decode_mime_header_unknown_charset(self, tools):
        """Test decoding with unknown charset falls back to utf-8."""
        encoded = rb"=\?unknown-charset?b?dGVzdA=="
        result = tools._decode_mime_header(encoded.decode())
        assert result != ""




class TestGetEmailBody:
    """Test _get_email_body extraction logic."""

    @pytest.mark.asyncio
    async def test_get_email_body_multipart_plain_only(self, tools):
        """Test extracting body from a multipart email with plain text part."""
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
        """Test extracting body — if no plain part, should return empty string."""
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
        from email.mime.multipart import MIMEMultipart
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

        msg = MIMEText("A" * 500, "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Long"
        body = tools._get_email_body(msg, max_chars=50)
        assert len(body) <= 50 + len("\n\n... [truncated]")

    @pytest.mark.asyncio
    async def test_get_email_body_single_non_multipart(self, tools):
        """Test extracting body from a non-multipart email."""

        msg = MIMEText("Hello world plain text", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Simple"
        body = tools._get_email_body(msg)
        assert body == "Hello world plain text"

    @pytest.mark.asyncio
    async def test_get_email_body_binary_payload_decode(self, tools):
        """Test body extraction when payload is bytes with a charset."""

        msg = MIMEText("Accents: caf\u00e9 r\u00e9sum\u00e9", "plain")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "Accents"
        body = tools._get_email_body(msg)
        assert "caf\u00e9" in body

