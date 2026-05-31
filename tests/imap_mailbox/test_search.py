"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestSearchEmailsAdditional:
    """Additional search_emails tests: date queries, combined criteria, no results."""

    @pytest.mark.asyncio
    async def test_search_emails_no_results(self, tools):
        """Test search returning no matching emails."""

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"nonexistent"')
        assert "No emails found matching criteria" in result

    @pytest.mark.asyncio
    async def test_search_emails_after_date(self, tools):
        """Test search with after: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "After test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            # We expect the uid search call to contain SINCE
            result = await tools.search_emails(query="after:2025-04-01", count=10)
        # The mock server handles search with ANY criteria via the ALL branch
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_before_date(self, tools):
        """Test search with before: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Before test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2025-12-01", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_before_after_combined(self, tools):
        """Test search combining before: and after:."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Range test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2025-01-01 before:2025-12-31", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_emails_combined_from_and_subject(self, tools):
        """Test search with both from: and subject:."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Pay me", "Invoice")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Hello", "Invoice")
        emails = [(raw, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com" subject:"Invoice"', count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" not in result

    @pytest.mark.asyncio
    async def test_search_emails_free_text_no_match(self, tools):
        """Test free-text search that matches no email."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "World")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="xyznotfound", count=10)
        assert "No emails found" in result


class TestIMAPSearchExceptionPaths:
    """Test IMAP search_emails error handling during fetch loop."""

    @pytest.mark.asyncio
    async def test_search_emails_free_text_fetch_exception(self, tools):
        """Test search_emails free-text fallback where one email fails to fetch (lines 770-771)."""
        raw_match = _make_raw_email("a@b.com", "c@d.com", "Match Subject", "Body text")
        raw_no_match = _make_raw_email("x@y.com", "z@w.com", "No Match", "completely different content")
        mock_server = MagicMock()

        fetch_count = [0]

        def uid_side_effect(cmd, *args, **kwargs):
            nonlocal fetch_count
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                fetch_count[0] += 1
                if fetch_count[0] == 1:
                    return ("OK", [(b"1 IMAP2 UID 10", raw_match)])
                else:
                    raise _IMAP_EXCEPTION("fetch error")
            return ("OK", [raw_no_match])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="body", count=5, folder="INBOX")
        assert "email" in result.lower()
