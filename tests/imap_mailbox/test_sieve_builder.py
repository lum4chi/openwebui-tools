"""Tests for SieveScriptBuilder helper — DSL generation and script manipulation."""

import pytest

from imap_mailbox import (
    _UNTAGGED_FILTER_BLOCK_RE,
    SieveScriptBuilder,
    _build_header_from_script,
    _extract_preamble,
    _extract_script_content,
    _parse_filters_from_script,
)


class TestFilterRuleGeneration:
    """Test generate_filter_rule for various filter types and conditions."""

    def test_move_rule_basic(self):
        """Basic move filter from sender to folder."""
        rule = SieveScriptBuilder.generate_filter_rule("move_work", "move", "Work", from_addr="boss@company.com")
        assert "# __FILTER:" in rule
        assert '"name":"move_work"' in rule
        assert '"type":"move"' in rule
        assert 'header :contains "From" "boss@company.com"' in rule
        assert 'fileinto "Work"' in rule

    def test_move_rule_with_subject(self):
        """Move filter with from + subject conditions."""
        rule = SieveScriptBuilder.generate_filter_rule(
            "move_invoices", "move", "Invoices", subject="invoice #123", from_addr="invoices@shop.com"
        )
        assert 'header :contains "From" "invoices@shop.com"' in rule
        assert 'header :contains "Subject" "invoice #123"' in rule
        assert '"match":"invoices@shop.com"' in rule

    def test_discard_rule(self):
        """Discard (silent delete) filter."""
        rule = SieveScriptBuilder.generate_filter_rule("block_spam", "discard", subject="lottery winner")
        assert "discard;" in rule
        assert '"type":"discard"' in rule

    def test_stop_rule(self):
        """Stop (blacklist to Junk) filter."""
        rule = SieveScriptBuilder.generate_filter_rule("mark_spam", "stop", from_addr="spam@evil.com")
        assert 'fileinto "Junk"' in rule

    def test_move_no_target_raises(self):
        """Move filter without target_folder raises ValueError."""
        with pytest.raises(ValueError, match="target_folder is required"):
            SieveScriptBuilder.generate_filter_rule("orphan_filter", "move")

    def test_filter_with_day_condition(self):
        """Filter matching a specific day of week."""
        rule = SieveScriptBuilder.generate_filter_rule("weekend_only", "move", "Work", day="Saturday")
        assert 'date :is "day" "Saturday"' in rule

    def test_filter_with_hour_range(self):
        """Filter matching a specific hour range."""
        rule = SieveScriptBuilder.generate_filter_rule("office_hours", "stop", hour_range=(9, 17))
        assert 'date :value "ge" "hour" "09"' in rule
        assert 'date :value "lt" "hour" "17"' in rule

    def test_filter_with_has_attachment(self):
        """Filter matching emails with attachments."""
        rule = SieveScriptBuilder.generate_filter_rule(
            "has_attach", "move", "Docs", subject="report", has_attachment=True
        )
        assert 'attachment :contains "Content-Type" "multipart/"' in rule

    def test_filter_with_false_has_attachment(self):
        """has_attachment=False is ignored — no conditions for it."""
        rule = SieveScriptBuilder.generate_filter_rule("no_att", "move", "Docs", subject="report", has_attachment=False)
        assert "attachment" not in rule
        assert "Subject" in rule

    def test_filter_no_conditions(self):
        """Filter with no matching conditions matches all."""
        rule = SieveScriptBuilder.generate_filter_rule("catch_all", "move", "Archive")
        assert "if true {" in rule

    def test_filter_with_to_recipient(self):
        """Filter matching recipient address."""
        rule = SieveScriptBuilder.generate_filter_rule("sent_to_team", "move", "Team", to_addr="team@example.com")
        assert 'header :contains "To" "team@example.com"' in rule
        assert '"match":"team@example.com"' in rule

    def test_no_anyof_or_allof_combinators(self):
        """Generated rules use nested if for universal server compatibility."""
        rule = SieveScriptBuilder.generate_filter_rule(
            "multi",
            "move",
            "Test",
            subject="x",
            from_addr="a@x.com",
            day="Monday",
            hour_range=(9, 17),
        )
        assert "anyof" not in rule
        assert "allof" not in rule
        assert "if header" in rule
        assert "if date" in rule

    def test_filter_with_two_conditions_has_two_blocks(self):
        """Multiple conditions produce multiple independent if blocks."""
        rule = SieveScriptBuilder.generate_filter_rule(
            "two_cond",
            "move",
            "Folder",
            from_addr="a@x.com",
            subject="hello",
        )
        assert 'header :contains "From"' in rule
        assert 'header :contains "Subject"' in rule
        assert rule.count('fileinto "Folder"') == 2
        assert rule.count("stop;") == 2


class TestBuildCompleteScript:
    """Test build_complete_script — combining rules into full script."""

    def test_single_filter(self):
        """Script with one filter."""
        rule = SieveScriptBuilder.generate_filter_rule("f1", "move", "Work", from_addr="boss@x.com")
        script = SieveScriptBuilder.build_complete_script([rule])
        assert 'require "fileinto"' in script
        assert "# __FILTER:" in script
        assert 'fileinto "Work"' in script

    def test_multiple_filters(self):
        """Script with several filters."""
        r1 = SieveScriptBuilder.generate_filter_rule("rule1", "move", "FolderA", from_addr="a@x.com")
        r2 = SieveScriptBuilder.generate_filter_rule("rule2", "move", "FolderB", from_addr="b@x.com")
        script = SieveScriptBuilder.build_complete_script([r1, r2])
        assert 'fileinto "FolderA"' in script
        assert 'fileinto "FolderB"' in script


class TestMergeFilterIntoScript:
    """Test merge_filter_into_script — adding rules to existing scripts."""

    def test_add_to_empty_script(self):
        """Adding a filter to a bare require statement."""
        existing = 'require "fileinto";\n'
        new_filter = SieveScriptBuilder.generate_filter_rule("new_rule", "move", "New", from_addr="new@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert "new_rule" in result
        assert 'fileinto "New"' in result

    def test_add_to_script_with_existing_filters(self):
        """Appending a filter alongside existing ones."""
        f1 = SieveScriptBuilder.generate_filter_rule("existing", "move", "Existing", from_addr="old@x.com")
        existing = SieveScriptBuilder.build_complete_script([f1])
        new_filter = SieveScriptBuilder.generate_filter_rule("new_rule", "move", "New", subject="urgent")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert '"name":"existing"' in result
        assert '"name":"new_rule"' in result

    def test_add_multiple_filters(self):
        """Adding several filters one by one."""
        existing = 'require "fileinto";\n'
        r1 = SieveScriptBuilder.generate_filter_rule("rule_a", "move", "A", from_addr="a@x.com")
        r2 = SieveScriptBuilder.generate_filter_rule("rule_b", "discard", subject="spam")
        result = SieveScriptBuilder.merge_filter_into_script(existing, r1)
        result = SieveScriptBuilder.merge_filter_into_script(result, r2)
        assert '"name":"rule_a"' in result
        assert '"name":"rule_b"' in result


class TestRemoveFilterFromScript:
    """Test remove_filter_from_script — removing individual rules."""

    def test_remove_single_filter(self):
        """Remove the only filter from a script."""
        f1 = SieveScriptBuilder.generate_filter_rule("to_remove", "move", "Work", from_addr="boss@x.com")
        script = SieveScriptBuilder.build_complete_script([f1])
        result = SieveScriptBuilder.remove_filter_from_script(script, "to_remove")
        assert "to_remove" not in result
        # Should still have require
        assert 'require "fileinto"' in result

    def test_remove_one_of_many(self):
        """Remove a filter keeping others intact."""
        f1 = SieveScriptBuilder.generate_filter_rule("keep", "move", "Keep", from_addr="keep@x.com")
        f2 = SieveScriptBuilder.generate_filter_rule("remove", "move", "Remove", from_addr="remove@x.com")
        f3 = SieveScriptBuilder.generate_filter_rule("keep2", "discard", subject="keep me")
        script = SieveScriptBuilder.build_complete_script([f1, f2, f3])
        result = SieveScriptBuilder.remove_filter_from_script(script, "remove")
        assert '"name":"keep"' in result
        assert '"name":"remove"' not in result
        assert '"name":"keep2"' in result

    def test_remove_nonexistent_name(self):
        """Removing a name that doesn't exist leaves script unchanged."""
        f1 = SieveScriptBuilder.generate_filter_rule("only_filter", "move", "A", from_addr="a@x.com")
        script = SieveScriptBuilder.build_complete_script([f1])
        result = SieveScriptBuilder.remove_filter_from_script(script, "ghost")
        assert result == script


class TestBuildHeaderFromScript:
    """Test _build_header_from_script helper."""

    def test_extract_multiple_require_statements(self):
        """Multiple require statements extracted in order."""
        script = 'require "fileinto";\nrequire "complaint";\nrequire "fileinto";\n# __FILTER:\nif true { stop; }\n'
        header = _build_header_from_script(script)
        assert 'require "fileinto"' in header
        assert 'require "complaint"' in header
        assert "if true" not in header

    def test_build_header_from_script_no_headers(self):
        """No require statements — fallback to fileinto."""
        script = "if true {\n  stop;\n}\n"
        header = _build_header_from_script(script)
        assert header == 'require "fileinto";'

    def test_build_header_with_non_require_lines(self):
        """Lines that are not require are ignored."""
        script = 'fileinto "Inbox";\nrequire "fileinto";\n# some comment\nstop;\n'
        header = _build_header_from_script(script)
        assert 'require "fileinto"' in header
        assert 'fileinto "Inbox"' not in header


class TestExtractScriptContent:
    """Test _extract_script_content helper."""

    def test_extract_from_standard_output(self):
        """Extract DSL from standard getscript response format."""
        output = (
            '=== Sieve Script: my_filter ===\nrequire "fileinto";\nif header :contains "From" "x" {\n  fileinto "Y";\n}'
        )
        content = _extract_script_content(output)
        assert 'require "fileinto"' in content

    def test_extract_from_raw_dsl(self):
        """Pass-through for raw DSL (no wrapper line)."""
        output = 'require "fileinto";\nif true {\n  stop;\n}'
        content = _extract_script_content(output)
        assert content == output


class TestParseFiltersFromScript:
    """Test _parse_filters_from_script helper."""

    def test_parse_single_filter(self):
        """Parse script with one filter block."""
        f1 = SieveScriptBuilder.generate_filter_rule("only_filter", "move", "Inbox", subject="hello")
        script = SieveScriptBuilder.build_complete_script([f1])
        filters = _parse_filters_from_script(script)
        assert len(filters) == 1
        assert '"name":"only_filter"' in filters[0]

    def test_parse_multiple_filters(self):
        """Parse script with multiple filter blocks."""
        f1 = SieveScriptBuilder.generate_filter_rule("f1", "move", "A", from_addr="a@x.com")
        f2 = SieveScriptBuilder.generate_filter_rule("f2", "discard", subject="x")
        f3 = SieveScriptBuilder.generate_filter_rule("f3", "stop", to_addr="b@x.com")
        script = SieveScriptBuilder.build_complete_script([f1, f2, f3])
        filters = _parse_filters_from_script(script)
        assert len(filters) == 3

    def test_parse_with_exclude_name(self):
        """Parse filters excluding a specific name."""
        f1 = SieveScriptBuilder.generate_filter_rule("keep", "move", "A", subject="keep")
        f2 = SieveScriptBuilder.generate_filter_rule("drop", "discard", subject="drop")
        script = SieveScriptBuilder.build_complete_script([f1, f2])
        filters = _parse_filters_from_script(script, exclude_name="drop")
        assert len(filters) == 1
        assert "keep" in filters[0]
        assert "drop" not in filters[0]

    def test_parse_with_invalid_json_tag_keeps_block(self):
        """Scripts with malformed tag JSON produce the block — exclusion logic changed."""
        script = 'require "fileinto";\n# __FILTER:{\'name\': broken}__\nif true { fileinto "X"; }\n'
        filters = _parse_filters_from_script(script)
        # Invalid JSON → current_name=None, but None is not excluded anymore
        # (it means "no specific name to exclude" not "skip all unnamed")
        assert len(filters) == 1
        assert "if true" in filters[0]

    def test_parse_empty_script(self):
        """Script with no filter blocks returns empty list."""
        filters = _parse_filters_from_script('require "fileinto";\n')
        assert filters == []

    def test_parse_last_block_with_exclude(self):
        """Excluded filter is properly skipped when it is the last block."""
        f1 = SieveScriptBuilder.generate_filter_rule("keep", "move", "A", subject="keep")
        f2 = SieveScriptBuilder.generate_filter_rule("drop", "discard", subject="drop")
        script = SieveScriptBuilder.build_complete_script([f1, f2])
        filters = _parse_filters_from_script(script, exclude_name="drop")
        assert len(filters) == 1
        assert "keep" in filters[0]

    def test_parse_untagged_header_filter(self):
        """Tag mode only — provider-created header filters are NOT parsed."""
        script = 'require "fileinto";\nif header :from "boss@x.com" {\n  fileinto "Boss";\n  stop;\n}\n'
        filters = _parse_filters_from_script(script)
        assert filters == []

    def test_parse_untagged_header_filter_with_include(self):
        """Untagged mode — provider filters are extracted."""
        script = 'require "fileinto";\nif header :from "boss@x.com" {\n  fileinto "Boss";\n  stop;\n}\n'
        filters = _parse_filters_from_script(script, include_untagged=True)
        assert len(filters) == 1
        assert "header :from" in filters[0]

    def test_parse_tag_and_untagged_together(self):
        """Tag-based filters and untagged filters both extracted."""
        tagged = SieveScriptBuilder.generate_filter_rule("tagged", "move", "T", subject="x")
        untagged_script = (
            'require "fileinto";\n'
            '# __FILTER:{"name":"tagged"}__\n'
            f"{tagged}\n"
            'if header :from "boss@x.com" {\n'
            '  fileinto "Boss";\n'
            "  stop;\n"
            "}\n"
        )
        filters = _parse_filters_from_script(untagged_script, include_untagged=True)
        assert len(filters) == 2

    def test_parse_untagged_multi_conditions(self):
        """Untagged filter with multi-line if condition (nested braces)."""
        script = (
            'require "fileinto";\n'
            'if address :is "To" "team@x.com" {\n'
            '  if date :is "day" "Monday" {\n'
            '    fileinto "WorkMon";\n'
            "    stop;\n"
            "  }\n"
            "}\n"
        )
        filters = _parse_filters_from_script(script, include_untagged=True)
        assert len(filters) == 1
        assert "address :is" in filters[0]
        assert 'fileinto "WorkMon"' in filters[0]

    def test_parse_untagged_skips_if_true(self):
        """Untagged mode does NOT match bare 'if true' lines without a tag."""
        script = 'require "fileinto";\nif true {\n  fileinto "Archive";\n  stop;\n}\n'
        filters = _parse_filters_from_script(script, include_untagged=True)
        assert filters == []

    def test_parse_untagged_multiple_filters(self):
        """Multiple untagged filters all extracted."""
        script = (
            'require "fileinto";\n'
            'if header :from "a@x.com" {\n'
            '  fileinto "A";\n'
            "  stop;\n"
            "}\n"
            'if header :from "b@x.com" {\n'
            '  fileinto "B";\n'
            "  stop;\n"
            "}\n"
        )
        filters = _parse_filters_from_script(script, include_untagged=True)
        assert len(filters) == 2
        assert "a@x.com" in filters[0]
        assert "b@x.com" in filters[1]

    def test_parse_empty_script_with_include_untagged(self):
        """Empty script returns empty list even with include_untagged."""
        filters = _parse_filters_from_script("", include_untagged=True)
        assert filters == []


class TestExtractPreamble:
    """Test _extract_preamble helper."""

    def test_preamble_with_requires(self):
        """Preamble extracts all require statements before filters."""
        script = (
            'require "fileinto";\n'
            'require "variables";\n'
            '# __FILTER:{"name":"f1"}__\n'
            'if header :from "a@x.com" {\n'
            '  fileinto "A";\n'
            "  stop;\n"
            "}\n"
        )
        preamble = _extract_preamble(script)
        assert 'require "fileinto"' in preamble
        assert 'require "variables"' in preamble

    def test_preamble_stops_at_unfiltered_if(self):
        """Preamble stops at untagged if-block (no filters in preamble)."""
        script = 'require "fileinto";\nif header :from "a@x.com" {\n  fileinto "A";\n  stop;\n}\n'
        preamble = _extract_preamble(script)
        assert 'require "fileinto"' in preamble
        assert "if header" not in preamble

    def test_preamble_empty_no_filters(self):
        """Script with only requires — preamble returns them all."""
        script = 'require "fileinto";\nrequire "vacation";\n'
        preamble = _extract_preamble(script)
        assert 'require "fileinto"' in preamble
        assert 'require "vacation"' in preamble

    def test_preamble_empty_script(self):
        """Empty script returns empty string."""
        assert _extract_preamble("") == ""


class TestMergeUntaggedFilters:
    """Test merge_filter_into_script — preserving untagged and header content."""

    def test_merge_preserves_untagged_filter(self):
        """Adding a filter to a script created by a provider preserves existing untagged filters."""
        existing = 'require "fileinto";\nif header :from "boss@x.com" {\n  fileinto "Boss";\n  stop;\n}\n'
        new_filter = SieveScriptBuilder.generate_filter_rule("new_rule", "move", "New", from_addr="new@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        # Existing untagged filter preserved
        assert "boss@x.com" in result
        assert 'fileinto "Boss"' in result
        # New filter added
        assert "new_rule" in result
        assert 'fileinto "New"' in result

    def test_merge_preserves_multiple_untagged_filters(self):
        """Adding preserves ALL untagged filters, not just the first."""
        existing = (
            'require "fileinto";\n'
            'if header :from "a@x.com" {\n'
            '  fileinto "A";\n'
            "  stop;\n"
            "}\n"
            'if header :from "b@x.com" {\n'
            '  fileinto "B";\n'
            "  stop;\n"
            "}\n"
        )
        new_filter = SieveScriptBuilder.generate_filter_rule("c_rule", "move", "C", to_addr="c@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert "a@x.com" in result
        assert "b@x.com" in result
        assert "c@x.com" in result

    def test_merge_preserves_header_with_extra_requires(self):
        """Custom require statements are preserved during merge."""
        existing = 'require "fileinto";\nrequire "variables";\nrequire "mime";\n'
        new_filter = SieveScriptBuilder.generate_filter_rule("f1", "move", "Inbox", from_addr="x@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert 'require "variables"' in result
        assert 'require "mime"' in result
        assert '"name":"f1"' in result

    def test_merge_tagged_and_untagged_together(self):
        """Scripts with both tagged and untagged filters preserve everything."""
        tagged = SieveScriptBuilder.generate_filter_rule("tagged_filter", "move", "Tagged", subject="x")
        existing = f'require "fileinto";\n{tagged}\nif header :from "boss@x.com" {{\n  fileinto "Boss";\n  stop;\n}}\n'
        new_filter = SieveScriptBuilder.generate_filter_rule("new_rule", "move", "New", from_addr="new@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        # Tagged filter preserved
        assert '"name":"tagged_filter"' in result
        # Untagged filter preserved
        assert "boss@x.com" in result
        assert 'fileinto "Boss"' in result
        # New filter added
        assert '"name":"new_rule"' in result

    def test_merge_preserves_tagged_with_include_untagged(self):
        """Adding filter alongside existing tagged filters still works."""
        f1 = SieveScriptBuilder.generate_filter_rule("keep", "move", "Keep", from_addr="old@x.com")
        existing = SieveScriptBuilder.build_complete_script([f1])
        new_filter = SieveScriptBuilder.generate_filter_rule("new_rule", "move", "New", subject="urgent")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert '"name":"keep"' in result
        assert '"name":"new_rule"' in result

    def test_merge_script_only_requires(self):
        """Merging into a script that only has require statements works."""
        existing = 'require "fileinto";\n'
        new_filter = SieveScriptBuilder.generate_filter_rule("f1", "move", "Work", from_addr="boss@x.com")
        result = SieveScriptBuilder.merge_filter_into_script(existing, new_filter)
        assert '"name":"f1"' in result
        assert 'if header :contains "From" "boss@x.com"' in result

    def test_merge_empty_script(self):
        """Merging into empty content produces valid script with new filter."""
        new_filter = SieveScriptBuilder.generate_filter_rule("f1", "move", "Work", from_addr="boss@x.com")
        result = SieveScriptBuilder.merge_filter_into_script("", new_filter)
        assert '"name":"f1"' in result


class TestRemoveUntaggedFilters:
    """Test remove_filter_from_script behavior with mixed tag/untagged."""

    def test_remove_tagged_from_mixed_script(self):
        """Removing a named tag does not affect untagged filters."""
        tagged = SieveScriptBuilder.generate_filter_rule("remove_me", "move", "Drop", subject="x")
        existing = f'require "fileinto";\n{tagged}\nif header :from "boss@x.com" {{\n  fileinto "Boss";\n  stop;\n}}\n'
        result = SieveScriptBuilder.remove_filter_from_script(existing, "remove_me")
        assert "remove_me" not in result
        assert "boss@x.com" in result
        assert 'fileinto "Boss"' in result

    def test_remove_untagged_name_not_found(self):
        """Removing an untagged filter by name returns unchanged script."""
        existing = 'require "fileinto";\nif header :from "a@x.com" {\n  fileinto "A";\n  stop;\n}\n'
        result = SieveScriptBuilder.remove_filter_from_script(existing, "a_rule")
        assert result == existing

    def test_remove_nonexistent_tag_from_tagged_only(self):
        """Removing a nonexistent tag from a tagged-only script returns unchanged."""
        f1 = SieveScriptBuilder.generate_filter_rule("f1", "move", "A", from_addr="a@x.com")
        script = SieveScriptBuilder.build_complete_script([f1])
        result = SieveScriptBuilder.remove_filter_from_script(script, "ghost")
        assert result == script


class TestReplaceUntaggedFilters:
    """Test replace_filter_in_script with mixed content."""

    def test_replace_tagged_preserves_untagged(self):
        """Replacing a tagged filter keeps untagged ones intact."""
        tagged = SieveScriptBuilder.generate_filter_rule("replace_me", "move", "Old", subject="x")
        existing = f'require "fileinto";\n{tagged}\nif header :from "boss@x.com" {{\n  fileinto "Boss";\n  stop;\n}}\n'
        new_tag = SieveScriptBuilder.generate_filter_rule("replace_me", "move", "New", subject="y")
        result = SieveScriptBuilder.replace_filter_in_script(existing, new_tag, "replace_me")
        assert '"name":"replace_me"' in result
        assert '"type":"move"' in result
        assert 'fileinto "New"' in result
        assert "boss@x.com" in result
        assert 'fileinto "Boss"' in result


class TestBuildCompleteScriptPreamble:
    """Test build_complete_script with custom preamble."""

    def test_custom_preamble(self):
        """build_complete_script accepts custom preamble with multiple requires."""
        rules = ["rule1"]
        preamble = 'require "fileinto";\nrequire "variables";\n'
        result = SieveScriptBuilder.build_complete_script(rules, preamble=preamble)
        assert 'require "fileinto"' in result
        assert 'require "variables"' in result
        assert "rule1" in result

    def test_default_preamble(self):
        """Default preamble is still just require fileinto."""
        rules = ["rule1"]
        result = SieveScriptBuilder.build_complete_script(rules)
        assert 'require "fileinto"' in result


class TestFilterBlockRegex:
    """Test the _UNTAGGED_FILTER_BLOCK_RE pattern behavior."""

    def test_bare_if_true_not_matched(self):
        """'if true' is not matched by the untagged filter regex."""

        assert not _UNTAGGED_FILTER_BLOCK_RE.match("  if true {")

    def test_header_condition_matched(self):
        """'if header' is matched."""

        assert _UNTAGGED_FILTER_BLOCK_RE.match('  if header :contains "From" "a"')

    def test_date_condition_matched(self):
        """'if date' is matched."""

        assert _UNTAGGED_FILTER_BLOCK_RE.match('  if date :is "day" "Monday"')

    def test_address_condition_matched(self):
        """'if address' is matched."""

        assert _UNTAGGED_FILTER_BLOCK_RE.match('  if address :is "To" "a@x.com"')

    def test_other_if_conditions_matched(self):
        """Other sieve conditions are matched."""

        assert _UNTAGGED_FILTER_BLOCK_RE.match("  if size :over 1M")
        assert _UNTAGGED_FILTER_BLOCK_RE.match('  if exists "X-Custom-Header"')
