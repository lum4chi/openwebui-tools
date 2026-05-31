"""Tests for delete_folder method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestDeleteFolder:
    """Test the delete_folder method."""

    @pytest.mark.asyncio
    async def test_delete_folder_success(self, tools):
        """Test successful folder deletion."""
        tools.valves.allow_delete_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.delete.return_value = ("OK", [b"DELETE completed"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_folder(folder="FolderToDelete")

        assert "deleted" in result
        assert "FolderToDelete" in result

    @pytest.mark.asyncio
    async def test_delete_folder_gate_disabled(self, tools):
        """Test delete_folder is gated by default."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_folder(folder="FolderToDelete")

        assert "disabled" in result
        assert "allow_delete_folder" in result
        mock_server.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_folder_no_credentials(self):
        """Test delete_folder without credentials."""
        t = Tools()
        t.valves.allow_delete_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.delete_folder(folder="FolderToDelete")

        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_folder_no_server(self):
        """Test delete_folder without server configured."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_delete_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.delete_folder(folder="FolderToDelete")

        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_folder_imap_error(self, tools):
        """Test delete_folder handles IMAP exceptions."""
        tools.valves.allow_delete_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.delete.side_effect = _IMAP_EXCEPTION("Mailbox not empty")
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_folder(folder="NotEmpty")

        assert "IMAP Error" in result
        assert "Mailbox not empty" in result

    @pytest.mark.asyncio
    async def test_delete_folder_general_error(self, tools):
        """Test delete_folder handles generic exceptions."""
        import imap_mailbox

        orig = imap_mailbox._IMAP_EXCEPTION
        imap_mailbox._IMAP_EXCEPTION = RuntimeError
        try:
            tools.valves.allow_delete_folder = True
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])
            mock_server.delete.side_effect = ValueError("Access denied")
            mock_server.close.return_value = None

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.delete_folder(folder="Forbidden")
        finally:
            imap_mailbox._IMAP_EXCEPTION = orig

        assert "Error deleting folder" in result
