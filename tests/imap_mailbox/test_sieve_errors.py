"""Tests for Sieve connection errors, operation errors, and exception handling."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import SieveMockBuilder


class TestSieveConnectionErrors:
    """Test Sieve exception handling during operations (not just connection time)."""

    @pytest.mark.asyncio
    async def test_create_sieve_script_connection_error(self, tools):
        """Test create_sieve_script returns error when sievelib client.connect() raises."""
        tools.valves.allow_create_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("authentication failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.create_sieve_script(name="test", content='fileinto "test";')
            assert "Error" in result and "ManageSieve" in result

    @pytest.mark.asyncio
    async def test_create_sieve_script_put_error(self, tools):
        """Test create_sieve_script handles putscript() exception."""
        tools.valves.allow_create_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["existing"])
        mock_client.putscript.side_effect = Exception("server error")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.create_sieve_script(name="new", content="discard;")
            assert "Error" in result and "creating" in result.lower()

    @pytest.mark.asyncio
    async def test_get_sieve_script_list_error(self, tools):
        """Test get_sieve_script handles listscripts() exception."""
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = Exception("connection reset")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.get_sieve_script(name="x")
            assert "Error" in result and "retrieving" in result.lower()


class TestSieveOtherExceptions:
    """Test remaining Sieve exception paths."""

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_operation_error(self, tools):
        """Test list_sieve_scripts handles listscripts() exception."""
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = Exception("list failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.list_sieve_scripts()
            assert "Error" in result and "listing" in result.lower()

    @pytest.mark.asyncio
    async def test_update_sieve_script_no_scripts(self, tools):
        """Test update_sieve_script returns error when no scripts exist."""
        tools.valves.allow_update_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        with patch("imap_mailbox.Client", return_value=SieveMockBuilder.make(active=None, scripts=[])):
            result = await tools.update_sieve_script(name="x", content="y")
            assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_update_sieve_script_put_error(self, tools):
        """Test update_sieve_script handles putscript() exception."""
        tools.valves.allow_update_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["existing"])
        mock_client.putscript.side_effect = Exception("write failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.update_sieve_script(name="existing", content="new content")
            assert "Error" in result and "updating" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_sieve_script_empty(self, tools):
        """Test delete_sieve_script when no scripts exist."""
        tools.valves.allow_delete_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        with patch("imap_mailbox.Client", return_value=SieveMockBuilder.make(active=None, scripts=[])):
            result = await tools.delete_sieve_script(name="nonexistent")
            assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_delete_sieve_script_error(self, tools):
        """Test delete_sieve_script handles deletescript() exception."""
        tools.valves.allow_delete_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["to_delete"])
        mock_client.deletescript.side_effect = Exception("delete failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.delete_sieve_script(name="to_delete")
            assert "Error" in result and "deleting" in result.lower()

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_empty(self, tools):
        """Test set_active_sieve_script when no scripts exist."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        with patch("imap_mailbox.Client", return_value=SieveMockBuilder.make(active=None, scripts=[])):
            result = await tools.set_active_sieve_script(name="any")
            assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_error(self, tools):
        """Test set_active_sieve_script handles setactive() exception."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["active1"])
        mock_client.setactive.side_effect = Exception("activate failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.set_active_sieve_script(name="active1")
            assert "Error" in result and "activating" in result.lower()

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_error(self, tools):
        """Test deactivate_sieve_script handles setactive() exception."""
        tools.valves.allow_activate_sieve = True
        tools.valves.imap_server = "sieve.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("active1", ["active1"])
        mock_client.setactive.side_effect = Exception("deactivate failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await tools.deactivate_sieve_script()
            assert "Error" in result and "deactivating" in result.lower()
