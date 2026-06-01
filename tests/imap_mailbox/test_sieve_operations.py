"""Tests for ManageSieve filter CRUD: list, get, create, update, delete, activate."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import SieveMockBuilder


class TestSieveTools:
    """Tests for ManageSieve filter management features."""

    def _make_sieve_mock(self, active: str | None = "filter1", scripts: list[str] | None = None):
        """Create a mock ManageSieve client with script data."""
        return SieveMockBuilder.make(active=active, scripts=scripts)

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_success(self, sieve_tools):
        """Test listing Sieve scripts on the server."""
        mock_client = self._make_sieve_mock(active="filter1", scripts=["filter1", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.list_sieve_scripts()
        assert "filter1" in result
        assert "filter2" in result
        assert ">>>" in result or "filter1" in result
        assert "active" in result.lower()

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_empty(self, sieve_tools):
        """Test listing when no Sieve scripts exist."""
        mock_client = SieveMockBuilder.empty()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.list_sieve_scripts()
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_get_sieve_script_success(self, sieve_tools):
        """Test retrieving a Sieve script by name."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.get_sieve_script(name="filter1")
        assert "Sieve Script: filter1" in result
        assert "fileinto" in result

    @pytest.mark.asyncio
    async def test_get_sieve_script_not_found(self, sieve_tools):
        """Test retrieving a non-existent script."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.get_sieve_script(name="nonexistent")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_get_sieve_script_empty_scripts(self, sieve_tools):
        """Test retrieving a script when none exist."""
        mock_client = SieveMockBuilder.empty()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.get_sieve_script(name="any")
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_create_sieve_script_success(self, sieve_tools):
        """Test creating a new Sieve script."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = self._make_sieve_mock()
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_sieve_script(name="auto_filter", content="require 'fileinto';")
        assert "created successfully" in result
        mock_client.putscript.assert_called_once_with("auto_filter", "require 'fileinto';")

    @pytest.mark.asyncio
    async def test_create_sieve_script_already_exists(self, sieve_tools):
        """Test creating a script that already exists."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_sieve_script(name="filter1", content="new content")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_sieve_script_disabled(self, sieve_tools):
        """Test creating a script when create permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_sieve_script(name="new_script", content="ignore")
        assert "disabled" in result.lower() and "allow_create_sieve" in result

    @pytest.mark.asyncio
    async def test_update_sieve_script_success(self, sieve_tools):
        """Test updating an existing Sieve script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.update_sieve_script(name="filter1", content="updated content here")
        assert "updated successfully" in result
        mock_client.putscript.assert_called_once_with("filter1", "updated content here")

    @pytest.mark.asyncio
    async def test_update_sieve_script_not_found(self, sieve_tools):
        """Test updating a non-existent script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.update_sieve_script(name="ghost", content="stuff")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_update_sieve_script_disabled(self, sieve_tools):
        """Test updating a script when update permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.update_sieve_script(name="x", content="y")
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_delete_sieve_script_success(self, sieve_tools):
        """Test deleting a Sieve script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        mock_client.deletescript.assert_called_once_with("filter2")

    @pytest.mark.asyncio
    async def test_delete_sieve_script_active_deactivates(self, sieve_tools):
        """Test that deleting an active script also deactivates it."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock(active="filter2", scripts=["filter1", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        mock_client.deletescript.assert_called_once_with("filter2")
        mock_client.setactive.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_delete_sieve_script_not_found(self, sieve_tools):
        """Test deleting a non-existent script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="ghost_script")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_sieve_script_disabled(self, sieve_tools):
        """Test deleting when delete permission is disabled."""
        mock_client = SieveMockBuilder.make()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="x")
        assert "disabled" in result.lower() and "allow_delete_sieve" in result

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_success(self, sieve_tools):
        """Test activating a Sieve script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock()
        mock_client.listscripts.return_value = (None, ["filter1", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.set_active_sieve_script(name="filter2")
        assert "now active" in result
        mock_client.setactive.assert_called_once_with("filter2")

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_not_found(self, sieve_tools):
        """Test activating a non-existent script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.set_active_sieve_script(name="phantom")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_disabled(self, sieve_tools):
        """Test activating when permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.set_active_sieve_script(name="x")
        assert "disabled" in result.lower() and "allow_activate_sieve" in result

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_success(self, sieve_tools):
        """Test deactivating the active Sieve script."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock(active="filter1")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.deactivate_sieve_script()
        assert "deactivated" in result.lower()
        mock_client.setactive.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_none_active(self, sieve_tools):
        """Test deactivating when no script is active."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = self._make_sieve_mock(active=None)
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.deactivate_sieve_script()
        assert "No Sieve script is currently active" in result

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_disabled(self, sieve_tools):
        """Test deactivating when permission is disabled."""
        mock_client = self._make_sieve_mock()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.deactivate_sieve_script()
        assert "disabled" in result.lower() and "allow_activate_sieve" in result

    @pytest.mark.asyncio
    async def test_sieve_no_credentials(self):
        """Test Sieve methods return error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await t.list_sieve_scripts()
            assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_server(self, sieve_tools):
        """Test Sieve methods return error when imap_server is empty."""
        sieve_tools.valves.imap_server = ""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.list_sieve_scripts()
            assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_credentials_get(self):
        """Test get_sieve_script returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        result = await t.get_sieve_script(name="x")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_credentials_update(self):
        """Test update_sieve_script returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        t.valves.allow_update_sieve = True
        result = await t.update_sieve_script(name="x", content="y")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_credentials_delete(self):
        """Test delete_sieve_script returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        t.valves.allow_delete_sieve = True
        result = await t.delete_sieve_script(name="x")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_credentials_set_active(self):
        """Test set_active_sieve_script returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        t.valves.allow_activate_sieve = True
        result = await t.set_active_sieve_script(name="x")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_sieve_no_credentials_deactivate(self):
        """Test deactivate_sieve_script returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        t.valves.allow_activate_sieve = True
        result = await t.deactivate_sieve_script()
        assert "credentials" in result.lower()
