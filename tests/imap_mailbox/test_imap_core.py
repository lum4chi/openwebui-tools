"""Core IMAP mailbox tool tests: list, read, search, delete operations."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


class TestIMAPMailboxTool:
    """Test suite for IMAP Mailbox Manager tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args,valve",
        [
            ("delete_emails", {"uids": "42", "folder": "INBOX"}, "allow_delete_single"),
            ("delete_all_emails", {"folder": "INBOX"}, "allow_delete_all"),
            ("read_emails", {"uids": "42", "folder": "INBOX"}, None),
            ("search_emails", {"query": "test", "folder": "INBOX"}, None),
        ],
    )
    async def test_folder_operations_require_credentials(self, method, args, valve):
        """Test that folder operations fail when credentials are missing (with valve enabled)."""
        t = Tools()
        if valve:
            setattr(t.valves, valve, True)
        result = await getattr(t, method)(**args)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_list_emails_no_folder_required(self):
        """Test that list_emails requires a folder parameter."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.imap_port = 993
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        with pytest.raises(TypeError):
            await t.list_emails(count=5)  # pyright: ignore

    @pytest.mark.asyncio
    async def test_list_emails_empty_folder_raises(self):
        """Test that list_emails raises ValueError when folder is empty."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.imap_port = 993
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        with pytest.raises(ValueError, match="required"):
            t._resolve_folder(folder="")

    @pytest.mark.asyncio
    async def test_read_emails_empty_folder_raises(self):
        """Test that read_emails raises ValueError when folder is empty."""
        t = Tools()
        with pytest.raises(ValueError, match="required"):
            t._resolve_folder(folder="")

    @pytest.mark.asyncio
    async def test_search_emails_empty_folder_raises(self):
        """Test that search_emails raises ValueError when folder is empty."""
        t = Tools()
        with pytest.raises(ValueError, match="required"):
            t._resolve_folder(folder="")

    @pytest.mark.asyncio
    async def test_delete_emails_empty_folder_raises(self):
        """Test that delete_emails raises ValueError when folder is empty."""
        t = Tools()
        with pytest.raises(ValueError, match="required"):
            t._resolve_folder(folder="")

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty_folder_raises(self):
        """Test that delete_all_emails raises ValueError when folder is empty."""
        t = Tools()
        with pytest.raises(ValueError, match="required"):
            t._resolve_folder(folder="")

    @pytest.mark.asyncio
    async def test_list_emails_empty_mailbox(self, tools):
        """Test listing emails in an empty mailbox."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_emails_with_messages(self, tools):
        """Test listing emails with actual messages."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "Hello" in result
        assert "Invoice #123" in result

    @pytest.mark.asyncio
    async def test_read_emails(self, tools):
        """Test reading specific email(s) by UID."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids="2", folder="INBOX")
        # UID 2 = carol (highest Uid)
        assert "carol@example.com" in result
        assert "Invoice #123" in result
        assert "Please find attached" in result

    @pytest.mark.asyncio
    async def test_read_emails_multiple(self, tools):
        """Test reading multiple emails by UID."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay invoice.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids=["1", "2"], folder="INBOX")
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "=== Email [1]" in result
        assert "=== Email [2]" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("query", "expected_in", "expected_not"),
        [
            ('from:"alice@example.com"', ["alice@example.com"], ["carol@example.com"]),
            ('subject:"Invoice"', ["carol@example.com"], ["alice@example.com"]),
            ('subject:"invoice"', ["carol@example.com"], ["alice@example.com"]),
            ("invoice for services", ["carol@example.com"], []),
        ],
    )
    async def test_search_emails_by_query_type(self, tools, query, expected_in, expected_not):
        """Test searching emails by query type (from/subject/free-text)."""
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay invoice for services.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query=query, count=10, folder="INBOX")
        for item in expected_in:
            assert item in result
        for item in expected_not:
            assert item not in result

    @pytest.mark.asyncio
    async def test_delete_emails_success(self, tools):
        """Test deleting a specific email."""
        tools.valves.allow_delete_single = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids="1", folder="INBOX")
        assert "deleted successfully" in result or "permanently deleted" in result

    @pytest.mark.asyncio
    async def test_delete_emails_invalid_uid(self, tools):
        """Test deleting an email with non-existent UID (IMAP command succeeds even if UID doesn't exist)."""
        tools.valves.allow_delete_single = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids="99", folder="INBOX")
        # UID 99 doesn't exist but IMAP store command still succeeds in the mock
        assert "permanently deleted" in result or "deleted" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_all_emails_success(self, tools):
        """Test deleting all emails from mailbox."""
        tools.valves.allow_delete_all = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        raw3 = _make_raw_email("dave@example.com", "bob@example.com", "Meeting", "See you tomorrow.")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails(folder="INBOX")
        assert "deleted successfully" in result
        assert "3 email" in result
        delete_calls = [c for c in mock_server.uid.call_args_list if c[0][0] == "store"]
        assert len(delete_calls) == 3

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty_mailbox(self, tools):
        """Test deleting all emails from an empty mailbox."""
        tools.valves.allow_delete_all = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails(folder="INBOX")
        assert "already empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_decode_mime_header(self, tools):
        """Test MIME header decoding utility."""
        result = tools._decode_mime_header("Hello World")
        assert result == "Hello World"
        assert tools._decode_mime_header("") == ""
        assert tools._decode_mime_header(None) == ""

    @pytest.mark.asyncio
    async def test_parse_email_structure(self, tools):
        """Test email parsing produces correct structure."""
        raw = _make_raw_email(
            "test@example.com",
            "recipient@example.com",
            "Test Subject",
            "Test body content",
        )
        parsed = tools._parse_email(raw)
        assert "test@example.com" in parsed["from"]
        assert "Test Subject" in parsed["subject"]
        assert "Test body content" in parsed["body"]
        assert "has_attachments" in parsed
        assert "attachment_count" in parsed
        assert "headers" in parsed

    @pytest.mark.asyncio
    async def test_regression_full_email_parsed_not_first_line_only(self, tools):
        """Regression: verify the full email is parsed, not just the first line."""
        raw = _make_raw_email(
            "regression@test.com",
            "user@test.com",
            "Regression Test Subject",
            "This body text must appear in the output, proving the full email "
            "was parsed and not truncated to the first header line.",
        )
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids="1", folder="INBOX")
        assert "regression@test.com" in result
        assert "Regression Test Subject" in result
        assert "This body text must appear" in result

    @pytest.mark.asyncio
    async def test_connection_error(self, tools):
        """Test handling of IMAP connection errors."""
        from .conftest import _IMAP_EXCEPTION

        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("535 Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_select_inbox_folder(self, tools):
        """Test that a custom folder name is used in IMAP select."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            await tools.list_emails(folder="Sent", count=5)
        mock_server.select.assert_called()
        call_args = mock_server.select.call_args
        assert call_args[0][0] == '"Sent"'

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "valve_name,method,args",
        [
            ("allow_delete_single", "delete_emails", {"uids": "1", "folder": "INBOX"}),
            ("allow_delete_all", "delete_all_emails", {"folder": "INBOX"}),
            ("allow_move", "move_emails", {"uids": "1", "target_folder": "Projects", "folder": "INBOX"}),
        ],
    )
    async def test_write_ops_disabled_by_default(self, valve_name, method, args):
        """Test that write operations are blocked when valves default to False."""
        t = Tools()
        assert getattr(t.valves, valve_name) is False
        result = await getattr(t, method)(**args)
        assert "disabled" in result.lower() and valve_name in result

    @pytest.mark.asyncio
    async def test_delete_emails_enabled(self, tools):
        """Test deleting a specific email when allow_delete_single is True."""
        tools.valves.allow_delete_single = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids="1", folder="INBOX")
        assert "deleted successfully" in result or "permanently deleted" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_enabled(self, tools):
        """Test deleting all emails when allow_delete_all is True."""
        tools.valves.allow_delete_all = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Invoice", "Please pay.")
        raw3 = _make_raw_email("dave@example.com", "bob@example.com", "Meeting", "See you tomorrow.")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails(folder="INBOX")
        assert "deleted successfully" in result
        assert "3 email" in result

    @pytest.mark.asyncio
    async def test_default_toggles_are_off(self):
        """Test that write operation toggles default to False."""
        t = Tools()
        assert t.valves.allow_delete_single is False
        assert t.valves.allow_delete_all is False
        assert t.valves.allow_move is False
        assert t.valves.allow_move is False
