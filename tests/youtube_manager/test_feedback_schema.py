"""B5: record_feedback decisions schema — docstring contract (T1-1) + FeedbackEntry JSON-schema decision enum (T0-5)."""

import pytest
from pydantic import ValidationError

import youtube_manager
from youtube_manager import FeedbackEntry, Tools, parse_feedback_log

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
    # Scenario: T0-5.6 version bumped to 1.2.3
    #   Given the tool top docstring
    #   When it is parsed
    #   Then version == "1.2.3"
    def test_version_bumped_to_1_2_3(self):
        doc = youtube_manager.__doc__ or ""
        version = next(line.split(":", 1)[1].strip() for line in doc.splitlines() if line.startswith("version:"))
        assert version == "1.2.3"
