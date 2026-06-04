"""Tests for mark_emails method (set/unset \\Seen flag)."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email, patch_imap_mailbox_attr


class TestMarkEmails:
    """Test the mark_emails method."""

    async def test_mark_emails_as_read_single_uid(self, tools):
        """Test marking a single email as read."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids="42", folder="INBOX", read=True)
        assert "read" in result
        assert "42" in result

    async def test_mark_emails_as_read_multiple_uids(self, tools):
        """Test marking multiple emails as read."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Msg", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11"), (raw, "12")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids=["10", "11"], folder="INBOX", read=True)
        assert "2 email(s)" in result
        assert "10" in result
        assert "11" in result

    async def test_mark_emails_as_unread(self, tools):
        """Test marking emails as unread (unset \\Seen)."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids="42", folder="INBOX", read=False)
        assert "unread" in result
        assert "42" in result

    async def test_mark_emails_disabled_by_default(self, tools):
        """Test mark_emails is blocked when allow_modify_flags is False."""
        tools.valves.allow_modify_flags = False
        result = await tools.mark_emails(uids=["1", "2"], folder="INBOX", read=True)
        assert "disabled" in result.lower() and "allow_modify_flags" in result

    async def test_mark_emails_no_uids(self, tools):
        """Test mark_emails returns error when no UIDs are provided."""
        tools.valves.allow_modify_flags = True
        result = await tools.mark_emails(uids="", folder="INBOX")
        assert "No UIDs" in result

    async def test_mark_emails_no_credentials(self):
        """Test mark_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_modify_flags = True
        result = await t.mark_emails(uids=["1"], folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_mark_emails_no_server(self):
        """Test mark_emails returns error when imap_server is not configured."""
        t = Tools()
        t.valves.allow_modify_flags = True
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.mark_emails(uids=["1"], folder="INBOX")
        assert "server" in result.lower()

    async def test_mark_emails_imap_error(self, tools):
        """Test mark_emails handles IMAP exceptions."""
        tools.valves.allow_modify_flags = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids=["42"], folder="INBOX")
        assert "IMAP Error" in result

    async def test_mark_emails_comma_separated(self, tools):
        """Test mark_emails with comma-separated UID string."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids="10,11", folder="INBOX", read=True)
        assert "10" in result
        assert "11" in result
        assert "2 email(s)" in result

    async def test_mark_emails_custom_folder(self, tools):
        """Test mark_emails with a custom source folder."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids=["1"], folder="Custom/Folder", read=False)
        assert "Custom/Folder" in result
        assert "unread" in result

    async def test_mark_emails_generic_exception(self):
        """Test mark_emails handles unexpected exceptions."""

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
            t.valves.allow_modify_flags = True
            result = await t.mark_emails(uids=["42"], folder="INBOX", read=True)
            assert "Error marking emails" in result

    async def test_mark_emails_partial_failure(self, tools):
        """Test batch mark where some UIDs fail."""

        def override_stores(cmd, criteria=None, *args, **kwargs):
            if cmd.upper() == "STORE":
                uid = criteria
                if isinstance(uid, (list, tuple)):
                    uid = uid[0]
                if uid == "5":
                    raise Exception("no such UID")
                return ("OK", [b"FLAGS (\\Seen)"])
            return ("OK", [b""])

        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")], override_uid=override_stores)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.mark_emails(uids=["1", "5"], folder="INBOX", read=True)
        assert "1" in result
        assert "5" in result
        assert "Failed" in result
