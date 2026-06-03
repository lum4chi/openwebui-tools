"""Tests for Sieve convenience methods: create_or_update_filter, add/remove_filter."""

from unittest.mock import MagicMock, patch

import pytest

from imap_mailbox import Tools


class TestCreateOrUpdateFilter:
    """Tests for the create_or_update_filter convenience method."""

    def _make_client(self, active="s", scripts=None, script_responses=None):
        from tests.imap_mailbox.conftest import SieveMockBuilder

        builder = SieveMockBuilder.make(active=active, scripts=scripts)
        if script_responses:
            for name, content in script_responses.items():
                if name in ("filter1", "s"):
                    builder.getscript.return_value = f"=== Sieve Script: placeholder ===\n{content}"
        return builder

    @pytest.mark.asyncio
    async def test_create_simple_move_filter(self, sieve_tools):
        """Create a filter with from_addr to move emails."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("auto_filter", ["auto_filter"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="auto_filter",
                filter_type="move",
                target_folder="Work",
                from_addr="boss@company.com",
            )
        assert "created" in result.lower() and "activated" in result.lower()
        called_args = mock_client.putscript.call_args_list[0]
        script_content = called_args[0][1]
        assert 'fileinto "Work"' in script_content
        assert 'header :contains "From" "boss@company.com"' in script_content

    @pytest.mark.asyncio
    async def test_create_discard_filter(self, sieve_tools):
        """Create a discard filter."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("discard_filters", ["discard_filters"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="discard_filters",
                filter_type="discard",
                subject="unwanted newsletter",
            )
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_stop_blacklist_filter(self, sieve_tools):
        """Create a stop/blacklist filter."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("blacklist", ["blacklist"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="blacklist",
                filter_type="stop",
                from_addr="spammer@evil.com",
            )
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_update_existing_filter(self, sieve_tools):
        """Update an existing filter script — preserves prior filters."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing = 'require "fileinto";\n'
        existing += '# __FILTER:{"name":"keep","type":"move","folder":"Inbox"}__\n'
        existing += 'if true {\n  fileinto "Inbox";\n  stop;\n}\n'
        mock_client.listscripts.return_value = ("filter_a", ["filter_a"])
        mock_client.getscript.return_value = f"=== Sieve Script: filter_a ===\n{existing}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="filter_a",
                filter_type="move",
                target_folder="Archive",
                subject="updated subject",
            )
        assert "updated" in result.lower()
        script = mock_client.putscript.call_args[0][1]
        # new filter replaces existing one with same name
        assert '"name":"filter_a"' in script
        # existing unrelated filters are preserved
        assert '"name":"keep"' in script
        assert 'fileinto "Archive"' in script

    @pytest.mark.asyncio
    async def test_update_existing_same_name_replaces_not_duplicates(self, sieve_tools):
        """Updating a filter with a name that already exists in the script replaces it, not duplicates."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing = 'require "fileinto";\n'
        existing += '# __FILTER:{"name":"dup","type":"move","folder":"Old"}__\n'
        existing += 'if true {\n  fileinto "Old";\n  stop;\n}\n'
        existing += '# __FILTER:{"name":"other","type":"discard"}__\n'
        existing += "if true {\n  discard;\n  stop;\n}\n"
        mock_client.listscripts.return_value = ("dup", ["dup", "other"])
        mock_client.getscript.return_value = f"=== Sieve Script: dup ===\n{existing}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_or_update_filter(
                name="dup",
                filter_type="discard",
                subject="new subject",
            )
        script = mock_client.putscript.call_args[0][1]
        assert script.count('"name":"dup"') == 1
        assert script.count('"name":"other"') == 1
        assert 'fileinto "Old"' not in script
        assert "discard" in script

    @pytest.mark.asyncio
    async def test_create_no_target_folder_for_move(self, sieve_tools):
        """Creating a move filter without target_folder returns error."""
        sieve_tools.valves.allow_create_sieve = True
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.create_or_update_filter(name="test", filter_type="move")
        assert "target_folder is required" in result

    @pytest.mark.asyncio
    async def test_create_invalid_hour_range_format(self, sieve_tools):
        """Invalid hour_range format (non-numeric) returns error."""
        sieve_tools.valves.allow_create_sieve = True
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.create_or_update_filter(
                name="test", filter_type="move", target_folder="X", hour_range="invalid"
            )
        assert "Invalid hour_range" in result

    @pytest.mark.asyncio
    async def test_create_invalid_hour_range_range(self, sieve_tools):
        """Invalid hour_range values (lo >= hi) returns error."""
        sieve_tools.valves.allow_create_sieve = True
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.create_or_update_filter(
                name="test", filter_type="move", target_folder="X", hour_range="17-9"
            )
        assert "Invalid hour_range" in result

    @pytest.mark.asyncio
    async def test_create_no_scripts_available(self, sieve_tools):
        """When ManageSieve returns None, proceed with create (putscript may still fail)."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = None
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="test", filter_type="move", target_folder="X", from_addr="a@b.com"
            )
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_disabled(self, sieve_tools):
        """Create when create permission is disabled."""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.create_or_update_filter(name="test", filter_type="move", target_folder="X")
        assert "disabled" in result.lower() and "allow_create_sieve" in result

    @pytest.mark.asyncio
    async def test_create_exception(self, sieve_tools):
        """Create when ManageSieve operation raises."""
        sieve_tools.valves.allow_create_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        mock_client.putscript.side_effect = Exception("Connection lost")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="test", filter_type="move", target_folder="X", from_addr="a@b.com"
            )
        assert "Error creating filter" in result

    @pytest.mark.asyncio
    async def test_create_no_credentials(self):
        """Create returns error when credentials are missing."""
        t = Tools()
        t.valves.username = ""
        t.valves.password = ""
        t.valves.allow_create_sieve = True
        result = await t.create_or_update_filter(name="test", filter_type="move", target_folder="X")
        assert "credentials" in result.lower()

    @pytest.mark.asyncio
    async def test_create_with_complex_conditions(self, sieve_tools):
        """Filter with multiple conditions."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("weekend_move", ["weekend_move"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="weekend_move",
                filter_type="move",
                target_folder="Weekend",
                from_addr="work@x.com",
                day="Saturday",
                hour_range=(8, 17),
                has_attachment=True,
            )
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_with_hour_range_string(self, sieve_tools):
        """Filter with hour_range as 'HH-HH' string exercises the parsing path."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("hours_filter", ["hours_filter"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.create_or_update_filter(
                name="hours_filter",
                filter_type="move",
                target_folder="Office",
                hour_range="9-17",
            )
        assert "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_with_recipient_condition(self, sieve_tools):
        """Filter matching recipient instead of sender."""
        sieve_tools.valves.allow_create_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [(None, []), ("to_filter", ["to_filter"])]
        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_or_update_filter(
                name="to_filter",
                filter_type="move",
                target_folder="ToMe",
                to_addr="me@company.com",
            )
        script = mock_client.putscript.call_args[0][1]
        assert 'header :contains "To" "me@company.com"' in script


class TestAddFilterToScript:
    """Tests for the add_filter_to_script convenience method."""

    @pytest.mark.asyncio
    async def test_add_filter_success(self, sieve_tools):
        """Add a new filter to an existing script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing_script = 'require "fileinto";\n'
        existing_script += '# __FILTER:{"name":"old_rule","type":"move","folder":"Old"}__\n'
        existing_script += 'if true {\n  fileinto "Old";\n  stop;\n}\n'
        mock_client.listscripts.return_value = ("my_scripts", ["my_scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: my_scripts ===\n{existing_script}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="my_scripts",
                name="new_rule",
                filter_type="move",
                target_folder="New",
                from_addr="sender@x.com",
            )
        assert "added" in result.lower()
        called_script = mock_client.putscript.call_args[0][1]
        assert '"name":"old_rule"' in called_script
        assert '"name":"new_rule"' in called_script

    @pytest.mark.asyncio
    async def test_add_filter_with_to_and_subject(self, sieve_tools):
        """Add filter with to_addr and subject conditions."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing_script = 'require "fileinto";\n'
        mock_client.listscripts.return_value = ("my_scripts", ["my_scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: my_scripts ===\n{existing_script}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="my_scripts",
                name="route_filter",
                filter_type="move",
                target_folder="Routing",
                to_addr="team@x.com",
                subject="urgent",
            )
        assert "added" in result.lower()
        called_script = mock_client.putscript.call_args[0][1]
        assert 'header :contains "To" "team@x.com"' in called_script
        assert 'header :contains "Subject" "urgent"' in called_script

    @pytest.mark.asyncio
    async def test_add_filter_invalid_hour_range(self, sieve_tools):
        """Add filter with invalid hour_range returns error."""
        sieve_tools.valves.allow_update_sieve = True
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.add_filter_to_script(
                script_name="x", name="f1", filter_type="move", target_folder="A", hour_range="25-9"
            )
        assert "Invalid hour_range" in result

    @pytest.mark.asyncio
    async def test_add_filter_invalid_hour_range_value_error(self, sieve_tools):
        """Add filter with non-parseable hour_range triggers ValueError exception."""
        sieve_tools.valves.allow_update_sieve = True
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.add_filter_to_script(
                script_name="x", name="f1", filter_type="move", target_folder="A", hour_range="abc-def"
            )
        assert "Invalid hour_range" in result
        assert "abc-def" in result

    @pytest.mark.asyncio
    async def test_add_filter_with_subject_day_and_attachment(self, sieve_tools):
        """Add filter with subject, day_of_week and has_attachment conditions."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        existing_script = 'require "fileinto";\n'
        mock_client.listscripts.return_value = ("my_scripts", ["my_scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: my_scripts ===\n{existing_script}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="my_scripts",
                name="complex_rule",
                filter_type="move",
                target_folder="Filtered",
                subject="urgent",
                day="Monday",
                hour_range="9-17",
                has_attachment=True,
            )
        assert "added" in result.lower()
        called_script = mock_client.putscript.call_args[0][1]
        assert 'header :contains "Subject" "urgent"' in called_script
        assert 'date :is "day" "Monday"' in called_script
        assert 'date :value "ge" "hour" "09"' in called_script
        assert 'attachment :contains "Content-Type" "multipart/"' in called_script

    @pytest.mark.asyncio
    async def test_add_to_script_not_found(self, sieve_tools):
        """Adding to a script that doesn't exist."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["other_script"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="ghost",
                name="f1",
                filter_type="move",
                target_folder="A",
            )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_add_filter_disabled(self, sieve_tools):
        """Add when update permission is disabled."""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.add_filter_to_script(
                script_name="x", name="f1", filter_type="move", target_folder="A"
            )
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_add_filter_no_scripts_available(self, sieve_tools):
        """Add when no scripts available."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = None
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="x", name="f1", filter_type="move", target_folder="A"
            )
        assert "no sieve scripts" in result.lower()

    @pytest.mark.asyncio
    async def test_add_filter_no_scripts_list(self, sieve_tools):
        """Add when scripts list is empty."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="x", name="f1", filter_type="move", target_folder="A"
            )
        assert "No Sieve scripts" in result or "manage their own API" in result.lower()

    @pytest.mark.asyncio
    async def test_add_filter_connect_fail(self, sieve_tools):
        """Add when ManageSieve connection fails (connect returns False)."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="scripts", name="f1", filter_type="move", target_folder="A"
            )
        assert "Connection or authentication failed" in result

    @pytest.mark.asyncio
    async def test_add_filter_putscript_error(self, sieve_tools):
        """Add when putscript raises an exception."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = 'require "fileinto";\n'
        mock_client.putscript.side_effect = Exception("Upload failed")
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.add_filter_to_script(
                script_name="scripts", name="f1", filter_type="move", target_folder="A"
            )
        assert "Error adding filter rule" in result


class TestRemoveFilterFromScript:
    """Tests for the remove_filter_from_script method."""

    @pytest.mark.asyncio
    async def test_remove_filter_success(self, sieve_tools):
        """Successfully remove a filter by name."""
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
            result = await sieve_tools.remove_filter_from_script(script_name="scripts", name="to_remove")
        assert "removed" in result.lower()
        updated = mock_client.putscript.call_args[0][1]
        assert "to_remove" not in updated
        assert "keep" in updated

    @pytest.mark.asyncio
    async def test_remove_nonexistent_filter(self, sieve_tools):
        """Removing a filter name that doesn't exist."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = (
            'require "fileinto";\n# __FILTER:{"name":"only","type":"move"}__\nif true { stop; }\n'
        )
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_filter_from_script(script_name="scripts", name="ghost")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_script_not_found(self, sieve_tools):
        """Removing from a script that doesn't exist."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["other"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_filter_from_script(script_name="ghost", name="f1")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_filter_no_scripts(self, sieve_tools):
        """Remove when no scripts are available."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_filter_from_script(script_name="ghost", name="f1")
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_remove_filter_disabled(self, sieve_tools):
        """Remove when update permission is disabled."""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.remove_filter_from_script(script_name="x", name="f1")
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_remove_filter_exception(self, sieve_tools):
        """Remove when ManageSieve raises an exception."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.getscript.side_effect = Exception("Server error")
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_filter_from_script(script_name="scripts", name="f1")
        assert "Error removing filter rule" in result

    @pytest.mark.asyncio
    async def test_remove_filter_connect_fail(self, sieve_tools):
        """Remove when ManageSieve connection fails."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_filter_from_script(script_name="scripts", name="f1")
        assert "Connection or authentication failed" in result


class TestRemoveAllFiltersFromScript:
    """Tests for the remove_all_filters_from_script method."""

    @pytest.mark.asyncio
    async def test_remove_all_filters(self, sieve_tools):
        """Remove all filters, keeping headers."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        script_content = (
            'require "fileinto";\n'
            'require "complaint";\n'
            '# __FILTER:{"name":"f1","type":"move"}__\n'
            'fileinto "A";\n'
            '# __FILTER:{"name":"f2","type":"discard"}__\n'
            "discard;\n"
        )
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        mock_client.getscript.return_value = f"=== Sieve Script: scripts ===\n{script_content}"
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_all_filters_from_script(script_name="scripts")
        assert "removed" in result.lower()
        updated = mock_client.putscript.call_args[0][1]
        assert "fileinto" in updated or "require" in updated
        assert "f1" not in updated
        assert "f2" not in updated

    @pytest.mark.asyncio
    async def test_remove_all_script_not_found(self, sieve_tools):
        """Remove all from a non-existent script."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, ["ghost_script"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_all_filters_from_script(script_name="ghost")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_all_no_scripts(self, sieve_tools):
        """Remove all when no scripts are available."""
        sieve_tools.valves.allow_update_sieve = True
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.return_value = (None, [])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_all_filters_from_script(script_name="ghost")
        assert "No Sieve scripts" in result

    @pytest.mark.asyncio
    async def test_remove_all_disabled(self, sieve_tools):
        """Remove all when update permission is disabled."""
        with patch("imap_mailbox.Client", MagicMock()):
            result = await sieve_tools.remove_all_filters_from_script(script_name="x")
        assert "disabled" in result.lower() and "allow_update_sieve" in result

    @pytest.mark.asyncio
    async def test_remove_all_exception(self, sieve_tools):
        """Remove all when ManageSieve raises an exception."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.getscript.side_effect = Exception("Server error")
        mock_client.listscripts.return_value = ("scripts", ["scripts"])
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_all_filters_from_script(script_name="scripts")
        assert "Error clearing filters" in result

    @pytest.mark.asyncio
    async def test_remove_all_connect_fail(self, sieve_tools):
        """Remove all when ManageSieve connection fails."""
        sieve_tools.valves.allow_update_sieve = True
        sieve_tools.valves.imap_server = "sieve.example.com"
        sieve_tools.valves.username = "testuser"
        sieve_tools.valves.password = "testpass"
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        with patch("imap_mailbox.Client", return_value=mock_client):
            result = await sieve_tools.remove_all_filters_from_script(script_name="scripts")
        assert "Connection or authentication failed" in result


class TestFullWorkflow:
    """Integration-style tests for end-to-end filter workflows."""

    @pytest.mark.asyncio
    async def test_create_then_add_then_remove(self, sieve_tools):
        """Full workflow: create filter, add another, then remove one."""
        sieve_tools.valves.allow_create_sieve = sieve_tools.valves.allow_update_sieve = True

        # Use a mutable dict to track the current script content
        script_state = {"content": 'require "fileinto";\n'}

        def getscript_side_effect(name):
            if name == "filters":
                return f"=== Sieve Script: filters ===\n{script_state['content']}"
            return ""

        def putscript_side_effect(name, content, activate=False):
            if name == "filters":
                script_state["content"] = content

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.listscripts.side_effect = [
            (None, []),
            ("filters", ["filters"]),
            ("filters", ["filters"]),
            ("filters", ["filters"]),
        ]
        mock_client.getscript.side_effect = getscript_side_effect
        mock_client.putscript.side_effect = putscript_side_effect

        with patch("imap_mailbox.Client", return_value=mock_client):
            await sieve_tools.create_or_update_filter(
                name="filters",
                filter_type="move",
                target_folder="A",
                from_addr="a@x.com",
            )
            await sieve_tools.add_filter_to_script(
                script_name="filters",
                name="rule2",
                filter_type="discard",
                subject="x",
            )
            result = await sieve_tools.remove_filter_from_script(script_name="filters", name="rule2")
        assert "removed" in result.lower()
        # Verify that only rule1 (a@x.com) remains
        updated_content = mock_client.putscript.call_args_list[-1][0][1]
        assert "a@x.com" in updated_content
        assert "rule2" not in updated_content
