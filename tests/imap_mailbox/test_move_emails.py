"""Tests for move_emails method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email, patch_imap_mailbox_attr


class TestMoveEmails:
    """Test the move_emails method (replaces move_email, archive_email, move_emails_by_uid)."""

    @pytest.mark.asyncio
    async def test_move_emails_single_uid_success(self, tools):
        """Test moving a single email by UID."""
        tools.valves.allow_move = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids="42", target_folder="Archive")
        assert "Email" in result or "moved" in result.lower()
        assert "42" in result
        assert "Archive" in result

    @pytest.mark.asyncio
    async def test_move_emails_multiple_uids(self, tools):
        """Test moving multiple emails by UID in one call."""
        tools.valves.allow_move = True
        raw1 = _make_raw_email("a@b.com", "c@d.com", "Msg 1", "Body 1")
        raw2 = _make_raw_email("a@b.com", "c@d.com", "Msg 2", "Body 2")
        raw3 = _make_raw_email("a@b.com", "c@d.com", "Msg 3", "Body 3")
        mock_server = _make_mock_server([(raw1, "10"), (raw2, "11"), (raw3, "12")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids=["10", "11"], target_folder="Projects")
        assert "2 email(s)" in result
        assert "10" in result
        assert "11" in result
        assert "Projects" in result

    @pytest.mark.asyncio
    async def test_move_emails_disabled_by_default(self, tools):
        """Test move_emails is blocked when allow_move is False."""
        tools.valves.allow_move = False
        result = await tools.move_emails(uids=["1", "2"], target_folder="Projects")
        assert "disabled" in result.lower() and "allow_move" in result

    @pytest.mark.asyncio
    async def test_move_emails_no_credentials(self):
        """Test move returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_move = True
        result = await t.move_emails(uids=["1"], target_folder="Projects")
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_move_emails_no_server(self):
        """Test move returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_move = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.move_emails(uids=["1"], target_folder="Projects")
        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_move_emails_imap_error(self, tools):
        """Test move_emails handles IMAP exceptions."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids=["42"], target_folder="Projects")
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_move_emails_custom_source_folder(self, tools):
        """Test batch move with custom source folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids=["1"], target_folder="Trash", folder="INBOX")
        assert "INBOX" in result
        assert "Trash" in result

    @pytest.mark.asyncio
    async def test_move_emails_partial_failure(self, tools):
        """Test batch move where some UIDs fail."""

        def override_move(cmd, criteria=None, *args, **kwargs):
            if cmd == "COPY":
                uid = criteria
                if isinstance(uid, (list, tuple)):
                    uid = uid[0]
                if uid == "5":
                    raise Exception("no such UID")
                return ("OK", [b""])
            return ("OK", [b""])

        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")], override_uid=override_move)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids=["1", "5"], target_folder="Projects")
        assert "1" in result
        assert "5" in result
        assert "Failed" in result

    @pytest.mark.asyncio
    async def test_move_emails_generic_exception(self):
        """Test batch move handles unexpected exceptions."""

        class CustomIMAPError(Exception):
            pass

        with patch_imap_mailbox_attr("_IMAP_EXCEPTION", CustomIMAPError):

            class BrokenTools(Tools):
                def _connect(self):
                    raise RuntimeError("unexpected connection failure")

            t = BrokenTools()
            t.valves.imap_server = "mail.example.com"
            t.valves.imap_port = 993
            t.valves.username = "testuser"
            t.valves.password = "testpass"
            t.valves.allow_move = True
            result = await t.move_emails(uids=["42"], target_folder="Projects")
            assert "Error moving emails" in result

    @pytest.mark.asyncio
    async def test_move_emails_uid_in_response(self, tools):
        """Test that the moved email UID is included in response."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids="42", target_folder="Projects")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_move_emails_to_nested_folder(self, tools):
        """Test moving to a nested folder path."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids="1", target_folder="Projects/Finance/Invoices")
        assert "Projects/Finance/Invoices" in result
        assert "moved" in result.lower()
        assert mock_server.create.called

    @pytest.mark.asyncio
    async def test_move_emails_comma_separated(self, tools):
        """Test move_emails with comma-separated UID string."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails(uids="10,11", target_folder="Archive")
        assert "10" in result
        assert "11" in result
        assert "2 email(s)" in result
