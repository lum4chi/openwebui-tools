"""Tests for ManageSieve rename_sieve_script method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import SieveMockBuilder


class TestRenameSieveScript:
    """Tests for the rename_sieve_script method."""

    def _make_client(self, active="filter1", scripts=None):
        """Create a configured mock ManageSieve client."""
        return SieveMockBuilder.make(active=active, scripts=scripts)

    @pytest.mark.asyncio
    async def test_rename_success(self, sieve_tools):
        """Test successful rename."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_client(active="old_name", scripts=["old_name", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="old_name", new_name="new_name")
        assert "renamed to 'new_name'" in result
        mock_client.renamescript.assert_called_once_with("old_name", "new_name")
        mock_client.setactive.assert_called_once_with("new_name")

    @pytest.mark.asyncio
    async def test_rename_non_active_script(self, sieve_tools):
        """Test renaming a non-active script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_client(active="filter2", scripts=["old_name", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="old_name", new_name="new_name")
        assert "renamed to 'new_name'" in result
        # setactive should NOT be called for non-active rename
        mock_client.setactive.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_old_name_not_found(self, sieve_tools):
        """Test renaming a script that doesn't exist."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="ghost", new_name="new_name")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_rename_new_name_exists(self, sieve_tools):
        """Test creating a rename where target name already exists."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="filter1", new_name="filter2")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_rename_new_name_same_as_old_ok(self, sieve_tools):
        """Test renaming to the same name (no-op but allowed)."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="filter1", new_name="filter1")
        assert "renamed to 'filter1'" in result

    @pytest.mark.asyncio
    async def test_rename_disabled(self, sieve_tools):
        """Test rename when update permission is disabled."""
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="old", new_name="new")
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_rename_no_scripts(self, sieve_tools):
        """Test rename when no scripts exist on server."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = SieveMockBuilder.empty()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="x", new_name="y")
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_rename_no_credentials(self):
        """Test rename returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_update_sieve = True
        t.valves.username = ""
        t.valves.password = ""
        result = await t.rename_sieve_script(old_name="x", new_name="y")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_rename_no_server(self, sieve_tools):
        """Test rename returns error when server is not configured."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = ""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.rename_sieve_script(old_name="x", new_name="y")
        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_rename_no_scripts_available(self, sieve_tools):
        """Test rename when ManageSieve returns None (unavailable → empty list)."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = None
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="x", new_name="y")
        # _handle_sieve_list_result converts None → (None, [], err), so scripts=[] triggers "No scripts" path
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_rename_operation_error(self, sieve_tools):
        """Test rename when renamescript raises an exception."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.renamescript.side_effect = Exception("Permission denied")
        mock_client.listscripts.return_value = ("filter1", ["filter1"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.rename_sieve_script(old_name="filter1", new_name="new_filter")
        assert "Error renaming" in result
