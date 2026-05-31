"""Tests for list_folders method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestListFolders:
    """Test the list_folders method."""

    @pytest.mark.asyncio
    async def test_list_folders_success(self, tools):
        """Test successful folder listing."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = (
            "OK",
            [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Sent"',
                b'(\\HasChildren) "/" "Projects"',
            ],
        )
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "Available IMAP folders" in result
        assert "INBOX" in result
        assert "Sent" in result
        assert "Projects" in result

    @pytest.mark.asyncio
    async def test_list_folders_empty(self, tools):
        """Test list_folders when server has no folders."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = ("OK", [])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "No folders found" in result

    @pytest.mark.asyncio
    async def test_list_folders_no_credentials(self):
        """Test list_folders without credentials."""
        t = Tools()
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.list_folders()

        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_list_folders_no_server(self):
        """Test list_folders without server configured."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.list_folders()

        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_list_folders_imap_error(self, tools):
        """Test list_folders handles IMAP exceptions."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.side_effect = _IMAP_EXCEPTION("Connection lost")
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_list_folders_unicode_decode(self, tools):
        """Test list_folders handles non-decodable entries gracefully."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = (
            "OK",
            [b'(\\HasNoChildren) "/" "\xc0\xc1NonUTF8"'],
        )
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "Available IMAP folders" in result

    @pytest.mark.asyncio
    async def test_list_folders_with_none_entry(self, tools):
        """Test list_folders skips None entries gracefully."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = (
            "OK",
            [b'(\\HasNoChildren) "/" "INBOX"', None, b'(\\HasNoChildren) "/" "Sent"'],
        )
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "Available IMAP folders" in result
        assert "INBOX" in result
        assert "Sent" in result

    @pytest.mark.asyncio
    async def test_list_folders_general_error(self, tools):
        """Test list_folders handles generic (non-IMAP) exceptions."""
        import imap_mailbox

        orig = imap_mailbox._IMAP_EXCEPTION
        imap_mailbox._IMAP_EXCEPTION = RuntimeError
        try:
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])
            mock_server.list.side_effect = ValueError("Server issue")
            mock_server.close.return_value = None

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_folders()
        finally:
            imap_mailbox._IMAP_EXCEPTION = orig

        assert "Error listing folders" in result
