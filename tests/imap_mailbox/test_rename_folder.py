"""Tests for rename_folder method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestRenameFolder:
    """Test the rename_folder method."""

    @pytest.mark.asyncio
    async def test_rename_folder_success(self, tools):
        """Test successful folder rename."""
        tools.valves.allow_rename_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.rename_thumbnail.return_value = ("OK", [b"RENAME completed"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.rename_folder(old_name="OldName", new_name="NewName")

        assert "renamed" in result
        assert "OldName" in result
        assert "NewName" in result
        mock_server.rename_thumbnail.assert_called_once()

    @pytest.mark.asyncio
    async def test_rename_folder_gate_disabled(self, tools):
        """Test rename_folder is gated by default."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.rename_folder(old_name="Old", new_name="New")

        assert "disabled" in result
        assert "allow_rename_folder" in result
        mock_server.rename_thumbnail.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_folder_no_credentials(self):
        """Test rename_folder without credentials."""
        t = Tools()
        t.valves.allow_rename_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.rename_folder(old_name="Old", new_name="New")

        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_rename_folder_no_server(self):
        """Test rename_folder without server configured."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_rename_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.rename_folder(old_name="Old", new_name="New")

        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_rename_folder_imap_error(self, tools):
        """Test rename_folder handles IMAP exceptions."""
        tools.valves.allow_rename_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.rename_thumbnail.side_effect = _IMAP_EXCEPTION("No such folder")
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.rename_folder(old_name="NonExistent", new_name="NewName")

        assert "IMAP Error" in result
        assert "No such folder" in result

    @pytest.mark.asyncio
    async def test_rename_folder_general_error(self, tools):
        """Test rename_folder handles generic exceptions."""
        import imap_mailbox

        orig = imap_mailbox._IMAP_EXCEPTION
        imap_mailbox._IMAP_EXCEPTION = RuntimeError
        try:
            tools.valves.allow_rename_folder = True
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])
            mock_server.rename_thumbnail.side_effect = ValueError("Permission denied")
            mock_server.close.return_value = None

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.rename_folder(old_name="Old", new_name="New")
        finally:
            imap_mailbox._IMAP_EXCEPTION = orig

        assert "Error renaming folder" in result
