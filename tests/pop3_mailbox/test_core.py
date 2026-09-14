"""Auto-generated test module."""

import poplib
from unittest.mock import MagicMock, patch

import pytest

from pop3_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


class TestPOP3MailboxTool:
    """Test suite for POP3 Mailbox Manager tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method,args,valve"),
        [
            ("list_emails", {"count": 5}, None),
            ("delete_email", {"email_index": 1}, "allow_delete_single"),
            ("delete_all_emails", {}, "allow_delete_all"),
        ],
    )
    # Given a POP3 tool with no credentials configured / When any mailbox operation is invoked / Then the result reports missing credentials
    async def test_operation_requires_no_credentials(self, method, args, valve):
        """Test that operations fail when credentials are missing."""
        t = Tools()
        if valve:
            setattr(t.valves, valve, True)
        result = await getattr(t, method)(**args)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    # Given a POP3 mailbox with zero emails / When list_emails is called / Then the result reports an empty mailbox
    async def test_list_emails_empty_mailbox(self, tools):
        """Test listing emails in an empty mailbox."""
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.list_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    # Given a POP3 mailbox with two messages / When list_emails is called / Then the result contains both senders, subjects, and the total count
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
    # Given a POP3 mailbox with two messages / When read_email is called for index 1 / Then the result contains the sender, subject, and body
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
    # Given a POP3 mailbox with two emails / When read_email is called with index 99 / Then the result reports an out-of-range index
    async def test_read_email_out_of_range(self, tools):
        """Test reading an email with an out-of-range index."""
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("query", "expected_in", "expected_not"),
        [
            ("from:alice@example.com", ["alice@example.com"], ["carol@example.com"]),
            ("subject:Invoice", ["carol@example.com"], ["alice@example.com"]),
            ("subject:invoice", ["carol@example.com"], ["alice@example.com"]),
        ],
    )
    # Given a POP3 mailbox with two messages / When search_emails is called with a query type / Then matches appear and non-matches do not
    async def test_search_emails_by_query_type(self, tools, query, expected_in, expected_not):
        """Test searching emails by query type (from/subject/free-text)."""
        emails = [
            _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob."),
            _make_raw_email("carol@example.com", "bob@example.com", "Invoice #123", "Please pay."),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query=query, count=10)
        for item in expected_in:
            assert item in result
        for item in expected_not:
            assert item not in result

    @pytest.mark.asyncio
    # Given a POP3 mailbox with five emails / When get_email_count is called / Then the result contains the count
    async def test_get_email_count(self, tools):
        """Test getting the total email count."""
        mock_server = _make_mock_server(5, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "5" in result

    @pytest.mark.asyncio
    # Given a POP3 server that rejects authentication / When get_email_count is called / Then the result reports a POP3 or Authentication error
    async def test_pop3_connection_error(self, tools):
        """Test handling of POP3 connection errors."""

        mock_server = MagicMock()
        mock_server.stat.side_effect = poplib.error_proto("535 Authentication failed")
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.get_email_count()
        assert "POP3 Error" in result or "Authentication" in result

    @pytest.mark.asyncio
    # Given plain, empty, and None header inputs / When _decode_mime_header is called / Then it returns the decoded string, and empty string for empty or None
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
    # Given a raw RFC822 email / When _parse_email is called / Then the parsed dict has from, subject, body, attachment, and headers fields
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
    # Given a raw email returned as separate lines / When read_email is called / Then sender, subject, and body are all present
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
    @pytest.mark.parametrize(
        "valve_name,method,args",
        [
            ("allow_delete_single", "delete_email", {"email_index": 1}),
            ("allow_delete_all", "delete_all_emails", {}),
        ],
    )
    # Given a fresh POP3 tool with write valves at their defaults / When a delete operation is invoked / Then the valve is False and the result reports the operation is disabled
    async def test_delete_ops_disabled_by_default(self, valve_name, method, args):
        """Test that delete operations are blocked when valves default to False."""
        t = Tools()
        assert getattr(t.valves, valve_name) is False
        result = await getattr(t, method)(**args)
        assert "disabled" in result.lower() and valve_name in result

    @pytest.mark.asyncio
    # Given a POP3 mailbox with one email and allow_delete_single enabled / When delete_email is called / Then the result reports successful deletion
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
    # Given a POP3 mailbox with one email and allow_delete_all enabled / When delete_all_emails is called / Then the result reports successful deletion
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
    # Given a POP3 mailbox with one selectable email / When the tool deletes that email with write permission enabled / Then the result reports successful deletion
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

    @pytest.mark.asyncio
    # Given an enabled allow_delete_single and a POP3 mailbox / When delete_email is called with index 99 / Then the result reports an out-of-range index
    async def test_delete_email_out_of_range(self, tools):
        """Test deleting an email with an out-of-range index."""
        tools.valves.allow_delete_single = True
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    # Given an enabled allow_delete_single and a POP3 mailbox / When delete_email is called with index 0 / Then the result reports an out-of-range index
    async def test_delete_email_invalid_index(self, tools):
        """Test deleting an email with an invalid index (0 or negative)."""
        tools.valves.allow_delete_single = True
        mock_server = _make_mock_server(2, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=0)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    # Given a POP3 mailbox with selectable emails / When the tool deletes all emails with the required write permission enabled / Then the result reports successful deletion of the mailbox contents
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

    @pytest.mark.asyncio
    # Given an enabled allow_delete_all and an empty POP3 mailbox / When delete_all_emails is called / Then the result reports the mailbox is already empty
    async def test_delete_all_emails_empty_mailbox(self, tools):
        """Test deleting all emails from an empty mailbox."""
        tools.valves.allow_delete_all = True
        mock_server = _make_mock_server(0, [])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "already empty" in result.lower() or "No emails" in result
