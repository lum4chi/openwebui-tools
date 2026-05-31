"""Auto-generated test module."""

import poplib
from unittest.mock import MagicMock, patch

import pytest

from pop3_mailbox import Tools


class TestPOP3DeleteErrorProto:
    """Test delete_email error_proto handler (line 423)."""

    @pytest.mark.asyncio
    async def test_delete_email_error_proto(self):
        """Test delete_email catches poplib.error_proto during dele() (line 423)."""

        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.allow_delete_single = True

        mock_server = MagicMock()
        mock_server.stat.return_value = (1, 500)
        mock_server.dele.side_effect = poplib.error_proto("DEL failed - mailbox locked")
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_email(email_index=1)
        assert "POP3 Error" in result


class TestPOP3DeleteSpecialCases:
    """Test delete_email and delete_all_emails special cases."""

    @pytest.mark.asyncio
    async def test_delete_all_emails_empty(self):
        """Test delete_all_emails returns early for empty mailbox."""
        t = Tools()
        t.valves.allow_delete_all = True
        t.valves.pop3_server = "mail.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"

        mock_server = MagicMock()
        mock_server.stat.return_value = (0, 0)
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_all_emails()
        assert "empty" in result.lower()


class TestPOP3DeleteEdgeCases:
    """Additional edge cases for delete operations."""

    @pytest.mark.asyncio
    async def test_delete_email_index_zero(self):
        """Test delete_email with index 0 (not a valid index)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.allow_delete_single = True

        mock_server = MagicMock()
        mock_server.stat.return_value = (5, 5000)
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_email(email_index=0)
        assert "out of range" in result.lower()


class TestPOP3DeleteAllInnerException:
    """Test delete_all_emails inner loop exception (lines 454-457)."""

    @pytest.mark.asyncio
    async def test_delete_all_emails_inner_loop_error_proto(self):
        """Test delete_all_emails where dele() raises error_proto mid-loop (line 454)."""

        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.allow_delete_all = True

        mock_server = MagicMock()
        mock_server.stat.return_value = (3, 3000)
        call_count = [0]

        def dele_side_effect(idx):
            call_count[0] += 1
            if call_count[0] <= 2:
                return None  # First two deletions succeed
            else:
                raise poplib.error_proto("DEL failed")

        mock_server.dele.side_effect = dele_side_effect
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_all_emails()
        assert "POP3 Error" in result

    @pytest.mark.asyncio
    async def test_delete_all_emails_inner_loop_generic_exception(self):
        """Test delete_all_emails where dele() raises generic Exception mid-loop (line 456-457)."""
        t = Tools()
        t.valves.username = "user"
        t.valves.password = "pass"
        t.valves.pop3_server = "pop3.example.com"
        t.valves.allow_delete_all = True

        mock_server = MagicMock()
        mock_server.stat.return_value = (2, 2000)
        call_count = [0]

        def dele_side_effect(idx):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # First deletion succeeds
            else:
                raise RuntimeError("disk full")

        mock_server.dele.side_effect = dele_side_effect
        mock_server.quit.return_value = None

        with patch("poplib.POP3_SSL", return_value=mock_server):
            result = await t.delete_all_emails()
        assert "Error deleting" in result or "disk full" in result
