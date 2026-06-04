"""Tests for archive_emails and trash_emails convenience methods."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestArchiveEmails:
    """Test the archive_emails convenience method."""

    async def test_archive_emails_success(self, tools):
        """Test archiving a single email."""
        tools.valves.allow_move = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids="42", folder="INBOX")
        assert "42" in result
        assert "Archive" in result or "mv" in result.lower() or "mov" in result.lower()

    async def test_archive_emails_disabled_by_default(self, tools):
        """Test archive_emails is blocked when allow_move is False."""
        tools.valves.allow_move = False
        result = await tools.archive_emails(uids=["42"], folder="INBOX")
        assert "disabled" in result.lower() and "allow_move" in result

    async def test_archive_emails_no_uids(self, tools):
        """Test archive returns error when no UIDs are provided."""
        tools.valves.allow_move = True
        result = await tools.archive_emails(uids="", folder="INBOX")
        assert "No UIDs" in result

    async def test_archive_emails_no_credentials(self):
        """Test archive_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_move = True
        result = await t.archive_emails(uids=["1"], folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_archive_emails_no_server(self):
        """Test archive_emails returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_move = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.archive_emails(uids=["1"], folder="INBOX")
        assert "server" in result.lower()

    async def test_archive_emails_custom_source_folder(self, tools):
        """Test archive_emails with explicit source folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids="1", folder="Sent")
        assert "Sent" in result

    async def test_archive_emails_custom_target(self, tools):
        """Test archive_emails with custom target folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids="1", folder="INBOX", target_folder="MyArchive")
        assert "MyArchive" in result

    async def test_archive_emails_imap_error(self, tools):
        """Test archive_emails handles IMAP exceptions."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids=["42"], folder="INBOX")
        assert "IMAP Error" in result

    async def test_archive_emails_default_folder_is_inbox(self, tools):
        """Test archive_emails defaults to INBOX when folder is empty string."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids="1", folder="")
        assert "INBOX" in result


class TestTrashEmails:
    """Test the trash_emails convenience method."""

    async def test_trash_emails_success(self, tools):
        """Test trashing a single email."""
        tools.valves.allow_move = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Spam", "Delete me.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.trash_emails(uids="42", folder="INBOX")
        assert "42" in result

    async def test_trash_emails_disabled_by_default(self, tools):
        """Test trash_emails is blocked when allow_move is False."""
        tools.valves.allow_move = False
        result = await tools.trash_emails(uids=["42"], folder="INBOX")
        assert "disabled" in result.lower() and "allow_move" in result

    async def test_trash_emails_no_uids(self, tools):
        """Test trash_emails returns error when no UIDs are provided."""
        tools.valves.allow_move = True
        result = await tools.trash_emails(uids="", folder="INBOX")
        assert "No UIDs" in result

    async def test_trash_emails_no_credentials(self):
        """Test trash_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_move = True
        result = await t.trash_emails(uids=["1"], folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_trash_emails_no_server(self):
        """Test trash_emails returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_move = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.trash_emails(uids=["1"], folder="INBOX")
        assert "server" in result.lower()

    async def test_trash_emails_custom_target(self, tools):
        """Test trash_emails with custom target folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.trash_emails(uids="1", folder="INBOX", target_folder="Deleted Items")
        assert "Deleted Items" in result

    async def test_trash_emails_imap_error(self, tools):
        """Test trash_emails handles IMAP exceptions."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.trash_emails(uids=["42"], folder="INBOX")
        assert "IMAP Error" in result

    async def test_trash_emails_default_folder_is_inbox(self, tools):
        """Test trash_emails defaults to INBOX when folder is empty string."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.trash_emails(uids="1", folder="")
        assert "INBOX" in result
