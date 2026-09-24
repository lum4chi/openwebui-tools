"""T9-5 transcript truncation: remaining-count marker in assemble_podcast_text."""

from youtube_manager import assemble_podcast_text

_UNIQUE_401 = [(i, f"line {i}") for i in range(1, 402)]
_UNIQUE_461 = [(i, f"line {i}") for i in range(1, 462)]
_UNDER_CAP_400 = [(i, f"line {i}") for i in range(1, 401)]
_DUP_LAST_SEGMENT = _UNDER_CAP_400 + [(401, "line 400")]


def _ts_lines(segments: list[tuple[int, str]]) -> list[str]:
    return [f"[{s // 60}:{s % 60:02d}] {t}" for s, t in segments]


class TestTranscriptTruncation:
    """Remaining-count truncation marker (pure function, T9-5 S1–S3)."""

    # @unit
    # Scenario: T9-5 S1 transcript truncation marker reports one omitted segment
    #   Given 401 unique transcript segments
    #   When assemble_podcast_text runs
    #   Then the payload contains exactly 400 timestamped transcript lines
    #     And the final line is exactly
    #       "... (truncated at 400 lines; 1 transcript segment(s) omitted; next chunk: transcript(video_id=\"vid\", language=\"en\", offset=400, max_lines=400))"
    #   (T5-1: notice is the actionable chunk-continuation form)
    def test_truncation_marker_one_omitted_segment(self):
        lines = assemble_podcast_text("vid", "T", "C", _UNIQUE_401).splitlines()
        assert lines[1:401] == _ts_lines(_UNIQUE_401[:400])
        assert lines[-1] == (
            "... (truncated at 400 lines; 1 transcript segment(s) omitted; "
            'next chunk: transcript(video_id="vid", language="en", offset=400, max_lines=400))'
        )
        assert len(lines) == 402

    # @unit
    # Scenario: T9-5 S2 transcript truncation marker reports the full remaining count
    #   Given 461 unique transcript segments
    #   When assemble_podcast_text runs
    #   Then the payload contains exactly 400 timestamped transcript lines
    #     And the final line is exactly
    #       "... (truncated at 400 lines; 61 transcript segment(s) omitted; next chunk: transcript(video_id=\"vid\", language=\"en\", offset=400, max_lines=400))"
    #   (T5-1: notice is the actionable chunk-continuation form)
    def test_truncation_marker_remaining_count(self):
        lines = assemble_podcast_text("vid", "T", "C", _UNIQUE_461).splitlines()
        assert lines[1:401] == _ts_lines(_UNIQUE_461[:400])
        assert lines[-1] == (
            "... (truncated at 400 lines; 61 transcript segment(s) omitted; "
            'next chunk: transcript(video_id="vid", language="en", offset=400, max_lines=400))'
        )
        assert len(lines) == 402

    # @unit
    # Scenario: T9-5 S3 under-cap transcripts have no truncation marker
    #   Given transcript segments that produce at most 400 timestamped lines
    #   When assemble_podcast_text runs
    #   Then the payload contains no line starting with "... (truncated at 400 lines"
    #     And the payload matches the pre-T9-5 under-cap podcast shape
    def test_under_cap_has_no_marker(self):
        exactly_400 = assemble_podcast_text("vid", "T", "C", _UNDER_CAP_400).splitlines()
        assert not any(ln.startswith("... (truncated at 400 lines") for ln in exactly_400)
        assert exactly_400[1:] == _ts_lines(_UNDER_CAP_400)
        assert len(exactly_400) == 401
        dup_last = assemble_podcast_text("vid", "T", "C", _DUP_LAST_SEGMENT).splitlines()
        assert not any(ln.startswith("... (truncated at 400 lines") for ln in dup_last)
        assert dup_last[1:] == _ts_lines(_UNDER_CAP_400)
        assert len(dup_last) == 401
