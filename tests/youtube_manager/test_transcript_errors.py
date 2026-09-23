"""T8-2 transcript exception reason mapping, video_id pre-validation, no-captions distinction (S1, S3, S4, S5).

T4-1 (youtube-manager-bugfixes): transcript fallback surfaces the real not-found / no-subtitle-track reason.
"""

import email.message
import urllib.error
from unittest.mock import MagicMock

import pytest

import youtube_manager
from youtube_manager import _clean_exception

_TRANSCRIPT_API_NAMES = [
    ("NoTranscriptFound", "no transcript found"),
    ("TranscriptsDisabled", "transcripts disabled"),
    ("VideoUnavailable", "video unavailable"),
    ("TranscriptRetrievalFailed", "transcript retrieval failed"),
    ("CouldNotRetrieveTranscript", "transcript retrieval failed"),
    ("InvalidVideoId", "invalid video id"),
]


class TestCleanExceptionReasons:
    """_clean_exception maps youtube-transcript-api exception names to specific reasons (by type name, D4)."""

    # @unit
    # Scenario: T8-2 S1 youtube-transcript-api exception names map to specific reasons
    #   Given a dummy exception class whose __name__ is one of the six mapped transcript-api names
    #   When _clean_exception is called on an instance of that class
    #   Then it returns the mapped reason string (parametrized over all six names)
    @pytest.mark.parametrize(
        ("exc_name", "expected"),
        _TRANSCRIPT_API_NAMES,
        ids=[name for name, _ in _TRANSCRIPT_API_NAMES],
    )
    def test_transcript_api_exception_names_map_to_reasons(self, exc_name, expected):
        exc = type(exc_name, (Exception,), {})()
        assert _clean_exception(exc) == expected


class TestVideoIdPreCheck:
    """transcript() rejects an invalid video_id before any I/O (S3)."""

    # @unit
    # Scenario: T8-2 S3 invalid video_id is rejected before any I/O
    #   Given an invalid video_id such as "a/b"
    #   When transcript is called with that video_id
    #   Then the response is exactly "Error: invalid video_id: 'a/b'"
    #     And no subtitle/temp I/O is attempted
    #     And a valid id such as "vid123" still proceeds
    async def test_invalid_video_id_rejected_before_io(self, tools, monkeypatch):
        ytdlp = MagicMock()
        fallback = MagicMock()
        mkdtemp = MagicMock()
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", ytdlp)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fallback)
        monkeypatch.setattr("tempfile.mkdtemp", mkdtemp)

        result = await tools.transcript("a/b")

        assert result == "Error: invalid video_id: 'a/b'"
        ytdlp.assert_not_called()
        fallback.assert_not_called()
        mkdtemp.assert_not_called()

    # @unit
    # Scenario: T8-2 S3 invalid video_id is rejected before any I/O (valid-id proceeds)
    #   Given an invalid video_id such as "a/b"
    #   When transcript is called with that video_id
    #   Then the response is exactly "Error: invalid video_id: 'a/b'"
    #     And no subtitle/temp I/O is attempted
    #     And a valid id such as "vid123" still proceeds
    async def test_valid_video_id_still_proceeds(self, tools, monkeypatch):
        ytdlp = MagicMock(side_effect=urllib.error.URLError("dns down"))
        fallback = MagicMock(return_value=([], None))
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", ytdlp)
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", fallback)

        result = await tools.transcript("vid123")

        assert ytdlp.call_count == 1
        assert result == (
            "Error: no transcript available for vid123: primary: network error; fallback: no transcript returned"
        )


class TestTranscriptEndToEndReasons:
    """End-to-end transcript reasons (S4) and the no-captions clean result (S5)."""

    # @unit
    # Scenario: T8-2 S4 a transcript-api fallback failure surfaces its specific reason end-to-end
    #   Given a primary yt-dlp subtitle extraction that raises urllib.error.URLError
    #   And a fallback transcript fetch that raises a NoTranscriptFound exception
    #   When transcript is called with video_id="vid123"
    #   Then the response is exactly "Error: no transcript available for vid123: primary: network error; fallback: no transcript found"
    async def test_primary_urlerror_fallback_notranscriptfound(self, tools, monkeypatch):
        monkeypatch.setattr(
            youtube_manager,
            "_ytdlp_extract",
            MagicMock(side_effect=urllib.error.URLError("dns down")),
        )
        monkeypatch.setattr(
            youtube_manager,
            "_fetch_transcript_fallback",
            MagicMock(side_effect=type("NoTranscriptFound", (Exception,), {})("no transcript found")),
        )

        result = await tools.transcript("vid123")

        assert result == (
            "Error: no transcript available for vid123: primary: network error; fallback: no transcript found"
        )

    # @unit
    # Scenario: T8-2 S5 no captions is a clean non-error result
    #   Given a primary yt-dlp subtitle extraction that succeeds but yields no usable VTT segments
    #   And a fallback transcript fetch that returns no segments
    #   When transcript is called with video_id="vid123"
    #   Then the response is exactly "No captions found for vid123"
    #   And the response does not start with "Error:"
    async def test_no_captions_clean_non_error_result(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", MagicMock(return_value={}))
        monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock(return_value=([], None)))

        result = await tools.transcript("vid123")

        assert result == "No captions found for vid123"
        assert not result.startswith("Error:")


class TestTranscriptFallbackReasons:
    """T4-1: the not-found / no-subtitle-track classes map to their specific reasons, not "unexpected error"."""

    # @unit
    # Scenario: T4-1.S1 [unit] — video-doesn't-exist class unifies to one specific reason end-to-end (both ids; not "unexpected error")
    # Given a video whose primary yt-dlp subtitle extraction raises the not-found-class exception "VideoNotFound"
    # And a fallback transcript fetch that also raises the not-found-class exception "VideoNotFound"
    # When transcript is called with video_id="invalid_id_12345" and then again with video_id="00000000000"
    # Then both results carry the SAME fallback reason "video unavailable"
    # And neither result's fallback reason is "unexpected error"
    # And the first result is exactly "Error: no transcript available for invalid_id_12345: primary: video unavailable; fallback: video unavailable"
    async def test_video_not_found_class_unifies_to_one_reason(self, tools, monkeypatch):
        not_found = type("VideoNotFound", (Exception,), {})
        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", MagicMock(side_effect=not_found("video unavailable")))
        monkeypatch.setattr(
            youtube_manager, "_fetch_transcript_fallback", MagicMock(side_effect=not_found("video unavailable"))
        )

        first = await tools.transcript("invalid_id_12345")
        second = await tools.transcript("00000000000")

        assert first == (
            "Error: no transcript available for invalid_id_12345: primary: video unavailable; fallback: video unavailable"
        )
        assert second == (
            "Error: no transcript available for 00000000000: primary: video unavailable; fallback: video unavailable"
        )
        assert "unexpected error" not in first
        assert "unexpected error" not in second

    # @unit
    # Scenario: T4-1.S2 [unit] — no-subtitle-track class maps to its own short reason (not "unexpected error")
    # Given a dummy exception class whose __name__ is "NoSubtitleTrack" (not currently in _TRANSCRIPT_API_REASONS)
    # When _clean_exception is called on an instance of that class
    # Then it returns exactly "no subtitle track"
    def test_no_subtitle_track_maps_to_own_reason(self):
        exc = type("NoSubtitleTrack", (Exception,), {})("no subtitle track")

        assert _clean_exception(exc) == "no subtitle track"

    # @unit
    # Scenario: T4-1.S3 [unit] — regression guard: the HTTP not-found / rate-limited reasons the user named stay intact
    # Given a urllib HTTPError with status 404 and a urllib HTTPError with status 429
    # When _clean_exception is called on each
    # Then the 404 maps to "not found - the resource no longer exists"
    # And the 429 maps to "rate limited - retry later"
    def test_http_404_and_429_reasons_stay_intact(self):
        e404 = urllib.error.HTTPError(
            "https://www.googleapis.com/youtube/v3/x", 404, "Not Found", email.message.Message(), None
        )
        e429 = urllib.error.HTTPError(
            "https://www.googleapis.com/youtube/v3/x", 429, "Too Many Requests", email.message.Message(), None
        )

        assert _clean_exception(e404) == "not found - the resource no longer exists"
        assert _clean_exception(e429) == "rate limited - retry later"
