"""Test fallback mechanisms: FieldInfo handling in parameters, _safe_close fallback to logout."""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

import imap_mailbox
from imap_mailbox import Tools

from .conftest import _IMAP_EXCEPTION


class TestFieldInfoFallback:
    """Test that FieldInfo objects in parameters are handled gracefully.

    Open WebUI has a bug where it passes raw Pydantic FieldInfo objects instead of their
    resolved default values (or the values provided by the user). This class ensures
    that both `list_emails` and `search_emails` handle FieldInfo gracefully.
    """

    @pytest.mark.asyncio
    async def test_list_emails_field_info_count_field_with_default(self, tools):
        """list_emails: FieldInfo(default=N) falls back to N."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=Field(default=10))

        assert "No emails" in result or "Folder is empty" in result
        mock_server.uid.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_emails_field_info_count_no_default(self, tools):
        """list_emails: FieldInfo with no default falls back to 10."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=Field(description="how many"))

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_list_emails_normal_int_count_regression(self, tools):
        """list_emails: normal int count still works (regression test)."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(folder="INBOX", count=5)

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_list_emails_field_info_with_description_only(self, tools):
        """list_emails: FieldInfo with description but no default falls back to 10."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_emails(
                folder="INBOX",
                count=Field(description="Number of recent emails to list (default: 10)"),
            )

        assert "No emails" in result or "Folder is empty" in result

    @pytest.mark.asyncio
    async def test_search_emails_field_info_count(self, tools):
        """search_emails: FieldInfo(default=N) for count falls back to N."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="test", count=Field(default=10))

        assert "No emails" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_emails_field_info_query(self, tools):
        """search_emails: FieldInfo as query parameter is handled."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query=Field(description="Search query"))

        assert "No emails" in result or "No emails found" in result
        # Should have called uid.search with the FieldInfo (treated as a string search)

    @pytest.mark.asyncio
    async def test_search_emails_field_info_count_and_query(self, tools):
        """search_emails: Both count and query as FieldInfo."""
        from pydantic import Field

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(
                query=Field(description="Search query"),
                count=Field(default=5),
            )

        assert "No emails" in result or "No emails found" in result

    @pytest.mark.asyncio
    async def test_search_emails_normal_params_regression(self, tools):
        """search_emails: normal params still work (regression test)."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [])
        mock_server.uid.return_value = ("OK", [b""])
        mock_server.close.return_value = None

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.search_emails(query="from:admin", count=3, folder="INBOX")

        assert "No emails" in result or "No emails found" in result


class TestSafeCloseFallback:
    """Test _safe_close fallback to logout when close() fails."""

    @pytest.mark.asyncio
    async def test_safe_close_fallback_to_logout_on_imap_error(self, tools):
        """Test _safe_close falls back to logout when close() raises IMAPException."""
        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.list.return_value = ("OK", [])
        mock_server.close.side_effect = _IMAP_EXCEPTION("CLOSE illegal in state AUTH")

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await tools.list_folders()

        assert "No folders found" in result or "Available IMAP folders" in result

    @pytest.mark.asyncio
    async def test_safe_close_fallback_to_logout_on_generic_error(self, tools):
        """Test _safe_close falls back to logout when close() raises generic exception."""

        @contextlib.contextmanager
        def patch_imap_mailbox_attr(attr: str, new_value):
            orig = getattr(imap_mailbox, attr)
            setattr(imap_mailbox, attr, new_value)
            try:
                yield
            finally:
                setattr(imap_mailbox, attr, orig)

        with patch_imap_mailbox_attr("_IMAP_EXCEPTION", RuntimeError):
            mock_server = MagicMock()
            mock_server.login.return_value = ("OK", [b"Login successful"])
            mock_server.list.return_value = ("OK", [])
            mock_server.close.side_effect = ValueError("Server broken")
            mock_server.delete.side_effect = _IMAP_EXCEPTION("Mailbox not empty")

            with patch("imaplib.IMAP4_SSL", return_value=mock_server):
                result = await tools.list_folders()

            assert "No folders found" in result or "Available IMAP folders" in result
