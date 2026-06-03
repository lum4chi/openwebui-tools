"""Tests for copy_emails method."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email


class TestCopyEmails:
    """Test the copy_emails method."""

    async def test_copy_emails_single_uid(self, tools):
        """Test copying a single email."""
        raw = _make_raw_email("alice@example.com", "bob@example.com", "Invoice", "Please pay.")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids="42", target_folder="Archive", folder="INBOX")
        assert "copied" in result
        assert "42" in result
        assert "Archive" in result

    async def test_copy_emails_multiple_uids(self, tools):
        """Test copying multiple emails."""
        raw = _make_raw_email("a@b.com", "c@d.com", "Msg", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11"), (raw, "12")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids=["10", "11"], target_folder="Projects", folder="INBOX")
        assert "2 email(s)" in result
        assert "10" in result
        assert "11" in result

    async def test_copy_emails_no_credentials(self):
        """Test copy_emails returns error when credentials are missing."""
        t = Tools()
        result = await t.copy_emails(uids=["1"], target_folder="Projects", folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_copy_emails_no_server(self):
        """Test copy_emails returns error when imap_server is not configured."""
        t = Tools()
        t.valves.imap_server = ""
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.copy_emails(uids=["1"], target_folder="Projects", folder="INBOX")
        assert "server" in result.lower()

    async def test_copy_emails_imap_error(self, tools):
        """Test copy_emails handles IMAP exceptions."""
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids=["42"], target_folder="Projects", folder="INBOX")
        assert "IMAP Error" in result

    async def test_copy_emails_to_nested_folder(self, tools):
        """Test copying to a nested folder path."""
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids="1", target_folder="Projects/Finance/Invoices", folder="INBOX")
        assert "Projects/Finance/Invoices" in result
        assert "copied" in result
        assert mock_server.create.called

    async def test_copy_emails_comma_separated(self, tools):
        """Test copy_emails with comma-separated UID string."""
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids="10,11", target_folder="Archive", folder="INBOX")
        assert "10" in result
        assert "11" in result
        assert "2 email(s)" in result

    async def test_copy_emails_partials_success_and_failure(self, tools):
        """Test copy where some UIDs succeed and some fail."""

        def override_copy(cmd, criteria=None, *args, **kwargs):
            if cmd == "COPY":
                uid = criteria
                if isinstance(uid, (list, tuple)):
                    uid = uid[0]
                if uid == "5":
                    raise Exception("no such UID")
                return ("OK", [b""])
            return ("OK", [b""])

        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")], override_uid=override_copy)
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.copy_emails(uids=["1", "5"], target_folder="Projects", folder="INBOX")
        assert "1" in result
        assert "5" in result
        assert "Failed" in result
