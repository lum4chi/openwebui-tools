"""Tests for get_folder_status method."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestFolderStatus:
    """Test the get_folder_status method."""

    async def test_folder_status_success(self, tools):
        """Test getting folder status for a folder with messages."""
        mock_server = _make_status_mock(total=42, unseen=5, uid_validity=12345, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "INBOX" in result
        assert "42" in result
        assert "5" in result
        assert "12345" in result

    async def test_folder_status_empty_folder(self, tools):
        """Test getting folder status for an empty folder."""
        mock_server = _make_status_mock(total=0, unseen=0, uid_validity=12345, has_uids=False)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="Empty/Folder")
        assert "Empty/Folder" in result
        assert "0" in result

    async def test_folder_status_no_credentials(self):
        """Test folder_status returns error when credentials are missing."""
        t = Tools()
        result = await t.get_folder_status(folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_folder_status_no_server(self):
        """Test folder_status returns error when imap_server is not configured."""
        t = Tools()
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.get_folder_status(folder="INBOX")
        assert "server" in result.lower()

    async def test_folder_status_folder_not_found(self, tools):
        """Test folder_status returns error for non-existent folder."""
        mock_server = MagicMock()
        mock_server.examine.return_value = ("NO", [b"No such mailbox"])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="NonExistent")
        assert "Could not examine" in result

    async def test_folder_status_imap_exception(self, tools):
        """Test folder_status handles IMAP exceptions."""
        mock_server = MagicMock()
        mock_server.examine.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "IMAP Error" in result

    async def test_folder_status_uid_search_fallback(self, tools):
        """Test folder_status gracefully handles UID search failure."""
        mock_server = _make_status_mock(total=42, unseen=5, uid_validity=12345, has_uids=True)
        mock_server.uid.side_effect = Exception("search failed after examine")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "42" in result
        assert "5" in result
        assert "unknown" in result.lower()

    async def test_folder_status_custom_folder(self, tools):
        """Test folder_status with a custom folder name."""
        mock_server = _make_status_mock(total=10, unseen=2, uid_validity=999, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="Projects/Invoices")
        assert "Projects/Invoices" in result

    async def test_folder_status_returns_messages_label(self, tools):
        """Test folder_status output contains Messages label."""
        mock_server = _make_status_mock(total=15, unseen=3, uid_validity=100, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "Messages" in result

    async def test_folder_status_returns_unseen_label(self, tools):
        """Test folder_status output contains Unseen label."""
        mock_server = _make_status_mock(total=15, unseen=3, uid_validity=100, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "Unseen" in result

    async def test_folder_status_returns_uid_validity(self, tools):
        """Test folder_status output contains UID Validity."""
        mock_server = _make_status_mock(total=15, unseen=3, uid_validity=9999, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "UID Validity" in result
        assert "9999" in result

    async def test_folder_status_returns_uid_range(self, tools):
        """Test folder_status output contains UID range."""
        mock_server = _make_status_mock(total=15, unseen=3, uid_validity=100, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "UID First" in result
        assert "UID Latest" in result

    async def test_folder_status_generic_exception(self, tools):
        """Test folder_status handles unexpected exceptions."""

        class CustomError(Exception):
            pass

        mock_server = MagicMock()
        mock_server.examine.side_effect = CustomError("unexpected")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "IMAP Error" in result or "Error getting" in result

    async def test_folder_status_no_uids_available(self, tools):
        """Test folder_status when IMAP UID SEARCH returns None."""
        mock_server = _make_status_mock(total=0, unseen=0, uid_validity=1, has_uids=False)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "unknown" in result.lower()

    async def test_folder_status_with_uids(self, tools):
        """Test folder_status correctly reports first/latest UID."""
        mock_server = _make_status_mock(total=5, unseen=1, uid_validity=1000, has_uids=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        # Should have UID First and UID Latest, not "unknown"
        assert "UID First" in result

    async def test_folder_status_empty_uid_string(self, tools):
        """Test folder_status when UID SEARCH returns empty string."""
        mock_server = _make_status_mock(total=0, unseen=0, uid_validity=1, has_uids=False, has_uids_empty=True)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "unknown" in result.lower()


def _make_status_mock(total: int, unseen: int, uid_validity: int, has_uids: bool, has_uids_empty: bool = False):
    """Create a mock IMAP server configured for folder status tests."""
    from unittest.mock import MagicMock

    mock_server = MagicMock()

    status_str = f'(* STATUS "INBOX" (MESSAGES {total} UNSEEN {unseen} UIDVALIDITY {uid_validity}))'
    mock_server.examine.return_value = ("OK", [status_str.encode()])

    if has_uids:
        mock_server.uid.return_value = ("OK", [b"10 20 30"])
    elif has_uids_empty:
        mock_server.uid.return_value = ("OK", [b""])
    else:
        mock_server.uid.return_value = ("OK", [None])

    mock_server.logout.return_value = ("OK", [b"Logout"])
    mock_server.close.return_value = None
    return mock_server
