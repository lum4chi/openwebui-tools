"""Auto-generated test module."""
import os
import poplib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


from unittest.mock import MagicMock, patch

from pop3_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


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

