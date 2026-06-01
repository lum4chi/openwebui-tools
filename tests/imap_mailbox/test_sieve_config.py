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
