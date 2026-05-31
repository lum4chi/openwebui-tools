"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

from imap_mailbox import Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)

from unittest.mock import patch

from .conftest import _make_mock_server, _make_raw_email


class TestListInboxEmails:
    """Test the list_inbox_emails convenience method."""

    @pytest.mark.asyncio
    async def test_list_inbox_emails_disabled_by_default(self, tools):
        """Test list_inbox_emails is blocked when allow_list_inbox is False."""
        assert tools.valves.allow_list_inbox is False
        result = await tools.list_inbox_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_inbox" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_enabled_with_messages(self, tools):
        """Test listing inbox emails when access is enabled."""
        tools.valves.allow_list_inbox = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Hello", "Hi Bob, how are you?")
        raw2 = _make_raw_email(
            "carol@example.com", "bob@example.com", "Invoice #123", "Please find attached the invoice."
        )
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=10)
        assert "alice@example.com" in result
        assert "carol@example.com" in result
        assert "Hello" in result
        assert "Invoice #123" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_empty(self, tools):
        """Test listing inbox emails from an empty inbox."""
        tools.valves.allow_list_inbox = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_no_credentials(self):
        """Test list_inbox_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_inbox = True
        result = await t.list_inbox_emails(count=5)
        assert "Error" in result and "credentials" in result




class TestReadInboxEmail:
    """Test the read_inbox_email convenience method."""

    @pytest.mark.asyncio
    async def test_read_inbox_email_disabled_by_default(self, tools):
        """Test read_inbox_email is blocked when allow_list_inbox is False."""
        assert tools.valves.allow_list_inbox is False
        result = await tools.read_inbox_email(email_index=1)
        assert "disabled" in result.lower() and "allow_list_inbox" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_enabled(self, tools):
        """Test reading an inbox email when access is enabled."""
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Inbox Message", "This is inbox body content.")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "Inbox Message" in result
        assert "INBOX" in result
        assert "This is inbox body content" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_out_of_range(self, tools):
        """Test reading an inbox email with an out-of-range index."""
        tools.valves.allow_list_inbox = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_inbox_email_empty_folder(self, tools):
        """Test reading from an empty inbox folder."""
        tools.valves.allow_list_inbox = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_no_credentials(self):
        """Test read_inbox_email returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_inbox = True
        result = await t.read_inbox_email(email_index=1)
        assert "Error" in result and "credentials" in result

