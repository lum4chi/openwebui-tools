"""T5-1 transcript chunked reads: max_lines/offset params + actionable truncation notice.

BDD: plan ``yt-deferred-backlog.md``, task T5-1 (scenarios T5-1-S1..S7).
"""

import pytest

from youtube_manager import assemble_podcast_text

_UNIQUE_461 = [(i, f"line {i}") for i in range(461)]
_UNIQUE_10 = [(i, f"line {i}") for i in range(10)]
_HDR = "=== Podcast transcript: T — C ==="


def _ts_lines(segments: list[tuple[int, str]]) -> list[str]:
    return [f"[{s // 60}:{s % 60:02d}] {t}" for s, t in segments]


class TestTranscriptChunking:
    # @unit
    # Scenario: T5-1-S1 default call keeps the 400-line cap with an actionable notice (unit)
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc", language="en") with no chunking params
    #   Then the output has 402 lines (header + 400 transcript lines + notice)
    #   And the last line is exactly
    #     "... (truncated at 400 lines; 61 transcript segment(s) omitted; next chunk: transcript(video_id=\"abc\", language=\"en\", offset=400, max_lines=400))"
    def test_default_cap_actionable_notice(self):
        lines = assemble_podcast_text("abc", "T", "C", _UNIQUE_461).splitlines()
        assert len(lines) == 402
        assert lines[0] == _HDR
        assert lines[1:401] == _ts_lines(_UNIQUE_461[:400])
        assert lines[-1] == (
            "... (truncated at 400 lines; 61 transcript segment(s) omitted; "
            'next chunk: transcript(video_id="abc", language="en", offset=400, max_lines=400))'
        )

    # @workflow
    # Scenario: T5-1-S2 two chunks cover the full transcript (workflow)
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc") runs with defaults
    #   And transcript(video_id="abc", offset=400) runs second
    #   Then chunk 1 has 400 transcript lines and chunk 2 has exactly the remaining 61
    #   And the two chunks' transcript lines, in order, equal all 461 segments with no duplicates
    #   And chunk 2 contains no truncation notice
    def test_two_chunk_read_covers_full_transcript(self):
        chunk1 = assemble_podcast_text("abc", "T", "C", _UNIQUE_461).splitlines()
        chunk2 = assemble_podcast_text("abc", "T", "C", _UNIQUE_461, offset=400).splitlines()
        assert len(chunk1) == 402
        assert chunk1[1:401] == _ts_lines(_UNIQUE_461[:400])
        assert len(chunk2) == 62
        assert chunk2[1:] == _ts_lines(_UNIQUE_461[400:])
        assert chunk1[1:401] + chunk2[1:] == _ts_lines(_UNIQUE_461)
        assert not any("truncated" in line for line in chunk2)

    # @unit
    # Scenario: T5-1-S3 max_lines smaller than the remainder is honored and echoed (unit)
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc", max_lines=100)
    #   Then the output has header + 100 transcript lines + notice
    #   And the notice ends with "offset=100, max_lines=100))"
    def test_max_lines_hundred_notice_echoes_params(self):
        lines = assemble_podcast_text("abc", "T", "C", _UNIQUE_461, max_lines=100).splitlines()
        assert len(lines) == 102
        assert lines[1:101] == _ts_lines(_UNIQUE_461[:100])
        assert lines[-1].startswith("... (truncated at 100 lines; 361 transcript segment(s) omitted; ")
        assert lines[-1].endswith('next chunk: transcript(video_id="abc", language="en", offset=100, max_lines=100))')

    # @unit
    # Scenario: T5-1-S4 max_lines=1 boundary (unit)
    #   Given a transcript with 10 unique segments
    #   When transcript(video_id="abc", max_lines=1)
    #   Then the output has header + exactly 1 transcript line + notice ending "offset=1, max_lines=1))"
    def test_max_lines_one_boundary(self):
        lines = assemble_podcast_text("abc", "T", "C", _UNIQUE_10, max_lines=1).splitlines()
        assert len(lines) == 3
        assert lines[0] == _HDR
        assert lines[1] == _ts_lines(_UNIQUE_10[:1])[0]
        assert lines[2].endswith("offset=1, max_lines=1))")

    # @unit
    # Scenario: T5-1-S5 offset beyond the end is an actionable error (unit)
    #   Given a transcript with 461 segments
    #   When transcript(video_id="abc", offset=461)
    #   Then the output is exactly "Error: transcript offset 461 is beyond the end of the transcript (461 segment(s) total)"
    #   And when transcript(video_id="abc", offset=1000)
    #   Then the output is exactly "Error: transcript offset 1000 is beyond the end of the transcript (461 segment(s) total)"
    @pytest.mark.parametrize(
        ("offset", "expected"),
        [
            (461, "Error: transcript offset 461 is beyond the end of the transcript (461 segment(s) total)"),
            (1000, "Error: transcript offset 1000 is beyond the end of the transcript (461 segment(s) total)"),
        ],
    )
    def test_offset_beyond_end_error(self, offset, expected):
        assert assemble_podcast_text("abc", "T", "C", _UNIQUE_461, offset=offset) == expected

    # @unit
    # T5-1 contract L239–241 (review-directed regression pin): omitted count for an offset>0 chunk is
    #   len(segments) - next_offset, where next_offset = offset + raw segment index at break.
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc", max_lines=100, offset=100)
    #   Then the notice is exactly
    #     "... (truncated at 100 lines; 261 transcript segment(s) omitted; next chunk: transcript(video_id=\"abc\", language=\"en\", offset=200, max_lines=100))"
    def test_offset_cap_break_notice_omitted_count(self):
        lines = assemble_podcast_text("abc", "T", "C", _UNIQUE_461, max_lines=100, offset=100).splitlines()
        assert len(lines) == 102
        assert lines[1:101] == _ts_lines(_UNIQUE_461[100:200])
        assert lines[-1] == (
            "... (truncated at 100 lines; 261 transcript segment(s) omitted; "
            'next chunk: transcript(video_id="abc", language="en", offset=200, max_lines=100))'
        )

    # @unit
    # Scenario: T5-1-S6 negative params clamp to the defaults (unit)
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc", offset=-7, max_lines=-100)
    #   Then the output is identical to the default-call output for the same input
    def test_negative_params_clamp_to_default(self):
        default = assemble_podcast_text("abc", "T", "C", _UNIQUE_461)
        clamped = assemble_podcast_text("abc", "T", "C", _UNIQUE_461, max_lines=-100, offset=-7)
        assert clamped == default

    # @unit
    # Scenario: T5-1-S7 mid-offset chunk without truncation is plain (unit)
    #   Given a transcript with 461 unique segments
    #   When transcript(video_id="abc", offset=400)
    #   Then the output is header + exactly the last 61 segments, in order
    #   And contains no "truncated" text
    def test_mid_offset_chunk_no_notice(self):
        lines = assemble_podcast_text("abc", "T", "C", _UNIQUE_461, offset=400).splitlines()
        assert lines[0] == _HDR
        assert lines[1:] == _ts_lines(_UNIQUE_461[400:])
        assert not any("truncated" in line for line in lines)
