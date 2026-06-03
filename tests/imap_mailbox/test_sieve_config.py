"""Tests for Sieve config paths: implicit TLS, _handle_sieve_list_result, _manage_sieve_connect, scripts=None guard."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import EncryptionMode, Tools


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
        """Test ManageSieve implicit TLS connect raises exception -> error string."""
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
