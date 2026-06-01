"""Tests for Sieve default valve values, port, and server fallback behavior."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import EncryptionMode, Tools


class TestSieveDefaults:
    """Test Sieve default configuration values."""

    @pytest.mark.asyncio
    async def test_sieve_default_valves(self):
        """Test that Sieve write valves default to False."""
        t = Tools()
        assert t.valves.allow_create_sieve is False
        assert t.valves.allow_update_sieve is False
        assert t.valves.allow_delete_sieve is False
        assert t.valves.allow_activate_sieve is False

    @pytest.mark.asyncio
    async def test_sieve_default_port(self):
        """Test that ManageSieve default port is 4190."""
        t = Tools()
        assert t.valves.manage_sieve_port == 4190
        assert t.valves.manage_sieve_encryption == EncryptionMode.starttls

    @pytest.mark.asyncio
    async def test_sieve_fallback_uses_imap_server(self, sieve_tools):
        """Test that missing manage_sieve_server falls back to imap_server."""
        sieve_tools.valves.imap_server = "imap.example.com"
        sieve_tools.valves.manage_sieve_server = ""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        client_mock = MagicMock(return_value=mock_client)
        with patch("imap_mailbox.Client", client_mock):
            await sieve_tools.create_sieve_script(name="x", content="y")
            client_mock.assert_called_once_with("imap.example.com", srvport=4190)
            mock_client.connect.assert_called_once()
