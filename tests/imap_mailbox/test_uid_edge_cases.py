"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import _make_mock_server, _make_raw_email


class TestIMAPUidDataNonePath:
    """Test edge cases where uid_data[0] is None."""

    @pytest.mark.asyncio
    async def test_refresh_uid_index_uid_data_none(self, tools):
        """Test _refresh_uid_index returns empty dict when uid_data[0] is None."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [None])  # Server returns None instead of empty list
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        from imap_mailbox import Tools as IMAPTools

        t = IMAPTools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            conn = t._connect()
            uid_map = t._refresh_uid_index(conn)
            conn.close()
        assert uid_map == {}

    @pytest.mark.asyncio
    async def test_list_emails_non_imap_fetch_error(self, tools):
        """Test list_emails handles non-IMAPException fetch failures (inner exception handler at 527-528)."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", b"1")
            elif cmd == "fetch":
                raise RuntimeError("unexpected error, not IMAP exception")
            return ("OK", [b"", b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=10)
        # Should show error for the UID but not crash
        assert "Error" in result or "INBOX" in result

    @pytest.mark.asyncio
    async def test_search_emails_free_text_max_count(self, tools):
        """Test search_emails stops fetching after hitting count limit in free-text search (line 734)."""
        raw1 = _make_raw_email("a@example.com", "b@example.com", "Match One", "contains word")
        raw2 = _make_raw_email("c@example.com", "d@example.com", "Match Two", "contains word")
        raw3 = _make_raw_email("e@example.com", "f@example.com", "Match Three", "contains word")
        emails = [(raw1, "1"), (raw2, "2"), (raw3, "3")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="word", count=2, folder="INBOX")
        # Should find 2 matches (count limit), not all 3
        assert "2 email" in result or "2 email" in result or "Found 2" in result


class TestIMAPSearchUidDataNone:
    """Test search_emails when uid_data[0] is None (server returned None instead of empty)."""

    @pytest.mark.asyncio
    async def test_search_emails_uid_data_none(self, tools):
        """Test search returns not found when server returns None for uid data."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [None])  # Server returns None (not b'' or empty string)
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"test"', folder="INBOX")
        assert "No emails found" in result


class TestIMAPSearchFreeTextEmpty:
    """Test search_emails free-text search where no emails match client-side filter."""

    @pytest.mark.asyncio
    async def test_search_free_text_no_client_match(self, tools):
        """Test search with free text where IMAP returns results but client filtering excludes all."""
        raw = _make_raw_email(
            "alice@example.com", "bob@example.com", "Hello World", "This email does not contain the word xyz"
        )
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="xyznotfoundxyz", count=10, folder="INBOX")
        assert "No emails found" in result


class TestIMAPSearchCombinedFilters:
    """Test search_emails combined filter edge cases."""

    @pytest.mark.asyncio
    async def test_search_emails_free_text_no_results(self, tools):
        """Test search_emails with free-text fallback returns 'No emails found'."""
        raw = _make_raw_email("sender@x.com", "recv@y.com", "Unrelated Subject", "completely different content")
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            else:
                return ("OK", [(b"1 IMAP2 UID 10", raw)])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="totally-missing-keyword-xyz-999", count=5, folder="INBOX")
        assert "No emails found" in result
