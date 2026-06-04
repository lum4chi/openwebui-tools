"""Tests to cover missing lines in new IMAP methods."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _make_mock_server, _make_raw_email


class TestStarUnstarMissingCoverage:
    """Cover missing lines in _star_unstar_emails."""

    async def test_star_unstar_empty_folder(self, tools):
        """Test _star_unstar_emails with None folder returns error (line 1132)."""
        t = Tools()
        t.valves.allow_modify_flags = True
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.star_emails(uids=["1"], folder=None)
        assert "Folder parameter is required" in result

    async def test_star_unstar_no_server(self, tools):
        """Test _star_unstar_emails with no imap_server configured (line 1140)."""
        t = Tools()
        t.valves.allow_modify_flags = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.star_emails(uids=["1"], folder="INBOX")
        assert "IMAP server is not configured" in result

    async def test_star_unstar_partial_store_failure(self, tools):
        """Test _star_unstar_emails raises in inner loop (lines 1156-1157) and reports partial (line 1170)."""
        tools.valves.allow_modify_flags = True

        def override_store(cmd, criteria=None, *args, **kwargs):
            if cmd == "STORE":
                uid = criteria
                if isinstance(uid, (list, tuple)):
                    uid = uid[0]
                if uid == "2":
                    raise ValueError("store failed")
                return ("OK", [b"FLAGS (\\Flagged)"])
            return ("OK", [b""])

        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server(
            [(raw, "1"), (raw, "2")],
            override_uid=override_store,
        )
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids=["1", "2"], folder="INBOX")
        assert "1" in result
        assert "Failed" in result
        assert "2" in result


class TestCopyMissingCoverage:
    """Cover missing lines in copy_emails."""

    async def test_copy_partial_failure(self, tools):
        """Test copy where some UIDs COPY succeed and some fail (lines 1223-1224, 1239-1241)."""

        def override_copy(cmd, criteria=None, *args, **kwargs):
            if cmd == "COPY":
                uid = criteria
                if isinstance(uid, (list, tuple)):
                    uid = uid[0]
                if uid == "5":
                    raise ValueError("copy failed")
                return ("OK", [b""])
            return ("OK", [b""])

        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server(
            [(raw, "1"), (raw, "5")],
            override_uid=override_copy,
        )
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids=["1", "5"], target_folder="Archive", folder="INBOX")
        assert "1" in result
        assert "Failed" in result


class TestMoveConvenienceMissingCoverage:
    """Cover missing lines in _move_convenience."""

    async def test_multiple_moved_output(self, tools):
        """Test archive with multiple UIDs produces multi-line output with UIDs line (lines 1368-1372)."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1"), (raw, "2"), (raw, "3")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids=["1", "2"], folder="INBOX")
        assert "2 email(s)" in result
        assert "UIDs:" in result

    async def test_archive_partial_failure(self, tools):
        """Test archive where some COPY succeed and some fail (lines 1357-1358, 1374-1376)."""
        tools.valves.allow_move = True

        def override_archive(cmd, criteria=None, *args, **kwargs):
            if isinstance(criteria, (list, tuple)):
                criteria = criteria[0]
            if criteria == "2":
                raise ValueError("no such UID")
            return ("OK", [b""])

        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server(
            [(raw, "1"), (raw, "2")],
            override_uid=override_archive,
        )
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_emails(uids=["1", "2"], folder="INBOX")
        assert "Failed" in result
        assert "2" in result


class TestFolderStatusMissingCoverage:
    """Cover missing lines in get_folder_status."""

    async def test_folder_status_uid_nonempty_result(self, tools):
        """Test get_folder_status with UID SEARCH returning non-empty UIDs (lines 1452-1456)."""
        mock_server = MagicMock()
        mock_server.examine.return_value = (
            "OK",
            [b'(* STATUS "INBOX" (MESSAGES 5 UNSEEN 1 UIDVALIDITY 12345))'],
        )
        mock_server.uid.return_value = ("OK", [b"10 20 30"])
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.logout.return_value = ("OK", [b""])
        mock_server.close.return_value = None
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "UID First" in result
        assert "10" in result
        assert "UID Latest" in result

    async def test_folder_status_uid_none_result(self, tools):
        """Test get_folder_status when UID SEARCH returns None (line 1452 conditional)."""
        mock_server = MagicMock()
        mock_server.examine.return_value = (
            "OK",
            [b'(* STATUS "INBOX" (MESSAGES 0 UNSEEN 0 UIDVALIDITY 1))'],
        )
        mock_server.uid.return_value = ("OK", [None])
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.logout.return_value = ("OK", [b""])
        mock_server.close.return_value = None
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "UID First" in result
        assert "unknown" in result

    async def test_folder_status_generic_exception(self, tools):
        """Test get_folder_status with generic exception (lines 1477-1478)."""
        mock_server = MagicMock()
        mock_server.examine.side_effect = ValueError("unexpected error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.get_folder_status(folder="INBOX")
        assert "Error getting folder status" in result


class TestCopyGenericException:
    """Test generic exception handling in copy_emails."""

    async def test_copy_generic_connect_exception(self):
        """Test copy_emails handles generic connection exception (lines 1250-1251)."""

        class BrokenTools(Tools):
            def _connect(self):
                raise TypeError("connection failed")

        t = BrokenTools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.copy_emails(uids=["1"], target_folder="Archive", folder="INBOX")
        assert "Error copying" in result


class TestMoveGenericException:
    """Test generic exception handling in _move_convenience."""

    async def test_archive_generic_exception(self):
        """Test archive handles generic connection exception (lines 1385-1388)."""

        class BrokenTools(Tools):
            def _connect(self):
                raise TypeError("connection failed")

        t = BrokenTools()
        t.valves.allow_move = True
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.archive_emails(uids=["1"], folder="INBOX")
        assert "Error archiving" in result

    async def test_trash_generic_exception(self):
        """Test trash handles generic connection exception (line 1388)."""

        class BrokenTools(Tools):
            def _connect(self):
                raise TypeError("connection failed")

        t = BrokenTools()
        t.valves.allow_move = True
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.trash_emails(uids=["1"], folder="INBOX")
        assert "Error trashing" in result
