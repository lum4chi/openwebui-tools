"""Auto-generated test module."""
import pytest

from imap_mailbox import Tools
from unittest.mock import MagicMock, patch

""" imaplib not directly used but the exception import comes from conftest. """


class TestDeleteEmailEmptyMailbox:
    """Test delete_email when mailbox is empty (lines 859-860)."""

    @pytest.mark.asyncio
    async def test_delete_email_empty_mailbox(self):
        """Test delete_email when mailbox is empty (lines 859-860)."""
        t = Tools()
        t.valves.imap_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.allow_delete_single = True

        mock_server = MagicMock()
        mock_server.login.return_value = ("OK", [b"Login successful"])
        mock_server.select.return_value = ("OK", [b"0 Messages"])
        mock_server.close.return_value = None
        mock_server.expunge.return_value = ("OK", [b"EXPUNGE"])

        def uid_side_effect(cmd, *args, **kwargs):
            if cmd == "search":
                return ("OK", [b""])
            return ("OK", [b""])

        mock_server.uid.side_effect = uid_side_effect

        with patch("imaplib.IMAP4_SSL", return_value=mock_server):
            result = await t.delete_email(email_index=1)
        assert "empty" in result.lower() or "Nothing to delete" in result
