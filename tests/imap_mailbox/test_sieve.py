"""Auto-generated test module."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import EncryptionMode, Tools

from .conftest import SieveMockBuilder


class TestSieveTools:
    """Tests for ManageSieve filter management features."""

    def _make_sieve_mock(self, active: str | None = "filter1", scripts: list[str] | None = None):
        """Create a mock ManageSieve client with script data. (Use SieveMockBuilder directly.)"""
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
        mock_client.listscripts.return_value = (None, [])  # no scripts yet
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


class TestSieveImplicitTLS:
    """Test ManageSieve with implicit TLS encryption mode (lines 153-158)."""

    @pytest.fixture
    def sieve_tools_implicit(self):
        t = Tools()
        t.valves.imap_server = "sieve.example.com"
        t.valves.username = "testuser"
        t.valves.password = "testpass"
        t.valves.manage_sieve_server = ""
        t.valves.manage_sieve_port = 4190
        t.valves.manage_sieve_encryption = EncryptionMode.implicit
        t.valves.manage_sieve_timeout = 30
        return t

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_implicit_tls(self, sieve_tools_implicit):
        """Test Sieve connect uses implicit TLS (ssl=True, starttls=False) at lines 153-158."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("active1", ["script1", "script2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools_implicit.list_sieve_scripts()
        mock_client.connect.assert_called_once_with("testuser", "testpass", ssl=True, starttls=False)

    @pytest.mark.asyncio
    async def test_get_sieve_script_implicit_tls(self, sieve_tools_implicit):
        """Test get_sieve_script works with implicit TLS connection."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("active1", ["script1"])
        mock_client.getscript.return_value = "require 'fileinto';\nif header :contains ..."
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools_implicit.get_sieve_script(name="script1")
        mock_client.connect.assert_called_once_with("testuser", "testpass", ssl=True, starttls=False)
        assert "require" in result

    @pytest.mark.asyncio
    async def test_manage_sieve_connect_implicit_tls_error(self, sieve_tools_implicit):
        """Test ManageSieve implicit TLS connect raises exception → error string."""
        mock_client = MagicMock()
        mock_client.connect.side_effect = OSError("TLS handshake failed")

        with patch("imap_mailbox.Client", return_value=mock_client):
            result = sieve_tools_implicit._manage_sieve_connect()
        assert isinstance(result, str) and "ManageSieve Error" in result


class TestHandleSieveListResult:
    """Tests for _handle_sieve_list_result edge cases (lines 55, 59-61)."""

    @pytest.mark.asyncio
    async def test_handle_none_returns_default_error(self):
        import imap_mailbox as im

        result = im._handle_sieve_list_result(None)
        active, scripts, msg = result
        assert active is None
        assert scripts == []
        assert msg is not None
        assert "Server responded" in msg

    @pytest.mark.asyncio
    async def test_handle_unparseable_empty_list(self):
        import imap_mailbox as im

        result = im._handle_sieve_list_result([])
        active, scripts, msg = result
        assert active is None
        assert scripts == []
        assert msg is not None
        assert "Unexpected" in msg

    @pytest.mark.asyncio
    async def test_handle_single_element_tuple(self):
        import imap_mailbox as im

        result = im._handle_sieve_list_result(("active",))
        active, scripts, msg = result
        assert active is None
        assert scripts == []
        assert msg is not None
        assert "Unexpected" in msg


class TestManageSieveConnectNonTrue:
    """Test _manage_sieve_connect connect() returns non-True (line 198)."""

    @pytest.mark.asyncio
    async def test_manage_sieve_connect_false_return(self, tools):
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = tools._manage_sieve_connect()
        assert isinstance(result, str) and "Connection or authentication failed" in result

    @pytest.mark.asyncio
    async def test_manage_sieve_connect_zero_return(self, tools):
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"
        mock_client = MagicMock()
        mock_client.connect.return_value = 0
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = tools._manage_sieve_connect()
        assert isinstance(result, str) and "Connection or authentication failed" in result


class TestSieveScriptsNoneGuard:
    """Test Sieve methods with _handle returning scripts=None (lines 218-219, etc.)."""

    @pytest.fixture
    def st(self):
        import imap_mailbox as im

        tools = im.Tools()
        tools.valves.imap_server = "s.example.com"
        tools.valves.username = "u"
        tools.valves.password = "p"
        return tools

    @pytest.mark.asyncio
    async def test_list_sieve_scripts_handle_none_scripts(self, st):
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active_script", None, "scripts not available")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.list_sieve_scripts()
                assert isinstance(result, str) and "no scripts" in result.lower() and "managesieve" in result.lower()
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_get_sieve_script_handle_none_scripts(self, st):
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "get script error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.get_sieve_script(name="testscript")
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_create_sieve_script_handle_none_scripts(self, st):
        st.valves.allow_create_sieve = True
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "create error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.create_sieve_script(name="new", content="discard;")
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_update_sieve_script_handle_none_scripts(self, st):
        st.valves.allow_update_sieve = True
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "update error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.update_sieve_script(name="x", content="y")
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_delete_sieve_script_handle_none_scripts(self, st):
        st.valves.allow_delete_sieve = True
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "delete error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.delete_sieve_script(name="x")
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_handle_none_scripts(self, st):
        st.valves.allow_activate_sieve = True
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "activate error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.set_active_sieve_script(name="x")
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_handle_none_scripts(self, st):
        st.valves.allow_activate_sieve = True
        import imap_mailbox as im

        orig_handle = im._handle_sieve_list_result

        def handle_none(*_args):
            return ("active", None, "deactivate error")

        mock_client = MagicMock()
        mock_client.connect.return_value = True

        try:
            with patch("imap_mailbox.Client", return_value=mock_client):
                im._handle_sieve_list_result = handle_none
                result = await st.deactivate_sieve_script()
                assert isinstance(result, str) and (
                    "no scripts" in result.lower() or "managesieve returned" in result.lower()
                )
        finally:
            im._handle_sieve_list_result = orig_handle
