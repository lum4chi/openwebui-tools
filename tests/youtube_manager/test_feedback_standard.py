"""T9-3 M1: record_feedback standard vs non-standard video_id — warning line, not error (S1, S2)."""

from datetime import datetime

import pytest

from youtube_manager import NOTE_FEEDBACK

HEADER = "| date | video_id | decision | title | source | reason |"


class TestRecordFeedbackStandardId:
    """S1: standard 11-character ids keep the exact one-line success result."""

    # @unit
    # Scenario: T9-3 S1 standard video_id records without warning
    #   Given the feedback log is absent
    #   And video_id is the standard 11-character id "dQw4w9WgXcQ"
    #   And decision is "watched"
    #   When record_feedback runs
    #   Then the result is exactly "OK — recorded watched for dQw4w9WgXcQ"
    #     And the written feedback row contains the same video_id
    #     And the result contains no "Notice" line
    @pytest.mark.parametrize("video_id", ["dQw4w9WgXcQ", "vid010abcde"])
    async def test_standard_id_records_without_warning(self, tools, fake_store, video_id):
        today = datetime.now().date().isoformat()

        result = await tools.record_feedback(video_id, "watched")

        assert result == f"OK — recorded watched for {video_id}"
        assert "Notice" not in result
        lines = fake_store.docs[NOTE_FEEDBACK].strip().splitlines()
        assert lines[0] == HEADER
        assert lines[-1] == f"| {today} | {video_id} | watched |  | digest |  |"


class TestRecordFeedbackNonStandardId:
    """S2: non-standard ids are still recorded, with the two-line warning result."""

    # @unit
    # Scenario: T9-3 S2 non-standard video_id records with warning
    #   Given the feedback log is absent
    #   And video_id is "vid010"
    #   And decision is "watched"
    #   When record_feedback runs
    #   Then the result is exactly
    #     """
    #     OK — recorded watched for vid010
    #     Notice: video_id is not the standard 11-character format
    #     """
    #     And the written feedback row contains "vid010"
    @pytest.mark.parametrize("video_id", ["vid010", "dQw4w9WgXc", "dQw4w9WgXcQ1", "bad id"])
    async def test_non_standard_id_records_with_warning(self, tools, fake_store, video_id):
        today = datetime.now().date().isoformat()

        result = await tools.record_feedback(video_id, "watched")

        assert result == (
            f"OK — recorded watched for {video_id}\nNotice: video_id is not the standard 11-character format"
        )
        lines = fake_store.docs[NOTE_FEEDBACK].strip().splitlines()
        assert lines[0] == HEADER
        assert lines[-1] == f"| {today} | {video_id} | watched |  | digest |  |"
