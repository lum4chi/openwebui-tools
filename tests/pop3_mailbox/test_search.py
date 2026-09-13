"""POP3 search tests: query parsing, date filters, and free-text quirk pins."""

from unittest.mock import patch

import pytest

from .conftest import _make_mock_server, _make_raw_email


class TestPOP3SearchAdditional:
    """Additional POP3 search edge cases."""

    @pytest.mark.asyncio
    async def test_search_empty_results(self, tools):
        # Given a POP3 mailbox containing one email from alice@example.com
        # When the tool searches with subject:nonexistent
        # Then the result reports that no emails were found
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="subject:nonexistent", count=10)
        assert "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_free_text_fallback(self, tools):
        # Given a POP3 mailbox containing one email whose body contains "invoice"
        # When the tool searches with the free-text query "invoice"
        # Then the email is returned in the result list
        raw = _make_raw_email(
            "alice@example.com", "bob@example.com", "Hello World", "This contains the word invoice somewhere."
        )
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_combined_unquoted(self, tools):
        # Given a POP3 mailbox containing one email with subject "Project Invoice"
        # When the tool searches with the unquoted two-word query "Project Invoice"
        # Then the email is returned in the result list
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Project Invoice", "Please review.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Project Invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_free_text_last_word_wins(self, tools):
        # Given a POP3 mailbox containing two emails, one whose subject matches only the
        # first query word and one whose subject matches only the last query word
        # When the tool searches with the unquoted two-word query "Project Invoice"
        # Then only the email matching the last word "invoice" is returned
        # Quirk pin: free-text query words overwrite search_subject one by one, so only the
        # last word is filtered; the naive AND expectation (both words match) fails against
        # this behaviour. Source behaviour is documented here, not fixed.
        emails = [
            _make_raw_email("a@example.com", "b@example.com", "Project Update", "Nothing to see."),
            _make_raw_email("c@example.com", "d@example.com", "Invoice Notice", "Nothing to see."),
        ]
        mock_server = _make_mock_server(2, emails)
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Project Invoice", count=10)
        assert "Found 1 email(s)" in result and "Invoice Notice" in result and "Project Update" not in result

    @pytest.mark.asyncio
    async def test_search_after_date(self, tools):
        # Given a POP3 email with a parseable date is stored in the mock mailbox
        # When the tool searches with an after: date that includes that email
        # Then the email is returned in the result list
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2020-01-01", count=10)
        assert "Found 1 email(s)" in result and "Hello" in result

    @pytest.mark.asyncio
    async def test_search_before_date(self, tools):
        # Given a POP3 email with a parseable date is stored in the mock mailbox
        # When the tool searches with a before: date that includes that email
        # Then the email is returned in the result list
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2030-01-01", count=10)
        assert "Found 1 email(s)" in result and "Hello" in result

    @pytest.mark.asyncio
    async def test_search_quoted_criteria_no_match(self, tools):
        # Given a POP3 mailbox containing one email from alice@example.com with subject "Hello"
        # When the tool searches with from:"alice@example.com" subject:"Hello"
        # Then no emails are found because the quoted criteria tokens are matched literally
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com" subject:"Hello"', count=10)
        assert "No emails found" in result
