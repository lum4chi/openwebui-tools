"""Auto-generated test module."""

from unittest.mock import patch

import pytest

from .conftest import _make_mock_server, _make_raw_email


class TestPOP3SearchAdditional:
    """Additional POP3 search edge cases."""

    @pytest.mark.asyncio
    async def test_search_empty_results(self, tools):
        """Test search returns message when no emails match."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="subject:nonexistent", count=10)
        assert "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_free_text_fallback(self, tools):
        """Test search with free text (no from:/subject: prefix) falls back to subject+body search."""
        raw = _make_raw_email(
            "alice@example.com", "bob@example.com", "Hello World", "This contains the word invoice somewhere."
        )
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_combined_unquoted(self, tools):
        """Test search with two unqualified words (both become search_subject)."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Project Invoice", "Please review.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Project Invoice", count=10)
        assert "alice@example.com" in result

    @pytest.mark.asyncio
    async def test_search_after_date(self, tools):
        """Test search with after: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="after:2020-01-01", count=10)
        assert "Hello" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_before_date(self, tools):
        """Test search with before: date filter."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query="before:2030-01-01", count=10)
        assert "Hello" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_combined_from_and_subject(self, tools):
        """Test search with combined from: and subject: criteria."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob.")
        mock_server = _make_mock_server(1, [raw])
        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await tools.search_emails(query='from:"alice@example.com" subject:"Hello"', count=10)
        assert "Hello" in result
