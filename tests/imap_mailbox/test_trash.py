"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)

from unittest.mock import patch

from .conftest import _make_mock_email_data, _make_mock_server, _make_raw_email


class TestTrashMethods:
    """Test the list_trash_emails and read_trash_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_trash_disabled_by_default(self, tools):
        """Test list_trash_emails is blocked when allow_list_trash is False."""
        assert tools.valves.allow_list_trash is False
        result = await tools.list_trash_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_trash" in result

    @pytest.mark.asyncio
    async def test_list_trash_enabled(self, tools):
        """Test listing trash emails when access is enabled."""
        tools.valves.allow_list_trash = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Trashed", "Trash body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_trash_emails(count=10)
        assert "Trashed" in result
        assert "Trash" in result

    @pytest.mark.asyncio
    async def test_list_trash_custom_folder(self, tools):
        """Test listing trash emails from a custom folder like 'Deleted Items'."""
        tools.valves.allow_list_trash = True
        tools.valves.trash_folder = "Deleted Items"
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Deleted", "Body")
        emails = [(raw, "1")]

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                return ("OK", [_make_mock_email_data(raw, "1")])
            return ("OK", [b""])

        mock_server = _make_mock_server(emails, override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_trash_emails(count=10)
        assert "Deleted" in result
        assert "Deleted Items" in result

    @pytest.mark.asyncio
    async def test_read_trash_enabled(self, tools):
        """Test reading a trash email when access is enabled."""
        tools.valves.allow_list_trash = True
        raw = _make_raw_email("sender@test.com", "recv@test.com", "Trash Msg", "Trash body")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_trash_email(email_index=1)
        assert "Trash Msg" in result
        assert "Trash" in result

