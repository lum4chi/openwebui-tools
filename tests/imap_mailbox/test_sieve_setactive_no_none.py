"""Verify setactive is never called with None — preventing .encode(None) AttributeError."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import SieveMockBuilder


class TestSetactiveNoNoneArgument:
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
