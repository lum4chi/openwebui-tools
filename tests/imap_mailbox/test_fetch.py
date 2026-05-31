"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

from imap_mailbox import Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)

from unittest.mock import MagicMock, patch

from .conftest import _make_raw_email


class TestFetchEmailByUid:
    """Test _fetch_email_by_uid method."""

    @pytest.mark.asyncio
    async def test_fetch_email_by_uid_success(self):
        """Test _fetch_email_by_uid returns parsed email dict."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"
        mock_server = MagicMock()
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")

        # The _fetch_email_by_uid method calls conn.uid("fetch", uid, "(RFC822)")
        # and expects a tuple of (status, raw_data) where raw_data[0] is [prefix, email_bytes]
        mock_server.uid.return_value = ("OK", [[b"1 (RFC822 {}", raw]])

        result = t._fetch_email_by_uid(mock_server, "1")
        assert result is not None
        assert result["from"] == "a@b.com"

    @pytest.mark.asyncio
    async def test_fetch_email_by_uid_empty_raw_data(self):
        """Test _fetch_email_by_uid when raw_data is empty returns None."""
        t = Tools()
        # Make conn.uid return empty list as raw_data (simulates no RFC822 data)
        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [])
        result = t._fetch_email_by_uid(mock_conn, "1")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_email_by_uid_connection_error(self):
        """Test _fetch_email_by_uid returns None when conn.uid raises an exception (line 512-513)."""
        t = Tools()
        mock_conn = MagicMock()
        mock_conn.uid.side_effect = RuntimeError("connection lost")
        result = t._fetch_email_by_uid(mock_conn, "1")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_email_by_uid_parse_error(self):
        """Test _fetch_email_by_uid returns None when _parse_email raises an exception (line 519-520)."""
        t = Tools()
        mock_conn = MagicMock()
        mock_conn.uid.return_value = ("OK", [[b"1 (RFC822 {}", b"fake"]])
        with patch.object(t, "_parse_email", side_effect=ValueError("parse failed")):
            result = t._fetch_email_by_uid(mock_conn, "1")
        assert result is None




class TestSearchEmailsFetchNone:
    """Test search_emails when _fetch_email_by_uid returns None (line 792)."""

    @pytest.mark.asyncio
    async def test_search_emails_some_fetch_failures(self):
        """Test search_emails where some candidate fetches return None, others succeed (line 792).

        Uses a non-free-text query (from:) so it enters the else branch at line 793 which
        calls _fetch_email_by_uid (the patched method) instead of the free-text branch
        which calls conn.uid("fetch") directly.
        """
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()

        def uid_side_effect(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1 2 3"])
            return ("OK", [[b"1 (RFC822 {}", b"fake"]])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"3"])

        call_order = []

        mock_fetch = MagicMock()

        def fetch_side(*args, **kwargs):
            call_order.append(args)
            if len(call_order) <= 2:
                return None
            raw = _make_raw_email("sender@test.com", "user@test.com", "Found Email", "Matched content")
            return t._parse_email(raw)

        mock_fetch.side_effect = fetch_side

        with patch.object(t, "_fetch_email_by_uid", mock_fetch), patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.search_emails(query="from:sender@test.com", count=5)
        assert "Found Email" in result
        assert len(call_order) == 3

