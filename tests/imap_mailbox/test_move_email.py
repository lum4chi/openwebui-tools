"""Tests for move_email method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import (
    _IMAP_EXCEPTION,
    _make_mock_server,
    _make_raw_email,
    patch_imap_mailbox_attr,
)


class TestMoveEmailFunctional:
    """Test the move_email method."""

    @pytest.mark.asyncio
    async def test_move_email_enabled_success(self, tools):
        """Test moving an email when permission is enabled."""
        tools.valves.allow_move = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "3")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Projects")
        assert "moved" in result.lower()
        assert "Projects" in result
        copy_call = [c for c in mock_server.uid.call_args_list if c[0][0] == "COPY"]
        assert len(copy_call) == 1
        assert mock_server.expunge.called

    @pytest.mark.asyncio
    async def test_move_email_disabled_by_default(self, tools):
        """Test move_email is blocked when allow_move is False."""
        assert tools.valves.allow_move is False
        result = await tools.move_email(email_index=1, target_folder="Projects")
        assert "disabled" in result.lower() and "allow_move" in result

    @pytest.mark.asyncio
    async def test_move_email_out_of_range(self, tools):
        """Test moving an email with an out-of-range index."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=99, target_folder="Projects")
        assert "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_move_email_empty_mailbox(self, tools):
        """Test moving from an empty mailbox."""
        tools.valves.allow_move = True
        mock_server = _make_mock_server([])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Projects")
        assert "empty" in result.lower() or "Nothing to move" in result

    @pytest.mark.asyncio
    async def test_move_email_custom_folder(self, tools):
        """Test moving with a custom source folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Trash", folder="INBOX")
        assert "INBOX" in result
        assert "Trash" in result
        assert "moved" in result.lower()

    @pytest.mark.asyncio
    async def test_move_email_no_credentials(self):
        """Test moving returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_move = True
        result = await t.move_email(email_index=1, target_folder="Projects")
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_move_email_to_nested_folder(self, tools):
        """Test moving to a nested folder path."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Projects/Finance/Invoices")
        assert "Projects/Finance/Invoices" in result
        assert "moved" in result.lower()
        assert mock_server.create.called
        mock_server.create.assert_called_with("Projects/Finance/Invoices")

    @pytest.mark.asyncio
    async def test_move_email_uid_in_response(self, tools):
        """Test that the moved email UID is included in response."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Projects")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_move_email_no_server(self):
        """Test move returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_move = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.move_email(email_index=1, target_folder="Projects")
        assert "Error" in result and "server" in result.lower()

    @pytest.mark.asyncio
    async def test_move_email_imap_error(self, tools):
        """Test move handles IMAP exceptions."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_email(email_index=1, target_folder="Projects")
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_move_email_generic_exception(self):
        """Test move handles unexpected generic exceptions."""

        # Patch _IMAP_EXCEPTION to a custom type that RuntimeError won't match
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
            result = await t.move_email(email_index=1, target_folder="Projects")
            assert "Error moving email" in result


class TestMoveEmailsByUid:
    """Test the move_emails_by_uid batch move method."""

    @pytest.mark.asyncio
    async def test_move_emails_single_uid_success(self, tools):
        """Test moving a single email by UID."""
        tools.valves.allow_move = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails_by_uid(email_uids=["42"], target_folder="Archive")
        assert "Emails" in result or "1 email" in result or "1 message" in result
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
            result = await tools.move_emails_by_uid(email_uids=["10", "11"], target_folder="Projects")
        assert "Moved 2 email(s)" in result
        assert "10" in result
        assert "11" in result
        assert "Projects" in result

    @pytest.mark.asyncio
    async def test_move_emails_disabled_by_default(self, tools):
        """Test move_emails_by_uid is blocked when allow_move is False."""
        tools.valves.allow_move = False
        result = await tools.move_emails_by_uid(email_uids=["1", "2"], target_folder="Projects")
        assert "disabled" in result.lower() and "allow_move" in result

    @pytest.mark.asyncio
    async def test_move_emails_empty_list(self, tools):
        """Test move with empty UID list."""
        tools.valves.allow_move = True
        result = await tools.move_emails_by_uid(email_uids=[], target_folder="Projects")
        assert "No UIDs" in result or "empty" in result.lower() or "at least one" in result

    @pytest.mark.asyncio
    async def test_move_emails_no_credentials(self):
        """Test move returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_move = True
        result = await t.move_emails_by_uid(email_uids=["1"], target_folder="Projects")
        assert "Error" in result and "credentials" in result

    @pytest.mark.asyncio
    async def test_move_emails_no_server(self):
        """Test move returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_move = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.move_emails_by_uid(email_uids=["1"], target_folder="Projects")
        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_move_emails_imap_error(self, tools):
        """Test move_emails_by_uid handles IMAP exceptions."""
        tools.valves.allow_move = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails_by_uid(email_uids=["42"], target_folder="Projects")
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_move_emails_custom_source_folder(self, tools):
        """Test batch move with custom source folder."""
        tools.valves.allow_move = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.move_emails_by_uid(email_uids=["1"], target_folder="Trash", folder="INBOX")
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
            result = await tools.move_emails_by_uid(email_uids=["1", "5"], target_folder="Projects")
        assert "Moved 1 email" in result
        assert "Failed to move 1 email" in result
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
            result = await t.move_emails_by_uid(email_uids=["42"], target_folder="Projects")
            assert "Error moving emails" in result
