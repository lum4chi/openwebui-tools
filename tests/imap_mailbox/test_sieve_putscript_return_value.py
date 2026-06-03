"""Verify putscript() boolean return value is checked — preventing silent failures."""

from unittest.mock import MagicMock, patch

import pytest


class TestPutscriptReturnValueChecked:
    """Ensure methods that call putscript() check its boolean return value."""

    @pytest.mark.asyncio
    async def test_update_sieve_script_putscript_fails_returns_error(self, sieve_tools):
        """update_sieve_script returns an error when putscript() returns False."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("active1", ["script_a"])
        mock_client.putscript.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.update_sieve_script(name="script_a", content="rejected content")
        assert "rejected" in result.lower()
        assert "Error" in result
        mock_client.logout.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_sieve_script_putscript_succeeds_returns_success(self, sieve_tools):
        """update_sieve_script returns success when putscript() returns True."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("active1", ["script_a"])
        mock_client.putscript.return_value = True
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.update_sieve_script(name="script_a", content="new content")
        assert "updated successfully" in result

    @pytest.mark.asyncio
    async def test_create_and_activate_putscript_fails_returns_error(self, sieve_tools):
        """create_and_activate_sieve_script returns error when putscript() returns False."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        mock_client.putscript.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="new_script", content="rejected")
        assert "rejected" in result.lower()
        assert "Error" in result
        mock_client.logout.assert_called_once()
