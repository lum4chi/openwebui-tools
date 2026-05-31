"""Auto-generated test module."""
import imaplib as _imaplib

import pytest

from imap_mailbox import Tools

_IMAP_EXCEPTION = getattr(_imaplib, "IMAP4Exception", Exception)

from unittest.mock import MagicMock, patch

from .conftest import _IMAP_EXCEPTION, _make_raw_email_with_attachment


class TestIMAPErrorsInOtherMethods:
    """Test IMAP exceptions are caught and returned as error strings in all public methods."""

    @pytest.mark.asyncio
    async def test_list_emails_imap_error(self, tools):
        """Test IMAP error handling in list_emails."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Connection refused")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_imap_error(self, tools):
        """Test IMAP error handling in list_inbox_emails."""
        tools.valves.allow_list_inbox = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Connection refused")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_inbox_emails(count=5)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_read_email_imap_error(self, tools):
        """Test IMAP error handling in read_email."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_imap_error(self, tools):
        """Test IMAP error handling in read_inbox_email."""
        tools.valves.allow_list_inbox = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Authentication failed")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.read_inbox_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_search_emails_imap_error(self, tools):
        """Test IMAP error handling in search_emails."""
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Timeout")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="test", count=10)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_delete_email_imap_error(self, tools):
        """Test IMAP error handling in delete_email."""
        tools.valves.allow_delete_single = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_email(email_index=1)
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_imap_error(self, tools):
        """Test IMAP error handling in delete_all_emails."""
        tools.valves.allow_delete_all = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.delete_all_emails()
        assert "IMAP Error" in result

    @pytest.mark.asyncio
    async def test_archive_email_imap_error(self, tools):
        """Test IMAP error handling in archive_email."""
        tools.valves.allow_archive = True
        mock_server = MagicMock()
        mock_server.login.side_effect = _IMAP_EXCEPTION("Disk error")
        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.archive_email(email_index=1)
        assert "IMAP Error" in result




class TestGenericExceptionErrors:
    """Test that generic (non-IMAP) exceptions are caught and returned properly."""

    @pytest.mark.asyncio
    async def test_list_emails_generic_error(self, tools):
        """Test generic exception handling in list_emails."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_emails(folder="INBOX", count=5)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_generic_error(self, tools):
        """Test generic exception handling in list_inbox_emails."""
        tools.valves.allow_list_inbox = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_inbox_emails(count=5)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_email_generic_error(self, tools):
        """Test generic exception handling in read_email."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_read_inbox_email_generic_error(self, tools):
        """Test generic exception handling in read_inbox_email."""
        tools.valves.allow_list_inbox = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_inbox_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_search_emails_generic_error(self, tools):
        """Test generic exception handling in search_emails."""
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.search_emails(query="test", count=10)
            assert "Error searching emails" in result

    @pytest.mark.asyncio
    async def test_delete_email_generic_error(self, tools):
        """Test generic exception handling in delete_email."""
        tools.valves.allow_delete_single = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.delete_email(email_index=1)
            assert "Error deleting email" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_generic_error(self, tools):
        """Test generic exception handling in delete_all_emails."""
        tools.valves.allow_delete_all = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.delete_all_emails()
            assert "Error deleting emails" in result

    @pytest.mark.asyncio
    async def test_archive_email_generic_error(self, tools):
        """Test generic exception handling in archive_email."""
        tools.valves.allow_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.archive_email(email_index=1)
            assert "Error archiving email" in result

    @pytest.mark.asyncio
    async def test_list_archive_emails_generic_error(self, tools):
        """Test generic exception handling in list_archive_emails."""
        tools.valves.allow_list_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_archive_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_archive_email_generic_error(self, tools):
        """Test generic exception handling in read_archive_email."""
        tools.valves.allow_list_archive = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_archive_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_trash_emails_generic_error(self, tools):
        """Test generic exception handling in list_trash_emails."""
        tools.valves.allow_list_trash = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_trash_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_trash_email_generic_error(self, tools):
        """Test generic exception handling in read_trash_email."""
        tools.valves.allow_list_trash = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_trash_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_sent_emails_generic_error(self, tools):
        """Test generic exception handling in list_sent_emails."""
        tools.valves.allow_list_sent = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_sent_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_read_sent_email_generic_error(self, tools):
        """Test generic exception handling in read_sent_email."""
        tools.valves.allow_list_sent = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.read_sent_email(email_index=1)
            assert "Error reading email" in result

    @pytest.mark.asyncio
    async def test_list_draft_emails_generic_error(self, tools):
        """Test generic exception handling in list_draft_emails."""
        tools.valves.allow_list_drafts = True
        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_draft_emails(count=10)
            assert "Error connecting to IMAP server" in result

    @pytest.mark.asyncio
    async def test_list_emails_server_not_configured(self, tools):
        """Test that list_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.list_emails(folder="INBOX", count=5)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_list_inbox_emails_server_not_configured(self, tools):
        """Test that list_inbox_emails returns error when imap_server is empty."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_list_inbox = True
        result = await t.list_inbox_emails(count=5)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_read_email_server_not_configured(self, tools):
        """Test that read_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.read_email(email_index=1)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_search_emails_server_not_configured(self, tools):
        """Test that search_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        result = await tools.search_emails(query="test", count=10)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_email_server_not_configured(self, tools):
        """Test that delete_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_delete_single = True
        result = await tools.delete_email(email_index=1)
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_server_not_configured(self, tools):
        """Test that delete_all_emails returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_delete_all = True
        result = await tools.delete_all_emails()
        assert "Error" in result and "server" in result

    @pytest.mark.asyncio
    async def test_archive_email_server_not_configured(self, tools):
        """Test that archive_email returns error when imap_server is empty."""
        tools = Tools()
        tools.valves.username = "testuser"
        tools.valves.password = "testpass"
        tools.valves.allow_archive = True
        result = await tools.archive_email(email_index=1)
        assert "Error" in result and "server" in result


class TestGenericExceptionEmailCount:
    """Test generic exception in get_email_count (lines 835-836)."""

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self):
        """Test get_email_count catches generic Exception (lines 835-836)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"

        with patch("imap_mailbox._IMAP_EXCEPTION", OSError):
            mock_server = MagicMock()
            mock_server.login.side_effect = NotImplementedError("Generic error")
            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await t.get_email_count()
            assert "Error checking mailbox" in result


class TestIMAPEmptyRawDataFetch:
    """Test IMAP email parsing when raw_data is empty or malformed."""

    @pytest.mark.asyncio
    async def test_list_emails_empty_raw_data(self, tools):
        """Test list_emails handles exception during UID fetch (lines 553-567)."""
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"101"])
            elif cmd == "fetch":
                return ("OK", [b"101 (FETCH)"])
            return ("OK", [b"101"])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.examine.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(count=5, folder="INBOX")
        assert "Error reading message" in result

    @pytest.mark.asyncio
    async def test_read_folder_email_attachments_shown(self, tools):
        """Test _read_folder_email shows attachment info when has_attachments=True (line 1160)."""
        raw_with_attach = _make_raw_email_with_attachment("a@b.com", "c@d.com", "Doc Attached", "Body")
        mock_server = MagicMock()

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b"42"])
            elif cmd == "fetch":
                return ("OK", [(b"42 (UID 42)", raw_with_attach)])
            return ("OK", [b"42"])

        mock_server.uid.side_effect = uid_side_effect
        mock_server.login.return_value = ("OK", None)
        mock_server.select.return_value = ("OK", [b"1"])

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools._read_folder_email(1, "INBOX")
        assert "Attachments:" in result or "Attachments" in result


class TestIMAPGetEmailCountException:
    """Test get_email_count exception handling."""

    @pytest.mark.asyncio
    async def test_get_email_count_server_error(self):
        """Test get_email_count handles runtime error during server operation."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()
        mock_server.login.return_value = None
        mock_server.select.side_effect = RuntimeError("connection dropped")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.get_email_count()
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_email_count_generic_exception(self):
        """Test get_email_count with non-IMAP generic exception (lines 835-836)."""
        t = Tools()
        t.valves.username = "u"
        t.valves.password = "p"
        t.valves.imap_server = "mail.example.com"

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", None)
        mock_server.uid.side_effect = AttributeError("broken connection")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.get_email_count()
        assert "Error" in result


class TestIMAPGetEmailCountServer:
    """Test get_email_count credential edge cases."""

    @pytest.mark.asyncio
    async def test_get_email_count_with_credentials_no_server(self):
        """Test get_email_count returns error when imap_server is not set but credentials are."""
        t = Tools()
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        result = await t.get_email_count()
        assert "Error" in result and "server" in result

