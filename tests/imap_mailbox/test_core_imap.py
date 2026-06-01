"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestIMAPMailboxTool:
    """Test suite for IMAP Mailbox Manager tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,args,valve",
        [
            ("delete_emails", {"uids": "42"}, "allow_delete_single"),
            ("delete_all_emails", {}, "allow_delete_all"),
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
            result = await tools.read_emails(uids="2")
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
            result = await tools.read_emails(uids=["1", "2"])
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
            result = await tools.search_emails(query=query, count=10)
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
            result = await tools.delete_emails(uids="1")
        assert "deleted successfully" in result or "permanently deleted" in result

    @pytest.mark.asyncio
    async def test_delete_emails_invalid_uid(self, tools):
        """Test deleting an email with non-existent UID (IMAP command succeeds even if UID doesn't exist)."""
        tools.valves.allow_delete_single = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids="99")
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
            result = await tools.delete_all_emails()
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
            result = await tools.delete_all_emails()
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
            result = await tools.read_emails(uids="1")
        assert "regression@test.com" in result
        assert "Regression Test Subject" in result
        assert "This body text must appear" in result

    @pytest.mark.asyncio
    async def test_connection_error(self, tools):
        """Test handling of IMAP connection errors."""
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
            ("allow_delete_single", "delete_emails", {"uids": "1"}),
            ("allow_delete_all", "delete_all_emails", {}),
            ("allow_move", "move_emails", {"uids": "1", "target_folder": "Projects"}),
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
            result = await tools.delete_emails(uids="1")
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
            result = await tools.delete_all_emails()
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


class TestIMAPEmptyMailboxPaths:
    """Test empty mailbox edge cases that hit early-return guards."""

    @pytest.mark.asyncio
    async def test_read_emails_empty_mailbox(self, tools):
        """Test read_emails returns early when mailbox is empty (uid_map is empty dict)."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids="1")
        assert "empty" in result.lower() or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_emails_no_credentials(self):
        """Test search_emails returns error without credentials."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        result = await t.search_emails(query="test", count=5)
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_delete_emails_no_server(self):
        """Test delete_emails returns server error when imap_server not configured."""
        t = Tools()
        t.valves.allow_delete_single = True
        t.valves.username = "u"
        t.valves.password = "p"
        result = await t.delete_emails(uids="1")
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_no_credentials(self):
        """Test delete_all_emails returns error without credentials."""
        t = Tools()
        t.valves.allow_delete_all = True
        t.valves.imap_server = "mail.example.com"
        result = await t.delete_all_emails()
        assert "Error" in result and "credentials" in result


class TestResolveFolder:
    """Test the _resolve_folder helper."""

    @pytest.mark.asyncio
    async def test_resolve_folder_explicit(self, tools):
        """Test _resolve_folder returns explicit folder."""
        result = tools._resolve_folder(folder="Custom/Folder")
        assert result == "Custom/Folder"

    @pytest.mark.asyncio
    async def test_resolve_folder_empty_fallsback_to_valve(self, tools):
        """Test _resolve_folder falls back to inbox_folder valve when folder is empty."""
        tools.valves.inbox_folder = "MyInbox"
        result = tools._resolve_folder(folder="")
        assert result == "MyInbox"

    @pytest.mark.asyncio
    async def test_resolve_folder_none_fallsback_to_valve(self, tools):
        """Test _resolve_folder falls back to inbox_folder when folder is None."""
        tools.valves.inbox_folder = "CustomInbox"
        result = tools._resolve_folder(folder=None)
        assert result == "CustomInbox"


class TestDeleteEmailsPartialFailures:
    """Test delete_emails partial failure and multi-email paths."""

    @pytest.mark.asyncio
    async def test_delete_emails_multi_success(self, tools):
        """Test deleting multiple emails by UID (multi-email success path)."""
        tools.valves.allow_delete_single = True
        raw1 = _make_raw_email("a@b.com", "c@d.com", "Msg 1", "Body 1")
        raw2 = _make_raw_email("a@b.com", "c@d.com", "Msg 2", "Body 2")
        raw3 = _make_raw_email("a@b.com", "c@d.com", "Msg 3", "Body 3")
        mock_server = _make_mock_server([(raw1, "10"), (raw2, "11"), (raw3, "12")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids=["10", "11", "12"])
        assert "3 email(s)" in result
        assert "INBOX" in result

    @pytest.mark.asyncio
    async def test_delete_emails_partial_store_failure(self, tools):
        """Test delete_emails reports failures when store fails for some UIDs."""

        def uid_side_effect(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1 2"])
            if cmd == "store":
                uid = (
                    criteria
                    if isinstance(criteria, str)
                    else str(criteria[0])
                    if isinstance(criteria, (list, tuple))
                    else str(criteria)
                )
                if uid == "2":
                    raise Exception("no such UID")
                return ("OK", [b"FLAGS (\\Deleted)"])
            if cmd == "expunge":
                return ("OK", [b"EXPUNGE"])
            return ("OK", [b""])

        tools.valves.allow_delete_single = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")], override_uid=uid_side_effect)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_emails(uids=["1", "2"])
        assert "permanently deleted" in result.lower() or "1" in result
        assert "Failed" in result or "2" in result

    @pytest.mark.asyncio
    async def test_read_emails_invalid_uid(self, tools):
        """Test read_emails returns error for completely invalid UID."""
        result = await tools.read_emails(uids="xyz")
        assert (
            "Error" in result
            or "Invalid" in result
            or "No UIDs" in result
            or "not found" in result.lower()
            or "no such" in result.lower()
        )

    @pytest.mark.asyncio
    async def test_read_emails_empty_uids(self, tools):
        """Test read_emails with UIDs that resolve to empty list."""
        from unittest.mock import MagicMock

        from pydantic import Field

        field = Field(description="no default")
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [b"0 Messages"])
        mock_server.close.return_value = None
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids=field)
        assert "No UIDs" in result
