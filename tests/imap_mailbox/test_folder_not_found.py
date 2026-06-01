"""Tests for folder select validation - ensures failed folder selection is properly reported."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestFolderNotFound:
    """Test that non-existent folders are properly detected and reported."""

    @pytest.mark.asyncio
    async def test_list_emails_nonexistent_folder(self, tools):
        """Test list_emails when folder doesn't exist (select returns NO)."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Servizi Pubblici", count=10)

        assert "IMAP Error" in result
        assert "Servizi Pubblici" in result

    @pytest.mark.asyncio
    async def test_list_emails_nonexistent_folder_returns_readable_error(self, tools):
        """Test that the error message clearly indicates the folder issue, not just credentials."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist: Bad mailbox name"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="NonExistent", count=5)

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_read_email_nonexistent_folder(self, tools):
        """Test read_email when folder doesn't exist."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1, folder="Fake/Folder")

        assert "IMAP Error" in result
        assert "Fake/Folder" in result

    @pytest.mark.asyncio
    async def test_search_emails_nonexistent_folder(self, tools):
        """Test search_emails when folder doesn't exist."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="test", count=10, folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_delete_email_nonexistent_folder(self, tools):
        """Test delete_email when folder doesn't exist."""
        tools.valves.allow_delete_single = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1, folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_nonexistent_folder(self, tools):
        """Test delete_all_emails when folder doesn't exist."""
        tools.valves.allow_delete_all = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails(folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_archive_email_nonexistent_folder(self, tools):
        """Test archive_email when source folder doesn't exist."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1, folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_move_email_nonexistent_folder(self, tools):
        """Test move_email when source folder doesn't exist."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Archive", folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_move_emails_by_uid_nonexistent_folder(self, tools):
        """Test move_emails_by_uid when source folder doesn't exist."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        mock_server.logout.return_value = ("OK", [b"Logout successful"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails_by_uid(email_uids=["1"], target_folder="Archive", folder="NonExistent")

        assert "IMAP Error" in result
        assert "NonExistent" in result

    @pytest.mark.asyncio
    async def test_select_folder_raises_on_not_ok(self):
        """Test that _select_folder raises when select returns NOT OK."""
        t = Tools()
        mock_server = MagicMock()
        mock_server.select.return_value = ("NO", [b"Mailbox doesn't exist"])
        with pytest.raises(_IMAP_EXCEPTION) as exc_info:
            t._select_folder(mock_server, "BadFolder")
        assert "BadFolder" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_folder_with_spaces_works_when_exists(self, tools):
        """Test that folder names with spaces work when the folder actually exists."""
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Mail with spaces folder", "Body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="Servizi Pubblici", count=10)
        assert "Servizi Pubblici" in result
        assert "Mail with spaces folder" in result
