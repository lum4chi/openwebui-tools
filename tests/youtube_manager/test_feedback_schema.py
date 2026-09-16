"""B5: record_feedback docstring documents the decisions schema (scenario T1-1)."""

from youtube_manager import Tools


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
