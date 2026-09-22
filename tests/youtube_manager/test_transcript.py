"""T2 transcript -> podcast format: primary/fallback paths (T2-1..T2-4, T2-6), VTT parse/assembly edges (T2-6)."""

import re
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from yt_dlp.utils import DownloadError, ExtractorError

import youtube_manager
from youtube_manager import TranscriptUnavailable, assemble_podcast_text, parse_vtt

_HDR = "=== Podcast transcript: T — C ==="
_SEGS_400 = [(i, f"line {i}") for i in range(1, 401)]
_SEGS_401 = [*_SEGS_400, (401, "line 401")]


def _vtt_ts(sec: int) -> str:
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}.000"


def _vtt(segments: list[tuple[int, str]]) -> str:
    """WEBVTT document with one cue per (start, text) segment."""
    blocks = ["WEBVTT"]
    for idx, (start, text) in enumerate(segments, start=1):
        blocks.append(f"{idx}\n{_vtt_ts(start)} --> {_vtt_ts(start + 2)}\n{text}")
    return "\n\n".join(blocks) + "\n"


def _pod(segments: list[tuple[int, str]]) -> list[str]:
    return [_HDR] + [f"[{s // 60}:{s % 60:02d}] {t}" for s, t in segments]


class _YtdlpStub:
    """Records _ytdlp_extract calls; returns info or raises; may write the VTT the way yt-dlp would."""

    def __init__(self, info: dict | None = None, exc: Exception | None = None, write_glob_vtt: str | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.info = info
        self.exc = exc
        self.write_glob_vtt = write_glob_vtt

    def __call__(self, url, extra: dict):
        self.calls.append((url, extra))
        if self.exc is not None:
            raise self.exc
        if self.write_glob_vtt is not None:
            (Path(extra["outtmpl"]).parent / "sub.vtt").write_text(self.write_glob_vtt)
        return self.info or {}


class TestTranscript:
    """transcript() primary/fallback resolution (caller-level: seams patched)."""

    # @unit
    # Scenario: T2-1 podcast format
    #   Given the yt-dlp seam yields caption segments for the video
    #   When the tool runs transcript
    #   Then the result starts with a header naming title and channel
    #   And every segment line has the form "[m:ss] text"
    #   And timestamps are monotonically non-decreasing
    async def test_podcast_format(self, tools, monkeypatch, tmp_path):
        vtt = tmp_path / "cap.vtt"
        vtt.write_text(_vtt([(5, "hello world"), (7, "second line")]))
        stub = _YtdlpStub(
            info={
                "title": "My Video",
                "uploader": "My Channel",
                "requested_subtitles": {"en": {"filepath": str(vtt)}},
            }
        )
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", stub)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock())

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "=== Podcast transcript: My Video — My Channel ==="
        assert lines[1:]
        assert all(re.fullmatch(r"\[\d+:\d{2}\] .+", line) for line in lines[1:])
        pairs = re.findall(r"\[(\d+):(\d{2})\]", "\n".join(lines[1:]))
        stamps = [int(minutes) * 60 + int(seconds) for minutes, seconds in pairs]
        assert stamps == sorted(stamps)  # monotonically non-decreasing
        assert "[0:05] hello world" in lines
        assert "[0:07] second line" in lines

    # @unit
    # Scenario: T2-2 primary path
    #   Given the yt-dlp seam returns auto-caption segments
    #   When transcript runs
    #   Then the fallback transcript seam is NOT called
    #   And the segments come from the yt-dlp result
    #   And the requested-language path has no notice while the glob path gets a "used unknown" notice
    @pytest.mark.parametrize("variant", ["filepath", "glob"], ids=["filepath", "glob"])
    async def test_primary_path(self, tools, monkeypatch, tmp_path, variant):
        segments = [(5, "auto caption line")]
        info: dict[str, object] = {"title": "P Title", "uploader": "P Channel"}
        write_glob_vtt = None
        if variant == "filepath":
            vtt = tmp_path / "cap.vtt"
            vtt.write_text(_vtt(segments))
            info["requested_subtitles"] = {"en": {"filepath": str(vtt)}}
        else:
            write_glob_vtt = _vtt(segments)
        stub = _YtdlpStub(info=info, write_glob_vtt=write_glob_vtt)
        fb = MagicMock()
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", stub)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fb)

        result = await tools.transcript("vid123")

        fb.assert_not_called()
        url, extra = stub.calls[0]
        assert url == "https://www.youtube.com/watch?v=vid123"
        assert extra["writeautomaticsub"] is True
        assert extra["writesubtitles"] is True
        assert extra["subtitleslangs"] == ["en"]
        assert extra["skip_download"] is True
        assert extra["outtmpl"].endswith("/sub.%(ext)s")
        assert not Path(extra["outtmpl"]).parent.exists()  # per-call tmp removed after parsing
        lines = result.splitlines()
        if variant == "filepath":
            assert lines[0] == "=== Podcast transcript: P Title — P Channel ==="
        else:
            assert lines[0] == "Notice: transcript language fallback: requested en, used unknown"
            assert lines[1] == "=== Podcast transcript: P Title — P Channel ==="
        assert "[0:05] auto caption line" in lines

    # @unit
    # Scenario: T2-3 fallback
    #   Given the yt-dlp seam reports no captions
    #   And the fallback seam returns segments
    #   When transcript runs
    #   Then the result contains the fallback segments in podcast format
    @pytest.mark.parametrize(
        ("variant", "header"),
        [
            pytest.param("info", "=== Podcast transcript: F Title — F Channel ===", id="info_without_subtitles"),
            pytest.param("raised", "=== Podcast transcript: vid123 — unknown ===", id="primary_raised"),
        ],
    )
    async def test_fallback_path(self, tools, monkeypatch, variant, header):
        if variant == "info":
            stub = _YtdlpStub(info={"title": "F Title", "uploader": "F Channel"})
        else:
            stub = _YtdlpStub(exc=Exception("no captions found"))
        fb = MagicMock(return_value=([(5, "fb one"), (60, "fb two")], "en"))
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", stub)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fb)

        result = await tools.transcript("vid123")

        fb.assert_called_once_with("vid123")
        lines = result.splitlines()
        assert lines[0] == header
        assert "[0:05] fb one" in lines
        assert "[1:00] fb two" in lines

    # @unit
    # Scenario: T8-2 S5 no captions is a clean non-error result
    #   Given a primary yt-dlp subtitle extraction that succeeds but yields no usable VTT segments
    #   And a fallback transcript fetch that returns no segments
    #   When transcript is called with video_id="vid123"
    #   Then the response is exactly "No captions found for vid123"
    #   And the response does not start with "Error:"
    # Variant: the fallback dependency is missing (TranscriptUnavailable) — the no-captions result is still clean.
    async def test_fallback_missing(self, tools, monkeypatch):
        stub = _YtdlpStub(info={})
        fb = MagicMock(side_effect=TranscriptUnavailable("fallback dependency not installed"))
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", stub)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fb)

        result = await tools.transcript("vid123")

        assert result == "No captions found for vid123"

    # @unit
    # Scenario: T8-2 S5 no captions is a clean non-error result
    #   Given a primary yt-dlp subtitle extraction that succeeds but yields no usable VTT segments
    #   And a fallback transcript fetch that returns no segments
    #   When transcript is called with video_id="vid123"
    #   Then the response is exactly "No captions found for vid123"
    #   And the response does not start with "Error:"
    # Retained S2 guard: [primary_raised] keeps the plain-exception "unexpected error" true-failure pin.
    @pytest.mark.parametrize(
        ("variant", "expected"),
        [
            pytest.param("info", "No captions found for vid123", id="info_without_subtitles"),
            pytest.param("missing_file", "No captions found for vid123", id="vtt_file_missing"),
            pytest.param(
                "raised",
                "Error: no transcript available for vid123: primary: unexpected error; fallback: no transcript returned",
                id="primary_raised",
            ),
        ],
    )
    async def test_no_transcript_message(self, tools, monkeypatch, tmp_path, variant, expected):
        if variant == "info":
            stub = _YtdlpStub(info={})
        elif variant == "missing_file":
            stub = _YtdlpStub(info={"requested_subtitles": {"en": {"filepath": str(tmp_path / "gone.vtt")}}})
        else:
            stub = _YtdlpStub(exc=Exception("no subtitles found"))
        fb = MagicMock(return_value=([], None))
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", stub)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fb)

        result = await tools.transcript("vid123")

        assert result == expected

    # @workflow [AC-2]
    # Scenario: B4 transcript failure reports clean primary and fallback reasons / extraction reasons
    #   Given a video id "abc" whose primary transcript raises URLError (or ExtractorError)
    #   And the fallback raises TimeoutError (or DownloadError)
    #   When transcript resolution is attempted
    #   Then the return is exactly "Error: no transcript available for abc: primary: <clean>; fallback: <clean>"
    @pytest.mark.parametrize(
        ("primary_exc", "fallback_exc", "expected"),
        [
            (
                urllib.error.URLError("dns down"),
                TimeoutError("slow"),
                "Error: no transcript available for abc: primary: network error; fallback: network error",
            ),
            (
                ExtractorError("bot check"),
                DownloadError("download failed"),
                "Error: no transcript available for abc: primary: transcript extraction failed; fallback: transcript extraction failed",
            ),
        ],
        ids=["network_reasons", "extraction_reasons"],
    )
    async def test_b4_clean_primary_fallback_reasons(self, tools, monkeypatch, primary_exc, fallback_exc, expected):
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", MagicMock(side_effect=primary_exc))
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock(side_effect=fallback_exc))

        result = await tools.transcript("abc")

        assert result == expected


class TestVtt:
    """parse_vtt + assemble_podcast_text edge cases (pure functions)."""

    # @unit
    # Scenario: T2-6 parsing edges
    #   Given VTT inputs: empty file; header-only; overlapping duplicate lines; 401+ lines
    #   When parse_vtt and assemble_podcast_text run
    #   Then empty → no segments; duplicate consecutive lines collapse to one; >400 lines truncate with a marker
    #   And timestamps parse from VTT 00:00:05.120 --> form to integer seconds
    @pytest.mark.parametrize(
        ("vtt_text", "segments", "expected_lines"),
        [
            pytest.param("", [], [_HDR], id="empty"),
            pytest.param("WEBVTT\n", [], [_HDR], id="header_only"),
            pytest.param(
                _vtt([(5, "hello"), (65, "long"), (3723, "with hours")]),
                [(5, "hello"), (65, "long"), (3723, "with hours")],
                _pod([(5, "hello"), (65, "long"), (3723, "with hours")]),
                id="integer_seconds",
            ),
            pytest.param(
                _vtt([(5, "same line"), (6, "same line")]),
                [(5, "same line"), (6, "same line")],
                _pod([(5, "same line")]),
                id="duplicate_lines_collapse",
            ),
            pytest.param(None, _SEGS_400, _pod(_SEGS_400), id="cap_400_no_marker"),
            pytest.param(None, _SEGS_401, _pod(_SEGS_400) + ["... (truncated at 400 lines)"], id="truncate_401"),
        ],
    )
    def test_parse_and_assemble_edges(self, vtt_text, segments, expected_lines):
        parsed = segments if vtt_text is None else parse_vtt(vtt_text)
        if vtt_text is not None:
            assert parsed == segments
        result = assemble_podcast_text("T", "C", parsed)
        assert result.splitlines() == expected_lines
