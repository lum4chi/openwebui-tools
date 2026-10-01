"""T5-1 (youtube-manager-bugfixes): transcript title is not "unknown" on the fallback path.

The metadata-only title lookup (`_video_title_lookup`, `_ytdlp_extract(url, extra=None)`) recovers a real
title/channel when the primary yt-dlp subtitle extraction failed (`info is None`) and the fallback returned
segments. The module-local `_ytdlp_extract` stub distinguishes the primary subtitle-bearing call (`extra`
is a dict) from the metadata-only title lookup (`extra is None`).
"""

import urllib.error
from unittest.mock import MagicMock

import youtube_manager


def _ytdlp_extract_stub(monkeypatch, *, primary, lookup):
    """Route the `_ytdlp_extract` seam: subtitle-bearing call (extra is a dict) vs metadata-only title lookup (extra is None)."""
    calls: list[tuple[str, dict | None]] = []

    def fake(url, extra=None):
        calls.append((url, extra))
        if isinstance(extra, dict):
            return primary()
        return lookup()

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _fallback_segments(monkeypatch):
    monkeypatch.setattr(youtube_manager, "_fetch_transcript_fallback", MagicMock(return_value=([(5, "fb one")], "en")))


class TestTranscriptTitleFallback:
    # @unit
    # Scenario: T5-1.S1 [unit] — recovery: primary fails, the metadata-only title lookup succeeds → real title in the header (+ language-fallback notice)
    # Given the primary yt-dlp subtitle-bearing call (extra is a dict) raises
    # And the metadata-only title lookup (extra is None) returns {"title": "Real Title", "uploader": "Real Channel"}
    # And the fallback transcript returns segments [(5, "fb one")] with language_code "en"
    # When transcript is called with video_id="vid123" and language="de"
    # Then the first line is exactly "Notice: transcript language fallback: requested de, used en"
    # And the second line is exactly "=== Podcast transcript: Real Title — Real Channel ==="
    # And the result contains "[0:05] fb one"
    # And the header line does not contain "unknown" and does not contain "vid123"
    async def test_title_lookup_recovers_real_title(self, tools, monkeypatch):
        def primary():
            raise urllib.error.URLError("dns down")

        def lookup():
            return {"title": "Real Title", "uploader": "Real Channel"}

        _ytdlp_extract_stub(monkeypatch, primary=primary, lookup=lookup)
        _fallback_segments(monkeypatch)

        result = await tools.transcript("vid123", language="de")

        lines = result.splitlines()
        assert lines[0] == "Notice: transcript language fallback: requested de, used en"
        assert lines[1] == "=== Podcast transcript: Real Title — Real Channel ==="
        assert "[0:05] fb one" in result
        assert "unknown" not in lines[1]
        assert "vid123" not in lines[1]

    # @unit
    # Scenario: T5-1.S2 [unit] — lookup also fails: the title stays "unknown" (graceful degradation, no crash)
    # Given the primary yt-dlp subtitle-bearing call raises
    # And the metadata-only title lookup (extra is None) ALSO raises
    # And the fallback transcript returns segments [(5, "fb one")] with language_code "en"
    # When transcript is called with video_id="vid123"
    # Then the first line is exactly "=== Podcast transcript: vid123 — unknown ==="
    # And the result contains "[0:05] fb one"
    async def test_title_lookup_failure_keeps_unknown(self, tools, monkeypatch):
        def primary():
            raise urllib.error.URLError("dns down")

        def lookup():
            raise urllib.error.URLError("dns down")

        _ytdlp_extract_stub(monkeypatch, primary=primary, lookup=lookup)
        _fallback_segments(monkeypatch)

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "=== Podcast transcript: vid123 — unknown ==="
        assert "[0:05] fb one" in result

    # @unit
    # Scenario: T5-1.S3 [unit] — no redundant lookup: primary already succeeded (info present) → the title is used and the metadata-only call is NOT made
    # Given the primary yt-dlp subtitle-bearing call returns {"title": "Real Title", "uploader": "Real Channel"} (no usable VTT)
    # And the fallback transcript returns segments [(5, "fb one")] with language_code "en"
    # When transcript is called with video_id="vid123"
    # Then the first line is exactly "=== Podcast transcript: Real Title — Real Channel ==="
    # And _ytdlp_extract is called exactly once (the primary call; no metadata-only title-lookup call)
    async def test_no_redundant_lookup_when_primary_succeeded(self, tools, monkeypatch):
        def primary():
            return {"title": "Real Title", "uploader": "Real Channel"}

        def lookup():
            raise AssertionError("metadata-only title lookup must not be made when the primary already succeeded")

        calls = _ytdlp_extract_stub(monkeypatch, primary=primary, lookup=lookup)
        _fallback_segments(monkeypatch)

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "=== Podcast transcript: Real Title — Real Channel ==="
        assert len(calls) == 1

    # @unit
    # Scenario: T5-1.S4 [unit] — title-less lookup result: a lookup that returns no usable title keeps the "unknown" header (covers the no-title branch)
    # Given the primary yt-dlp subtitle-bearing call raises
    # And the metadata-only title lookup (extra is None) returns {} (no "title" key)
    # And the fallback transcript returns segments [(5, "fb one")] with language_code "en"
    # When transcript is called with video_id="vid123"
    # Then the first line is exactly "=== Podcast transcript: vid123 — unknown ==="
    async def test_titleless_lookup_result_keeps_unknown(self, tools, monkeypatch):
        def primary():
            raise urllib.error.URLError("dns down")

        def lookup():
            return {}

        _ytdlp_extract_stub(monkeypatch, primary=primary, lookup=lookup)
        _fallback_segments(monkeypatch)

        result = await tools.transcript("vid123")

        lines = result.splitlines()
        assert lines[0] == "=== Podcast transcript: vid123 — unknown ==="
