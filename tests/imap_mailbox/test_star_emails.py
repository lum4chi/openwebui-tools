"""Tests for star_emails / unstar_emails methods."""

from unittest.mock import MagicMock, patch

from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION, _make_mock_server, _make_raw_email, patch_imap_mailbox_attr


class TestStarEmails:
    """Test star_emails and unstar_emails methods."""

    async def test_star_emails_single(self, tools):
        """Test starring a single email."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids="42", folder="INBOX")
        assert "starred" in result
        assert "42" in result

    async def test_star_emails_multiple(self, tools):
        """Test starring multiple emails."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Msg", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11"), (raw, "12")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids=["10", "11"], folder="INBOX")
        assert "2 email(s)" in result
        assert "10" in result
        assert "11" in result

    async def test_star_emails_disabled_by_default(self, tools):
        """Test star_emails is blocked when allow_modify_flags is False."""
        tools.valves.allow_modify_flags = False
        result = await tools.star_emails(uids=["1", "2"], folder="INBOX")
        assert "disabled" in result.lower() and "allow_modify_flags" in result

    async def test_star_emails_no_uids(self, tools):
        """Test star_emails returns error when no UIDs are provided."""
        tools.valves.allow_modify_flags = True
        result = await tools.star_emails(uids="", folder="INBOX")
        assert "No UIDs" in result

    async def test_star_emails_no_credentials(self):
        """Test star_emails returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_modify_flags = True
        result = await t.star_emails(uids=["1"], folder="INBOX")
        assert "Error" in result and "credentials" in result

    async def test_star_emails_imap_error(self, tools):
        """Test star_emails handles IMAP exceptions."""
        tools.valves.allow_modify_flags = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids=["42"], folder="INBOX")
        assert "IMAP Error" in result

    async def test_star_emails_comma_separated(self, tools):
        """Test star_emails with comma-separated UIDs."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids="10,11", folder="INBOX")
        assert "10" in result
        assert "11" in result
        assert "2 email(s)" in result

    async def test_star_emails_custom_folder(self, tools):
        """Test star_emails with a custom source folder."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "1")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.star_emails(uids=["1"], folder="Custom/Folder")
        assert "Custom/Folder" in result
        assert "starred" in result

    async def test_star_emails_generic_exception(self):
        """Test star_emails handles unexpected exceptions."""

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
            result = await t.star_emails(uids=["42"], folder="INBOX")
            assert "Error starring emails" in result

    async def test_unstar_emails_single(self, tools):
        """Test unstarring a single email."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "42")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.unstar_emails(uids="42", folder="INBOX")
        assert "unstarred" in result
        assert "42" in result

    async def test_unstar_emails_multiple(self, tools):
        """Test unstarring multiple emails."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Msg", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.unstar_emails(uids=["10", "11"], folder="INBOX")
        assert "2 email(s)" in result
        assert "10" in result
        assert "11" in result

    async def test_unstar_emails_disabled_by_default(self, tools):
        """Test unstar_emails is blocked when allow_modify_flags is False."""
        tools.valves.allow_modify_flags = False
        result = await tools.unstar_emails(uids=["1", "2"], folder="INBOX")
        assert "disabled" in result.lower() and "allow_modify_flags" in result

    async def test_unstar_emails_no_uids(self, tools):
        """Test unstar_emails returns error when no UIDs are provided."""
        tools.valves.allow_modify_flags = True
        result = await tools.unstar_emails(uids="", folder="INBOX")
        assert "No UIDs" in result

    async def test_unstar_emails_imap_error(self, tools):
        """Test unstar_emails handles IMAP exceptions."""
        tools.valves.allow_modify_flags = True
        mock_server = MagicMock()
        mock_server.select.side_effect = _IMAP_EXCEPTION("IMAP connect failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.unstar_emails(uids=["42"], folder="INBOX")
        assert "IMAP Error" in result

    async def test_unstar_emails_comma_separated(self, tools):
        """Test unstar_emails with comma-separated UIDs."""
        tools.valves.allow_modify_flags = True
        raw = _make_raw_email("a@b.com", "c@d.com", "Test", "Body")
        mock_server = _make_mock_server([(raw, "10"), (raw, "11")])
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.unstar_emails(uids="10,11", folder="INBOX")
        assert "10" in result
        assert "unstarred" in result
