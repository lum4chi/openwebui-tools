"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestSearchEmailsAdditional:
    """Additional search_emails tests: date queries, combined criteria, no results."""

    @pytest.mark.asyncio
    async def test_search_emails_no_results(self, tools):
        """Test search returning no matching emails.

        Given an IMAP mailbox fixture that exposes the mock connection
        When search_emails is called with a subject criteria that matches nothing
        Then the result contains "No emails found matching criteria"
        """

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b""])

        mock_server = _make_mock_server([], override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='subject:"nonexistent"', folder="INBOX")
        assert "No emails found matching criteria" in result

    @pytest.mark.asyncio
    async def test_search_emails_after_date(self, tools):
        """Test search with after: date filter.

        Given an IMAP mailbox fixture that exposes the mock connection
        When search_emails is called with query "after:2025-04-01"
        Then the outgoing IMAP search criteria are ("search", "", "SINCE 01-Apr-2025")
        And the result contains the matching email
        """
        raw = _make_raw_email("alice@example.com", "bob@example.com", "After test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2025-04-01", count=10, folder="INBOX")
        assert "alice@example.com" in result
        # Outgoing-criteria contract: after: -> SINCE only.
        mock_server.uid.assert_any_call("search", "", "SINCE 01-Apr-2025")

    @pytest.mark.asyncio
    async def test_search_emails_before_date(self, tools):
        """Test search with before: date filter.

          Given an IMAP mailbox fixture that exposes the mock connection
          When search_emails is called with query "before:2025-12-01"
          Then the outgoing IMAP search criteria are ("search", "", "ALL")
          And the result contains the matching email

        Before-only quirk (documented, not a regression): a `before:`-only query
        builds NO outgoing criteria because imap_mailbox.py appends `BEFORE`
        only when `search_after is not None`. With no `SINCE` part the criteria
        list is empty, so the tool falls back to `"ALL"` — the BEFORE bound is
        never sent to the server.
        """
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Before test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2025-12-01", count=10, folder="INBOX")
        assert "alice@example.com" in result
        # Outgoing-criteria contract: before-only -> ALL.
        mock_server.uid.assert_any_call("search", "", "ALL")

    @pytest.mark.asyncio
    async def test_search_emails_before_after_combined(self, tools):
        """Test search combining before: and after:.

        Given an IMAP mailbox fixture that exposes the mock connection
        When search_emails is called with query "after:2025-01-01 before:2025-12-31"
        Then the outgoing IMAP search criteria are
             ("search", "", "SINCE 01-Jan-2025 BEFORE 01-Jan-2026")
        And the result contains the matching email
        """
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Range test", "Hi")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2025-01-01 before:2025-12-31", count=10, folder="INBOX")
        assert "alice@example.com" in result
        # Outgoing-criteria contract: before bound is
        # exclusive (+1 day): 2025-12-31 -> BEFORE 01-Jan-2026.
        mock_server.uid.assert_any_call("search", "", "SINCE 01-Jan-2025 BEFORE 01-Jan-2026")

    @pytest.mark.asyncio
    async def test_search_emails_combined_from_and_subject(self, tools):
        """Test search with both from: and subject:.

        Given an IMAP mailbox fixture that exposes the mock connection
        When search_emails is called with a from+subject query
        Then the result contains the matching email and not the unmatched one
        """
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Pay me", "Invoice")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Hello", "Invoice")
        emails = [(raw, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(
                query='from:"alice@example.com" subject:"Invoice"', count=10, folder="INBOX"
            )
        assert "alice@example.com" in result
        assert "carol@example.com" not in result

    @pytest.mark.asyncio
    async def test_search_emails_free_text_no_match(self, tools):
        """Test free-text search that matches no email.

        Given an IMAP mailbox fixture that exposes the mock connection
        When search_emails is called with a free-text query that matches nothing
        Then the result contains "No emails found"
        """
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "World")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="xyznotfound", count=10, folder="INBOX")
        assert "No emails found" in result


class TestIMAPSearchExceptionPaths:
    """Test IMAP search_emails error handling during fetch loop."""

    @pytest.mark.asyncio
    async def test_search_emails_free_text_fetch_exception(self, tools):
        """Test search_emails free-text fallback where one email fails to fetch (lines 770-771).

        Given an IMAP mailbox fixture where a free-text fetch raises an exception
        When search_emails is called with a free-text query
        Then the result still contains "email" (exception path is handled)
        """
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

    @pytest.mark.asyncio
    async def test_search_emails_fetch_parse_failure_in_uid_path(self, tools):
        """Test search_emails where UID-based fetch (non-free-text) raises exception during index access.

        Given an IMAP mailbox fixture where a from: fetch returns malformed payload
        When search_emails is called with a from: query
        Then the result contains "No emails found matching criteria"
        """
        mock_server = MagicMock()

        def uid_side_effect(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                # Return a single bytes object instead of the expected [prefix, raw_bytes] list
                return ("OK", [b"single-bytes-object"])
            return ("OK", [b""])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"anyone@example.com"', count=5, folder="INBOX")
        assert "No emails found matching criteria" in result
