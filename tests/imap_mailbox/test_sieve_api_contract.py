"""Verify ManageSieve API contract: putscript args, return value checks, setactive arguments."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import SieveMockBuilder


class TestPutscriptSignature:
    """Ensure putscript() is called with exactly (name, content) — no extra kwargs."""

    @pytest.mark.asyncio
    async def test_create_sieve_script_putscript_two_args(self, sieve_tools):
        """create_sieve_script calls putscript(name, content) with no extra kwargs."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = SieveMockBuilder.make(active=None, scripts=[])
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_sieve_script(name="test_script", content='require "fileinto";')
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "test_script"
        assert args[1] == 'require "fileinto";'
        assert kwargs == {}, "putscript should not receive keyword arguments"

    @pytest.mark.asyncio
    async def test_update_sieve_script_putscript_two_args(self, sieve_tools):
        """update_sieve_script calls putscript(name, content) with no extra kwargs."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = SieveMockBuilder.make()
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.update_sieve_script(name="filter1", content="new content updated")
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "filter1"
        assert args[1] == "new content updated"
        assert kwargs == {}, "putscript should not receive keyword arguments"


class TestPutscriptReturnValue:
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

    @pytest.mark.asyncio
    async def test_create_sieve_script_putscript_fails_returns_error(self, sieve_tools):
        """create_sieve_script returns error when putscript() returns False."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        mock_client.putscript.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_sieve_script(name="new_script", content="rejected")
        assert "rejected" in result.lower()
        assert "Error" in result
        mock_client.logout.assert_called_once()


class TestSetactiveNoNone:
    """Ensure setactive() is never called with None — sievelib calls .encode() on the argument."""

    @pytest.mark.asyncio
    async def test_deactivate_sieve_script_calls_setactive_with_empty_string(self, sieve_tools):
        """deactivate_sieve_script passes '' to setactive, not None."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = SieveMockBuilder.make(active="filter1")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.deactivate_sieve_script()
        assert "deactivated" in result.lower()
        args, kwargs = mock_client.setactive.call_args
        assert args[0] == "", f"setactive called with {args[0]!r} instead of empty string"

    @pytest.mark.asyncio
    async def test_delete_active_script_calls_setactive_with_empty_string(self, sieve_tools):
        """delete_sieve_script calls setactive('') when deleting an active script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = SieveMockBuilder.make(active="filter2", scripts=["filter1", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        args, kwargs = mock_client.setactive.call_args
        assert args[0] == "", f"setactive called with {args[0]!r} instead of empty string"

    @pytest.mark.asyncio
    async def test_delete_inactive_script_calls_setactive_once_not_twice(self, sieve_tools):
        """delete_sieve_script does NOT call setactive when deleting an inactive script."""
        sieve_tools.valves.allow_delete_sieve = True
        mock_client = SieveMockBuilder.make(active="filter1", scripts=["filter1", "filter2"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.delete_sieve_script(name="filter2")
        assert "deleted successfully" in result
        # setactive should NOT be called for non-active scripts
        mock_client.setactive.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_active_sieve_script_calls_setactive_with_name(self, sieve_tools):
        """set_active_sieve_script passes the script name to setactive."""
        sieve_tools.valves.allow_activate_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["my_script"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.set_active_sieve_script(name="my_script")
        assert "now active" in result
        args, kwargs = mock_client.setactive.call_args
        assert args[0] == "my_script"

    @pytest.mark.asyncio
    async def test_create_sieve_script_no_setactive_call(self, sieve_tools):
        """create_sieve_script does NOT call setactive (only activate does)."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = SieveMockBuilder.make(active=None, scripts=[])
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_sieve_script(name="new_script", content='require "fileinto";')
        mock_client.setactive.assert_not_called()
