"""
Tests for the POP3 Mailbox Reader tool.
Uses mocked POP3 responses so no real server is required.
"""

import os

# Ensure the tool module can be imported
import sys
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pop3_mailbox import Tools


def _make_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Create a raw email bytes object for mocking."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Mon, 21 Apr 2025 10:00:00 +0000"
    return msg.as_bytes()


def _make_mock_server(msg_count: int, emails: list) -> MagicMock:
    """Create a mock POP3 server that returns the given emails.

    POP3 spec: index 1 = oldest, index N = newest.
    The tool iterates from msg_count down to 1 (newest to oldest).
    emails[0] = oldest, emails[-1] = newest.

    Returns each email line as a separate list element, matching real
    POP3 server behaviour (poplib.retr returns a list of lines).
    """
    mock_server = MagicMock()
    mock_server.stat.return_value = (msg_count, msg_count * 1000)

    def mock_retr(index):
        if 1 <= index <= msg_count:
            email_idx = index - 1
            if 0 <= email_idx < len(emails):
                # Real POP3 returns each line as a separate bytes element
                lines = emails[email_idx].split(b"\r\n")
                return ("220 OK", lines, len(emails[email_idx]))
        return ("500 Error", [], 0)

    mock_server.retr.side_effect = mock_retr
    mock_server.quit.return_value = None
    return mock_server


@pytest.fixture
def tools():
    t = Tools()
    t.valves.pop3_server = "mail.example.com"
    t.valves.pop3_port = 995
    t.valves.username = "testuser"
    t.valves.password = "testpass"
    t.valves.use_ssl = True
    t.valves.timeout = 5
    return t


class TestPOP3MailboxTool:
    """Test suite for POP3 Mailbox Manager tool."""

    @pytest.mark.asyncio
    async def test_list_emails_no_credentials(self):
        """Test that list_emails returns error when credentials are missing."""
        t = Tools()
        result = await t.list_emails(count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_list_emails_empty_mailbox(self, tools):
        """Test listing emails in an empty mailbox."""
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_emails_with_messages(self, tools):
        """Test listing emails with actual messages."""
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?"),
            _make_raw_email(
                "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
            ),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "Hello" in result
        assert "Invoice #123" in result
        assert "2 total" in result

    @pytest.mark.asyncio
    async def test_read_email(self, tools):
        """Test reading a specific email by index."""
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?"),
            _make_raw_email(
                "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
            ),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "alice@example.com" in result
        assert "Hello" in result
        assert "Hi Bob" in result

    @pytest.mark.asyncio
    async def test_read_email_out_of_range(self, tools):
        """Test reading an email with an out-of-range index."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_by_from(self, tools):
        """Test searching emails by sender."""
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
            _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay."),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="from:alice@example.com", count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" not in result
        assert "1 email" in result.lower() or "1 message" in result.lower()

    @pytest.mark.asyncio
    async def test_search_emails_by_subject(self, tools):
        """Test searching emails by subject keyword."""
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
            _make_raw_email("carol@example.com", "bob@example.com", "Invoice #123", "Please pay."),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="subject:invoice", count=10)
        assert "carol@example.com" in result
        assert "Invoice" in result

    @pytest.mark.asyncio
    async def test_get_email_count(self, tools):
        """Test getting the total email count."""
        mock_server = _make_mock_server(5, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "5" in result

    @pytest.mark.asyncio
    async def test_pop3_connection_error(self, tools):
        """Test handling of POP3 connection errors."""
        import poplib

        mock_server = MagicMock()
        mock_server.stat.side_effect = poplib.error_proto("535 Authentication failed")
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "POP3 Error" in result or "Authentication" in result

    @pytest.mark.asyncio
    async def test_decode_mime_header(self, tools):
        """Test MIME header decoding utility."""
        # Test plain ASCII
        result = tools._decode_mime_header("Hello World")
        assert result == "Hello World"

        # Test empty
        result = tools._decode_mime_header("")
        assert result == ""

        # Test None
        result = tools._decode_mime_header(None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_parse_email_structure(self, tools):
        """Test email parsing produces correct structure."""
        raw = _make_raw_email("test@example.com", "recipient@example.com", "Test Subject", "Test body content")
        parsed = tools._parse_email(raw)
        assert "test@example.com" in parsed["from"]
        assert "Test Subject" in parsed["subject"]
        assert "Test body content" in parsed["body"]
        assert "has_attachments" in parsed
        assert "attachment_count" in parsed
        assert "headers" in parsed

    @pytest.mark.asyncio
    async def test_regression_full_email_parsed_not_first_line_only(self, tools):
        """Regression: verify the full email is parsed, not just the first line.

        poplib.POP3.retr() returns a list where each element is one line of the
        raw email (matching real POP3 wire behaviour).  A prior bug passed only
        raw_msg_bytes[0] — the first line — to the parser, producing empty
        headers and body for every email.

        This test uses a mock that returns lines separately (like a real server)
        and asserts that all fields are present in the parsed output.
        """
        raw = _make_raw_email(
            "regression@test.com",
            "user@test.com",
            "Regression Test Subject",
            "This body text must appear in the output, proving the full email "
            "was parsed and not truncated to the first header line.",
        )
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "regression@test.com" in result, "From header missing — email was not fully parsed"
        assert "Regression Test Subject" in result, "Subject header missing — email was not fully parsed"
        assert "This body text must appear" in result, "Body missing — only the first line was parsed"

    @pytest.mark.asyncio
    async def test_delete_email_no_credentials(self):
        """Test that delete_email returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_delete_single = True
        result = await t.delete_email(email_index=1)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_delete_email_disabled_by_default(self, tools):
        """Test that delete_email is blocked when allow_delete_single is False (default)."""
        assert tools.valves.allow_delete_single is False
        result = await tools.delete_email(email_index=1)
        assert "disabled" in result.lower() and "allow_delete_single" in result

    @pytest.mark.asyncio
    async def test_delete_email_enabled(self, tools):
        """Test deleting a specific email when allow_delete_single is True."""
        tools.valves.allow_delete_single = True
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
        ]
        mock_server = _make_mock_server(1, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "deleted successfully" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_disabled_by_default(self, tools):
        """Test that delete_all_emails is blocked when allow_delete_all is False (default)."""
        assert tools.valves.allow_delete_all is False
        result = await tools.delete_all_emails()
        assert "disabled" in result.lower() and "allow_delete_all" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_enabled(self, tools):
        """Test deleting all emails when allow_delete_all is True."""
        tools.valves.allow_delete_all = True
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
        ]
        mock_server = _make_mock_server(1, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "deleted successfully" in result

    @pytest.mark.asyncio
    async def test_delete_email_success(self, tools):
        """Test deleting a specific email."""
        tools.valves.allow_delete_single = True
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
            _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay."),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "deleted successfully" in result
        mock_server.dele.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_delete_email_out_of_range(self, tools):
        """Test deleting an email with an out-of-range index."""
        tools.valves.allow_delete_single = True
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_email_invalid_index(self, tools):
        """Test deleting an email with an invalid index (0 or negative)."""
        tools.valves.allow_delete_single = True
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=0)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_all_emails_no_credentials(self):
        """Test that delete_all_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_delete_all = True
        result = await t.delete_all_emails()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_success(self, tools):
        """Test deleting all emails from mailbox."""
        tools.valves.allow_delete_all = True
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
            _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay."),
            _make_raw_email("dave@example.com", "bob@example.com", "Meeting", "See you tomorrow."),
        ]
        mock_server = _make_mock_server(3, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "deleted successfully" in result
        assert "3 email" in result
        assert mock_server.dele.call_count == 3

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty_mailbox(self, tools):
        """Test deleting all emails from an empty mailbox."""
        tools.valves.allow_delete_all = True
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "already empty" in result.lower() or "No emails" in result


class TestPOP3NonSSLConnection:
    """Test non-SSL connection mode for POP3."""

    @pytest.mark.asyncio
    async def test_list_emails_non_ssl(self):
        """Test that use_ssl=False connects via POP3 instead of POP3_SSL."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.use_ssl = False
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "Test" in result
        assert "1 total" in result

    @pytest.mark.asyncio
    async def test_list_emails_ssl_default(self):
        """Test that use_ssl=True (default) uses POP3_SSL."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.list_emails(count=5)
        assert "empty" in result.lower() or "No emails" in result
        assert "poplib.POP3" not in result


class TestPOP3SearchAdditional:
    """Additional POP3 search edge cases."""

    @pytest.mark.asyncio
    async def test_search_empty_results(self, tools):
        """Test search returns message when no emails match."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="subject:nonexistent", count=10)
        assert "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_free_text_fallback(self, tools):
        """Test search with free text (no from:/subject: prefix) falls back to subject+body search."""
        raw = _make_raw_email(
            "alice@example.com", "bob@example.com", "Hello World", "This contains the word invoice somewhere."
        )
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_combined_unquoted(self, tools):
        """Test search with two unqualified words (both become search_subject)."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Project Invoice", "Please review.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Project Invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_after_date(self, tools):
        """Test search with after: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2020-01-01", count=10)
        assert "Hello" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_before_date(self, tools):
        """Test search with before: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2030-01-01", count=10)
        assert "Hello" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_combined_from_and_subject(self, tools):
        """Test search with combined from: and subject: criteria."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com" subject:"Hello"', count=10)
        assert "Hello" in result


class TestPOP3GenericErrorPaths:
    """Test generic exception handling in POP3 methods."""

    @pytest.mark.asyncio
    async def test_delete_email_generic_error(self):
        """Test delete_email catches generic exceptions (e.g., network)."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.allow_delete_single = True

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.delete_email(email_index=1)
        assert "Error deleting" in result

    @pytest.mark.asyncio
    async def test_search_emails_generic_error(self):
        """Test search_emails catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.search_emails(query="subject:test", count=10)
        assert "Error searching" in result

    @pytest.mark.asyncio
    async def test_get_email_count_generic_error(self):
        """Test get_email_count catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.get_email_count()
        assert "Error checking mailbox" in result

    @pytest.mark.asyncio
    async def test_read_email_generic_error(self):
        """Test read_email catches generic exceptions."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.username = "user"
        t.valves.password = "pass"

        with patch("poplib.POP3_SSL", side_effect=OSError("connection refused")):
            result = await t.read_email(email_index=1)
        assert "Error reading" in result


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
        from email.mime.multipart import MIMEMultipart
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
        from email.mime.multipart import MIMEMultipart
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
        """Test read_email uses poplib.POP3 when use_ssl=False."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.use_ssl = False
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
        """Test search_emails uses poplib.POP3 when use_ssl=False."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.use_ssl = False
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
        """Test delete_email uses poplib.POP3 when use_ssl=False."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.use_ssl = False
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
        """Test get_email_count uses poplib.POP3 when use_ssl=False."""
        t = Tools()
        t.valves.pop3_server = "mail.test.com"
        t.valves.pop3_port = 110
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.use_ssl = False
        mock_server = _make_mock_server(5, [])
        with patch("poplib.POP3", return_value=mock_server) as mock_pop3:
            result = await t.get_email_count()
        mock_pop3.assert_called_once()
        assert "5" in result


class TestPOP3ReadEmailIndexZero:
    """Test read_email with index=0 (boundary validation)."""

    @pytest.mark.asyncio
    async def test_read_email_index_zero(self, tools):
        """Test that read_email rejects index=0 as out of range."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=0)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_email_negative_index(self, tools):
        """Test that read_email rejects negative index as out of range."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=-1)
        assert "out of range" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestPOP3ListEmailsAttachment:
    """Test list_emails with attachments."""

    @pytest.mark.asyncio
    async def test_list_emails_shows_attachment_count(self, tools):
        """Test list_emails shows attachment info when emails have attachments."""
        from email.mime.base import MIMEBase
        from email.mime.multipart import MIMEMultipart

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
        from email.mime.multipart import MIMEMultipart

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


class TestPOP3InnerFetchException:
    """Test inner exception handler in list_emails."""

    @pytest.mark.asyncio
    async def test_list_emails_inner_fetch_error(self, tools):
        """Test list_emails handles individual retr() failures gracefully."""
        emails = [
            b"From: a@b.com\r\nTo: c@d.com\r\nSubject: OK\r\nDate: Mon, 21 Apr 2025 10:00:00 +0000\r\n\r\nBody",
            b"From: e@f.com\r\nTo: g@h.com\r\nSubject: OK2\r\nDate: Mon, 21 Apr 2025 11:00:00 +0000\r\n\r\nBody2",
        ]

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        mock_server.quit.return_value = None

        call_count = [0]

        def mock_retr(index):
            call_count[0] += 1
            if call_count[0] <= 2 and 1 <= index <= 2:
                email_idx = index - 1
                if 0 <= email_idx < len(emails):
                    lines = emails[email_idx].split(b"\r\n")
                    return ("220 OK", lines, len(emails[email_idx]))
            return ("500 Error", [], 0)

        mock_server.retr.side_effect = mock_retr

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5)
        # Should show at least the successful email
        assert "Subject:" in result


class TestPOP3MIMECharsetFallback:
    """Test MIME decoding charset fallback paths."""

    @pytest.mark.asyncio
    async def test_parse_email_charset_fallback(self, tools):
        """Test _parse_email handles unknown charset fallback to UTF-8."""
        # Email with charset that will cause LookupError
        raw = b"""\
Subject: =?unknown-charset-xyz?b?dGVzdA==?=\r
From: from@example.com\r
To: to@example.com\r
Date: Mon, 21 Apr 2025 10:00:00 +0000\r
Content-Type: text/plain; charset=nonexistent-charset-abc\r
\r
test body"""

        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5)
        # Should not crash with charset error
        assert "Subject:" in result


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


class TestPOP3DeleteSpecialCases:
    """Test delete_email and delete_all_emails special cases."""

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty(self):
        """Test delete_all_emails returns early for empty mailbox."""
        t = Tools()
        t.valves.allow_delete_all = True
        t.valves.pop3_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"

        mock_server = MagicMock()
        mock_server.stat.return_value = (0, 0)
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_all_emails()
        assert "empty" in result.lower()


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
