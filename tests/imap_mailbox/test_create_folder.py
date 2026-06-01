"""Tests for create_folder method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestCreateFolder:
    """Test the create_folder method."""

    @pytest.mark.asyncio
    async def test_create_folder_success(self, tools):
        """Test successful folder creation."""
        tools.valves.allow_create_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.create.return_value = ("OK", [b"CREATE completed"])
        mock_server.select.return_value = (b"OK", [b"0 Messages"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.create_folder(folder="Projects")

        assert "created successfully" in result
        assert "Projects" in result
        mock_server.create.assert_called_once_with("Projects")

    @pytest.mark.asyncio
    async def test_create_folder_nested_success(self, tools):
        """Test creating nested folder path."""
        tools.valves.allow_create_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.create.return_value = ("OK", [b"CREATE completed"])
        mock_server.select.return_value = (b"OK", [b"0 Messages"])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.create_folder(folder="Projects/Invoices/2025")

        assert "created successfully" in result
        assert "Projects/Invoices/2025" in result

    @pytest.mark.asyncio
    async def test_create_folder_gate_disabled(self, tools):
        """Test create_folder is gated by default."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.create_folder(folder="TestFolder")

        assert "disabled" in result
        assert "allow_create_folder" in result
        mock_server.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_folder_no_credentials(self):
        """Test create_folder without credentials."""
        t = Tools()
        t.valves.allow_create_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.create_folder(folder="TestFolder")

        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_create_folder_no_server(self):
        """Test create_folder without server configured."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_create_folder = True
        mock_server = MagicMock()

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.create_folder(folder="TestFolder")

        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_create_folder_imap_error(self, tools):
        """Test create_folder handles IMAP exceptions."""
        tools.valves.allow_create_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.create.side_effect = _IMAP_EXCEPTION("Folder already exists")
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.create_folder(folder="ExistingFolder")

        assert "IMAP Error" in result
        assert "Folder already exists" in result

    @pytest.mark.asyncio
    async def test_create_folder_imap_exception_type(self, tools):
        """Test create_folder catches _IMAP_EXCEPTION specifically."""
        tools.valves.allow_create_folder = True
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.create.side_effect = _IMAP_EXCEPTION("No such directory")
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.create_folder(folder="Nope")

        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_create_folder_general_error(self, tools):
        """Test create_folder handles generic (non-IMAP) exceptions."""
        import imap_mailbox

        orig = imap_mailbox._IMAP_EXCEPTION
        imap_mailbox._IMAP_EXCEPTION = RuntimeError
        try:
            tools.valves.allow_create_folder = True
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])

            def create_side_effect(*args, **kwargs):
                raise ValueError("Something went wrong")

            mock_server.create.side_effect = create_side_effect
            mock_server.close.return_value = None

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.create_folder(folder="Test")
        finally:
            imap_mailbox._IMAP_EXCEPTION = orig

        assert "Error creating folder" in result
