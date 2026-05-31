"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

from imap_mailbox import Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)

from unittest.mock import patch

from .conftest import _make_mock_email_data, _make_mock_server, _make_raw_email


class TestArchiveMethods:
    """Test the list_archive_emails and read_archive_email convenience methods."""

    @pytest.mark.asyncio
    async def test_list_archive_disabled_by_default(self, tools):
        """Test list_archive_emails is blocked when allow_list_archive is False."""
        assert tools.valves.allow_list_archive is False
        result = await tools.list_archive_emails(count=5)
        assert "disabled" in result.lower() and "allow_list_archive" in result

    @pytest.mark.asyncio
    async def test_list_archive_enabled_with_messages(self, tools):
        """Test listing archived emails when access is enabled."""
        tools.valves.allow_list_archive = True
        raw1 = _make_raw_email("alice@example.com", "bob@example.com", "Archived A", "Body A")
        raw2 = _make_raw_email("carol@example.com", "bob@example.com", "Archived B", "Body B")
        emails = [(raw1, "1"), (raw2, "2")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "Archived A" in result
        assert "Archived B" in result
        assert "Archive" in result

    @pytest.mark.asyncio
    async def test_list_archive_enabled_custom_folder(self, tools):
        """Test listing archived emails from a custom folder path."""
        tools.valves.allow_list_archive = True
        tools.valves.archive_folder = "Gmail/All Mail"
        raw = _make_raw_email("sender@test.com", "receiver@test.com", "Test", "Body")
        emails = [(raw, "1")]

        def override_uid(cmd, criteria=None, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"1"])
            elif cmd == "fetch":
                return ("OK", [_make_mock_email_data(raw, "1")])
            return ("OK", [b""])

        mock_server = _make_mock_server(emails, override_uid=override_uid)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "Test" in result
        assert "Gmail/All Mail" in result

    @pytest.mark.asyncio
    async def test_list_archive_empty(self, tools):
        """Test listing archived emails from an empty archive folder."""
        tools.valves.allow_list_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_archive_emails(count=10)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_read_archive_disabled_by_default(self, tools):
        """Test read_archive_email is blocked when allow_list_archive is False."""
        assert tools.valves.allow_list_archive is False
        result = await tools.read_archive_email(email_index=1)
        assert "disabled" in result.lower() and "allow_list_archive" in result

    @pytest.mark.asyncio
    async def test_read_archive_enabled(self, tools):
        """Test reading an archived email when access is enabled."""
        tools.valves.allow_list_archive = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Archived Message", "This is body content.")
        emails = [(raw, "1")]
        mock_server = _make_mock_server(emails)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=1)
        assert "Archived Message" in result
        assert "Archive" in result
        assert "This is body content" in result

    @pytest.mark.asyncio
    async def test_read_archive_out_of_range(self, tools):
        """Test reading an archived email with an out-of-range index."""
        tools.valves.allow_list_archive = True
        raw = _make_raw_email("test@example.com", "u@example.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_read_archive_empty_folder(self, tools):
        """Test reading from an empty archive folder."""
        tools.valves.allow_list_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_archive_email(email_index=1)
        assert "empty" in result.lower() or "No emails" in result

    @pytest.mark.asyncio
    async def test_list_archive_no_credentials(self):
        """Test list_archive_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_list_archive = True
        result = await t.list_archive_emails()
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_archive_custom_folder_default(self, tools):
        """Test default archive folder is 'Archive'."""
        assert tools.valves.archive_folder == "Archive"




class TestArchiveEmailFunctional:
    """Test the archive_email method (the action, not read/list)."""

    @pytest.mark.asyncio
    async def test_archive_email_enabled_success(self, tools):
        """Test archiving an email when permission is enabled."""
        tools.valves.allow_archive = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "3")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "archived" in result.lower()
        assert mock_server.uid.call_args_list[-2][0][0] == "COPY"
        assert mock_server.expunge.called

    @pytest.mark.asyncio
    async def test_archive_email_disabled_by_default(self, tools):
        """Test archive_email is blocked when allow_archive is False."""
        assert tools.valves.allow_archive is False
        result = await tools.archive_email(email_index=1)
        assert "disabled" in result.lower() and "allow_archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_out_of_range(self, tools):
        """Test archiving an email with an out-of-range index."""
        tools.valves.allow_archive = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=99)
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_archive_email_empty_mailbox(self, tools):
        """Test archiving from an empty mailbox."""
        tools.valves.allow_archive = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "empty" in result.lower() or "Nothing to archive" in result

    @pytest.mark.asyncio
    async def test_archive_email_custom_folder(self, tools):
        """Test archiving with a custom archive folder."""
        tools.valves.allow_archive = True
        tools.valves.archive_folder = "Gmail/All Mail"
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "Gmail/All Mail" in result
        copy_call = [c for c in mock_server.uid.call_args_list if c[0][0] == "COPY"]
        assert len(copy_call) == 1
        assert copy_call[0][0][2] == "Gmail/All Mail"

    @pytest.mark.asyncio
    async def test_archive_email_no_credentials(self):
        """Test archiving returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_archive = True
        result = await t.archive_email(email_index=1)
        assert "Error" in result and "credentials" in result

