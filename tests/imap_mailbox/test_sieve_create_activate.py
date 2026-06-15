"""Tests for ManageSieve create_and_activate_sieve_script method."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools

from .conftest import SieveMockBuilder


class TestCreateAndActivateSieveScript:
    """Tests for the create_and_activate_sieve_script method."""

    def _make_client(self, active="existing", scripts=None):
        return SieveMockBuilder.make(active=active, scripts=scripts)

    @pytest.mark.asyncio
    async def test_create_and_activate_success(self, sieve_tools):
        """Test creating a script that gets activated."""
        sieve_tools.valves.allow_create_sieve = True
        # First call: no scripts exist (we check before create)
        # Then after putscript, active matches the new name
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        # First listscripts: empty (check for existing name)
        # Then after putscript, active matches the new name
        mock_client.listscripts.side_effect = [
            (None, []),
            ("my_filter", ["my_filter"]),  # After putscript, it's active
        ]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(
                name="my_filter", content='require "fileinto";\nif true { stop; }'
            )
        assert "created and activated successfully" in result
        mock_client.putscript.assert_called_once_with(
            "my_filter",
            'require "fileinto";\nif true { stop; }',
        )

    @pytest.mark.asyncio
    async def test_create_name_already_exists(self, sieve_tools):
        """Test creating with a name that already exists."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="filter1", content="new content")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_script_created_but_cannot_verify_active(self, sieve_tools):
        """Script is created with putscript(activate=True) but server may not honor activation."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [
            (None, []),  # Before: no scripts
            ("other_script", ["filter1"]),  # After: different active (server quirk)
        ]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="filter1", content="content")
        assert "Manual activation" in result or "manual activation" in result.lower()

    @pytest.mark.asyncio
    async def test_create_disabled(self, sieve_tools):
        """Test create when create permission is disabled."""
        mock_client = self._make_client()
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="x", content="y")
        assert "disabled" in result.lower() and "allow_create_sieve" in result

    @pytest.mark.asyncio
    async def test_create_no_scripts_available(self, sieve_tools):
        """Test when ManageSieve returns None (provider uses non-standard API)."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = None
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="x", content="y")
        # When lists returns None, _handle_sieve_list_result returns (None, [], err_msg).
        # scripts is [] so name not in scripts — proceed with putscript (may fail on provider)
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_no_credentials(self):
        """Test create returns error when credentials are missing."""
        t = Tools()
        t.valves.allow_create_sieve = True
        t.valves.username = ""
        t.valves.password = ""
        result = await t.create_and_activate_sieve_script(name="x", content="y")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_create_no_server(self, sieve_tools):
        """Test create returns error when server is not configured."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = ""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.create_and_activate_sieve_script(name="x", content="y")
        assert "server" in result.lower()

    @pytest.mark.asyncio
    async def test_create_putscript_error(self, sieve_tools):
        """Test create when putscript raises an exception."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        mock_client.putscript.side_effect = Exception("Server error")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_and_activate_sieve_script(name="x", content="y")
        assert "Error creating and activating" in result
