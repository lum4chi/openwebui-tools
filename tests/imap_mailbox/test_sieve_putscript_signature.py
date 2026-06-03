"""Verify putscript is never called with extra kwargs — catching API mismatch bugs."""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import SieveMockBuilder


class TestPutscriptTwoArgsOnly:
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

    @pytest.mark.asyncio
    async def test_add_filter_to_script_putscript_two_args(self, sieve_tools):
        """add_filter_to_script calls putscript(name, content) with no extra kwargs."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing_script = 'require "fileinto";\n# __FILTER:{"name":"old","type":"move","folder":"X"}__\nif true { fileinto "X"; stop; }\n'
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: scripts ===\n{existing_script}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.add_filter_to_script(
                script_name="scripts", name="new_rule", filter_type="move", target_folder="New", from_addr="a@b.com"
            )
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "scripts"
        assert kwargs == {}, "putscript should not receive keyword arguments"

    @pytest.mark.asyncio
    async def test_remove_filter_from_script_putscript_two_args(self, sieve_tools):
        """remove_filter_from_script calls putscript(name, content) with no extra kwargs."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        script_content = (
            'require "fileinto";\n'
            '# __FILTER:{"name":"to_remove","type":"move","folder":"X"}__\n'
            'if true { fileinto "X"; stop; }\n'
            '# __FILTER:{"name":"keep","type":"move","folder":"Y"}__\n'
            'if true { fileinto "Y"; stop; }\n'
        )
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: scripts ===\n{script_content}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.remove_filter_from_script(script_name="scripts", name="to_remove")
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "scripts"
        assert kwargs == {}, "putscript should not receive keyword arguments"

    @pytest.mark.asyncio
    async def test_create_or_update_filter_putscript_two_args(self, sieve_tools):
        """create_or_update_filter convenience method calls putscript with exactly two positional args."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("new_filter", ["new_filter"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_or_update_filter(
                name="new_filter", filter_type="move", target_folder="Work", from_addr="boss@x.com"
            )
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "new_filter"
        assert kwargs == {}, "putscript should not receive keyword arguments"

    @pytest.mark.asyncio
    async def test_remove_all_filters_putscript_two_args(self, sieve_tools):
        """remove_all_filters_from_script calls putscript with exactly (name, content)."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = 'require "fileinto";\n# __FILTER:{"name":"f1"}__\nfileinto "X";\n'
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.remove_all_filters_from_script(script_name="scripts")
        args, kwargs = mock_client.putscript.call_args
        assert len(args) == 2
        assert args[0] == "scripts"
        assert kwargs == {}, "putscript should not receive keyword arguments"
