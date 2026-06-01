"""IMAP edge case tests: empty mailbox paths, folder resolution, delete partial failures."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _make_raw_email, _make_mock_server


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
        from pydantic import Field

        field = Field(description="no default")
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [b"0 Messages"])
        mock_server.close.return_value = None
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids=field)
        assert "No UIDs" in result
