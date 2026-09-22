"""B5: record_feedback decisions schema — docstring contract (T1-1) + FeedbackEntry JSON-schema decision enum (T0-5)."""

from typing import get_args, get_type_hints

import pytest
from pydantic import ValidationError

import youtube_manager
from youtube_manager import DECISIONS, FeedbackEntry, Tools, parse_feedback_log

from .conftest import sample_feedback_log


class TestFeedbackSchema:
    """record_feedback docstring is the model-facing decisions schema."""

    # @unit
    # Scenario: T1-1 record feedback schema docstring
    #   Given the record_feedback method on Tools
    #   When its docstring is inspected
    #   Then "watched" appears in the docstring
    #   And "listened" appears in the docstring
    #   And "skipped" appears in the docstring
    def test_record_feedback_docstring_names_decisions(self):
        doc = Tools.record_feedback.__doc__ or ""
        assert "watched" in doc
        assert "listened" in doc
        assert "skipped" in doc


class TestFeedbackEntryDecisionEnum:
    """FeedbackEntry is the model-facing decisions schema: its JSON schema advertises the enum (T0-5)."""

    # @unit
    # Scenario: T0-5.1 JSON schema advertises the decision enum
    #   Given the FeedbackEntry Pydantic model
    #   When model_json_schema() is generated
    #   Then properties.decision.enum == ["watched", "listened", "skipped"]
    def test_json_schema_advertises_decision_enum(self):
        schema = FeedbackEntry.model_json_schema()
        assert schema["properties"]["decision"]["enum"] == ["watched", "listened", "skipped"]

    # @unit
    # Scenario: T0-5.2 valid decisions accepted
    #   Given each decision in ["watched", "listened", "skipped"]
    #   When a FeedbackEntry is constructed with it
    #   Then it is accepted
    @pytest.mark.parametrize("decision", ["watched", "listened", "skipped"])
    def test_valid_decisions_accepted(self, decision: str):
        entry = FeedbackEntry("2026-09-01", "vidX", decision, "title", "digest", "")
        assert entry.decision == decision

    # @unit
    # Scenario: T0-5.3 invalid decision rejected by the schema
    #   Given a FeedbackEntry constructed with decision="deleted"
    #   When the model validates it
    #   Then a ValidationError is raised
    def test_invalid_decision_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackEntry("2026-09-01", "vidX", "deleted", "title", "digest", "")

    # @unit
    # Scenario: T0-5.4 record_feedback friendly message preserved (regression)
    #   Given a record_feedback call with decision="deleted"
    #   When it is invoked
    #   Then it is rejected with a message naming the valid values (existing behavior unchanged)
    async def test_record_feedback_friendly_message_preserved(self, tools, fake_store):
        out = await tools.record_feedback("vidX", "deleted")
        assert out == "Error: decision must be one of: watched, listened, skipped"
        assert not fake_store.docs

    # @unit
    # Scenario: T0-5.5 backward compatible: existing state parses cleanly
    #   Given a sample feedback log containing only watched/listened/skipped rows
    #   When the state is parsed through the model
    #   Then it parses with no errors
    def test_existing_state_parses_cleanly(self):
        md = sample_feedback_log(
            [
                ("2026-09-01", "vidW", "watched", "t", "digest", ""),
                ("2026-09-02", "vidL", "listened", "t", "digest", ""),
                ("2026-09-03", "vidS", "skipped", "t", "digest", "too long"),
            ]
        )
        entries = parse_feedback_log(md)
        assert [e.decision for e in entries] == ["watched", "listened", "skipped"]

    # @unit
    # Scenario: T8-4 S3 the module docstring version is bumped to 1.5.2
    #   Given the module docstring
    #   When read
    #   Then it contains "1.5.2"
    #   And it does not contain "1.5.1"
    def test_version_bumped_to_1_5_2(self):
        doc = youtube_manager.__doc__ or ""
        assert "1.5.2" in doc
        assert "1.5.1" not in doc


class TestRecordFeedbackToolSchema:
    """The OWUI tool schema (signature-derived) advertises the decision enum (T8-4)."""

    # @unit
    # Scenario: T8-4 S1 the OWUI tool schema advertises the decision enum (values equal DECISIONS)
    #   Given the record_feedback signature
    #   When the OWUI tool schema is derived from its type hints (get_type_hints → create_model → model_json_schema)
    #   Then decision is advertised as type "string" with enum exactly ["watched", "listened", "skipped"]
    #   And the enum values are exactly the DECISIONS tuple values
    def test_record_feedback_tool_schema_advertises_decision_enum(self):
        hints = get_type_hints(Tools.record_feedback)
        assert get_args(hints["decision"]) == ("watched", "listened", "skipped")
        assert set(get_args(hints["decision"])) == set(DECISIONS)
