"""Auto-generated test module."""

from unittest.mock import patch

import pytest

from imap_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


class TestFolderParamOverride:
    """Test passing explicit folder parameter to existing methods."""

    @pytest.mark.asyncio
    async def test_list_emails_folder_param(self, tools):
        """Test list_emails respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Hello", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Custom/Folder", count=10)
        assert "Hello" in result
        assert "Custom/Folder" in result
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_read_emails_folder_param(self, tools):
        """Test read_emails respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_emails(uids="1", folder="Custom/Folder")
        assert "Custom/Folder" in result
        assert "Test" in result

    @pytest.mark.asyncio
    async def test_search_emails_folder_param(self, tools):
        """Test search_emails respects explicit folder param."""
        raw = _make_raw_email("test@example.com", "u@example.com", "Search Me", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="Search Me", count=10, folder="Custom/Folder")
        assert "Search Me" in result
        assert "Custom/Folder" in result


class TestListEmailsExplicitFolder:
    """Test the list_emails method with required folder parameter."""

    @pytest.mark.asyncio
    async def test_list_emails_requires_folder(self):
        """Test that list_emails raises TypeError when folder is not provided."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.imap_port = 993
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        with pytest.raises(TypeError):
            await t.list_emails(count=5)  # pyright: ignore

    @pytest.mark.asyncio
    async def test_list_emails_with_custom_folder(self, tools):
        """Test list_emails with a custom folder."""
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Custom Folder", "Body content")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Custom/Folder", count=10)
        assert "Custom/Folder" in result
        assert "Custom Folder" in result

    @pytest.mark.asyncio
    async def test_list_emails_empty_custom_folder(self, tools):
        """Test list_emails with empty custom folder."""
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Empty/Folder", count=10)
        assert "empty" in result.lower() or "No emails" in result
