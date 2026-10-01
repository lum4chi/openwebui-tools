"""T7-3 transcript language fallback notice (B4): notice line when the used transcript language differs from the requested one."""

from pathlib import Path
from unittest.mock import MagicMock

import youtube_manager

_HDR = "=== Podcast transcript: P Title — P Channel ==="
_FALLBACK_HEADER = "=== Podcast transcript: vid123 — unknown ==="


def _vtt_ts(sec: int) -> str:
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}.000"


def _vtt(segments: list[tuple[int, str]]) -> str:
    """WEBVTT document with one cue per (start, text) segment."""
    blocks = ["WEBVTT"]
    for idx, (start, text) in enumerate(segments, start=1):
        blocks.append(f"{idx}\n{_vtt_ts(start)} --> {_vtt_ts(start + 2)}\n{text}")
    return "\n\n".join(blocks) + "\n"


class _YtdlpStub:
    """Records _ytdlp_extract calls; returns info or raises; may write the VTT the way yt-dlp would."""

    def __init__(self, info: dict | None = None, exc: Exception | None = None, write_glob_vtt: str | None = None):
        self.info = info
        self.exc = exc
        self.write_glob_vtt = write_glob_vtt

    def __call__(self, url, extra: dict):
        if self.exc is not None:
            raise self.exc
        if self.write_glob_vtt is not None:
            (Path(extra["outtmpl"]).parent / "sub.vtt").write_text(self.write_glob_vtt)
        return self.info or {}


class TestTranscriptLanguageNotice:
    """B4: notice line when used transcript language differs from the requested language."""

    # @unit [AC-B4]
    # Scenario: T7-3 primary requested language used has no notice
    #   Given the primary transcript path returns segments for the requested language
    #   When transcript runs
    #   Then the first line is the podcast header
    #     And no "Notice:" line is present
    async def test_primary_requested_language_no_notice(self, tools, monkeypatch, tmp_path):
        vtt = tmp_path / "cap.vtt"
        vtt.write_text(_vtt([(5, "seg one")]))
        info = {"title": "P Title", "uploader": "P Channel", "requested_subtitles": {"en": {"filepath": str(vtt)}}}
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", _YtdlpStub(info=info))
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock())

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == _HDR
        assert not any(line.startswith("Notice:") for line in lines)

    # @unit [AC-B4]
    # Scenario: T7-3 primary different language used adds a notice
    #   Given the primary transcript path returns segments for a language different from the requested language
    #   When transcript runs
    #   Then the first line is exactly "Notice: transcript language fallback: requested en, used de"
    #     And the second line is the podcast header
    async def test_primary_different_language_notice(self, tools, monkeypatch):
        info = {"title": "P Title", "uploader": "P Channel", "requested_subtitles": {"de": {}}}
        monkeypatch.setattr(
            youtube_manager, "_ytdlp_extract", _YtdlpStub(info=info, write_glob_vtt=_vtt([(5, "seg one")]))
        )
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock())

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "Notice: transcript language fallback: requested en, used de"
        assert lines[1] == _HDR

    # @unit [AC-B4]
    # Scenario: T7-3 primary unknown language used adds a notice
    #   Given the primary transcript path returns segments but no requested_subtitles entry identifies the language
    #   When transcript runs with language "en"
    #   Then the first line is exactly "Notice: transcript language fallback: requested en, used unknown"
    #     And the second line is the podcast header
    async def test_primary_unknown_language_notice(self, tools, monkeypatch):
        info = {"title": "P Title", "uploader": "P Channel"}
        monkeypatch.setattr(
            youtube_manager, "_ytdlp_extract", _YtdlpStub(info=info, write_glob_vtt=_vtt([(5, "seg one")]))
        )
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock())

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "Notice: transcript language fallback: requested en, used unknown"
        assert lines[1] == _HDR

    # @unit [AC-B4]
    # Scenario: T7-3 fallback language differs adds a notice
    #   Given the primary transcript path fails
    #   And the fallback returns segments with a language different from the requested language
    #   When transcript runs
    #   Then the first line is exactly "Notice: transcript language fallback: requested en, used de"
    #     And the fallback segments are still rendered in podcast format
    async def test_fallback_language_differs_notice(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", _YtdlpStub(exc=Exception("no captions found")))
        monkeypatch.setattr(
            youtube_manager,
            "_fetch_transcript_fallback",
            MagicMock(return_value=([(5, "fb one"), (60, "fb two")], "de")),
        )

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "Notice: transcript language fallback: requested en, used de"
        assert lines[1] == _FALLBACK_HEADER
        assert "[0:05] fb one" in lines
        assert "[1:00] fb two" in lines

    # @unit [AC-B4]
    # Scenario: T7-3 fallback language unavailable reports unknown
    #   Given the primary transcript path fails
    #   And the fallback returns segments with no language code
    #   When transcript runs with language "en"
    #   Then the first line is exactly "Notice: transcript language fallback: requested en, used unknown"
    #     And the fallback segments are still rendered in podcast format
    async def test_fallback_language_unavailable_notice(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", _YtdlpStub(exc=Exception("no captions found")))
        monkeypatch.setattr(
            youtube_manager,
            "_fetch_transcript_fallback",
            MagicMock(return_value=([(5, "fb one"), (60, "fb two")], None)),
        )

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "Notice: transcript language fallback: requested en, used unknown"
        assert lines[1] == _FALLBACK_HEADER
        assert "[0:05] fb one" in lines
        assert "[1:00] fb two" in lines

    # @unit [AC-B4]
    # Scenario: T8-2 S5 no captions is a clean non-error result
    #   Given a primary yt-dlp subtitle extraction that succeeds but yields no usable VTT segments
    #   And a fallback transcript fetch that returns no segments
    #   When transcript is called with video_id="vid123"
    #   Then the response is exactly "No captions found for vid123"
    #   And the response does not start with "Error:"
    #   And no "Notice:" line is present (T7-3 no-Notice invariant, D9)
    async def test_error_path_unchanged_no_notice(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", _YtdlpStub(info={}))
        monkeypatch.setattr(
            youtube_manager,
            "_fetch_transcript_fallback",
            MagicMock(return_value=([], None)),
        )

        result = await tools.transcript("vid123")

        assert result == "No captions found for vid123"
        assert "Notice:" not in result
