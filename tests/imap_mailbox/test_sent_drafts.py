"""Auto-generated test module."""

from unittest.mock import patch

import pytest

from imap_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


class TestSentMethods:
    """Test the list_sent_emails and read_sent_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_sent_disabled_by_default(self, tools):
        """Test list_sent_emails is blocked when allow_list_sent is False."""
        assert tools.valves.allow_list_sent is False
        result = await tools.list_sent_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_sent" in result

    @pytest.mark.asyncio
    async def test_list_sent_enabled(self, tools):
        """Test listing sent emails when access is enabled."""
        tools.valves.allow_list_sent = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Sent Msg", "Sent body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_sent_emails(count=10)
        assert "Sent Msg" in result
        assert "Sent" in result

    @pytest.mark.asyncio
    async def test_read_sent_enabled(self, tools):
        """Test reading a sent email when access is enabled."""
        tools.valves.allow_list_sent = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Outgoing", "Outgoing body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_sent_email(email_index=1)
        assert "Outgoing" in result
        assert "Sent" in result


class TestDraftsMethods:
    """Test the list_draft_emails convenience method."""

    @pytest.mark.asyncio
    async def test_list_drafts_disabled_by_default(self, tools):
        """Test list_draft_emails is blocked when allow_list_drafts is False."""
        assert tools.valves.allow_list_drafts is False
        result = await tools.list_draft_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_drafts" in result

    @pytest.mark.asyncio
    async def test_list_drafts_enabled(self, tools):
        """Test listing draft emails when access is enabled."""
        tools.valves.allow_list_drafts = True
        raw = _make_raw_email("me@test.com", "you@test.com", "Draft Msg", "Draft body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_draft_emails(count=10)
        assert "Draft Msg" in result
        assert "Drafts" in result

    @pytest.mark.asyncio
    async def test_list_drafts_no_read_method(self, tools):
        """Verify read_draft_email convenience does not exist (drafts are typically read-only)."""
        assert not hasattr(tools, "read_draft_email")


class TestIMAPListSpecialFolders:
    """Test accessing special folders returns errors when not enabled."""

    @pytest.mark.asyncio
    async def test_list_sent_emails_disabled(self):
        """Test list_sent_emails returns access denied when not enabled."""
        t = Tools()
        result = await t.list_sent_emails(count=5)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_read_sent_email_disabled(self):
        """Test read_sent_email returns access denied when not enabled."""
        t = Tools()
        result = await t.read_sent_email(email_index=1)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_list_trash_emails_disabled(self):
        """Test list_trash_emails returns access denied when not enabled."""
        t = Tools()
        result = await t.list_trash_emails(count=5)
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_read_trash_email_disabled(self):
        """Test read_trash_email returns access denied when not enabled."""
        t = Tools()
        result = await t.read_trash_email(email_index=1)
        assert "disabled" in result.lower()
