"""T8-1 (Batch 8): per-video search isolation (B1) + per-source gather isolation (B3).

Scenarios S1-S6 (plan .opencode/plans/youtube-production-readiness.md, Task T8-1); Gherkin preserved verbatim.
"""

import urllib.error
from typing import Any

import youtube_manager
from youtube_manager import ReauthNeeded, Tools

WATCH = "https://www.youtube.com/watch?v="


def _entry(video_id):
    return {
        "id": video_id,
        "title": f"Search title {video_id}",
        "uploader": f"Search channel {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 300,
        "view_count": 1000,
        "upload_date": "20260910",
        "description": f"Search description {video_id}",
        "tags": [],
    }


def _ytdlp_fake(monkeypatch, flat: dict[str, list[str]], watch: dict[str, Any]):
    """Patch _ytdlp_extract: flat listings serve id-only rows; watch URLs serve an entry or raise."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        if url in flat:
            return {"entries": [{"id": video_id} for video_id in flat[url]]}
        outcome = watch[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _boom(exc):
    """Class-method stand-in that raises exc (for the _fetch_watch_later/_fetch_subscriptions seams)."""

    def raiser(self, *args, **kwargs):
        raise exc

    return raiser


def _notes_block(payload):
    return payload.split("=== Source notes ===\n", 1)[1]


class TestGatherIsolation:
    """B1 per-video search isolation + B3 per-source gather isolation (S1-S6)."""

    # @unit
    # Scenario: T8-1 S1 partial search isolation — one unavailable video does not abort search
    # Given a search listing that returns flat entries for ids "vid-a" and "vid-b"
    # And a mocked ytdlp that raises a network error (urllib.error.URLError) for the "vid-a" watch URL
    # And the mocked ytdlp returns a valid full entry for the "vid-b" watch URL
    # When gather_candidates is called with sources="search" and a non-empty search_query
    # Then the response is a candidates payload (not an error)
    # And the response contains the candidate built from "vid-b"
    # And the notes include exactly "skipped 1 unavailable: vid-a"
    async def test_s1_partial_search_isolation(self, tools, monkeypatch):
        flat = {"ytsearch20:rust async": ["vid-a", "vid-b"]}
        watch = {WATCH + "vid-a": urllib.error.URLError("network down"), WATCH + "vid-b": _entry("vid-b")}
        _ytdlp_fake(monkeypatch, flat, watch)

        payload = await tools.gather_candidates(sources="search", search_query="rust async")

        assert not payload.startswith("Error")
        assert "Search title vid-b" in payload  # the candidate built from "vid-b"
        assert "Candidate IDs: vid-b" in payload
        assert _notes_block(payload) == "skipped 1 unavailable: vid-a"

    # @unit
    # Scenario: T8-1 S2 all-unavailable search returns a clean error with the first reason
    # Given a search listing that returns a flat entry for id "vid-a"
    # And a mocked ytdlp that raises a network error (urllib.error.URLError) for the "vid-a" watch URL
    # When gather_candidates is called with sources="search" and a non-empty search_query
    # Then the response is exactly "Error: transient"
    async def test_s2_all_unavailable_clean_error(self, tools, monkeypatch):
        flat = {"ytsearch20:rust async": ["vid-a"]}
        watch = {WATCH + "vid-a": urllib.error.URLError("network down")}
        _ytdlp_fake(monkeypatch, flat, watch)

        payload = await tools.gather_candidates(sources="search", search_query="rust async")

        assert payload == "Error: transient"

    # @unit
    # Scenario: T8-1 S3 no search results is not an error
    # Given a search listing that returns zero flat entries
    # When gather_candidates is called with sources="search" and a non-empty search_query
    # Then the response is the empty candidates payload containing "(none)"
    # And the response is not an error
    # And no "skipped" note is added
    async def test_s3_no_results_not_an_error(self, tools, monkeypatch):
        _ytdlp_fake(monkeypatch, {"ytsearch20:rust async": []}, {})

        payload = await tools.gather_candidates(sources="search", search_query="rust async")

        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert not payload.startswith("Error")
        assert "skipped" not in payload

    # @unit
    # Scenario: T8-1 S4 per-source reauth isolation keeps healthy search results
    # Given watch_later configured with OAuth and a mocked fetch that raises ReauthNeeded
    # And a search that yields 1 available candidate
    # When gather_candidates is called with sources="watch_later,search" and a non-empty search_query
    # Then the response is a candidates payload (not an error)
    # And the response contains the search candidate
    # And the notes include exactly "watch_later failed: reauth"
    # And the response does not start with "REAUTH_NEEDED"
    async def test_s4_reauth_isolation_keeps_healthy_search(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager.Tools, "_fetch_watch_later", _boom(ReauthNeeded("stale")))
        flat = {"ytsearch20:rust async": ["vid-b"]}
        watch = {WATCH + "vid-b": _entry("vid-b")}
        _ytdlp_fake(monkeypatch, flat, watch)

        payload = await tools.gather_candidates(sources="watch_later,search", search_query="rust async")

        assert not payload.startswith("REAUTH_NEEDED")
        assert not payload.startswith("Error")
        assert "Search title vid-b" in payload  # the search candidate survives
        assert _notes_block(payload) == "watch_later failed: reauth"

    # @unit
    # Scenario: T8-1 S5 all sources reauth with no candidates returns the REAUTH block
    # Given watch_later and subscriptions configured with OAuth
    # And mocked fetches that raise ReauthNeeded for both sources
    # When gather_candidates is called with sources="watch_later,subscriptions"
    # Then the response starts with "REAUTH_NEEDED"
    # And the response includes the reauth Fix line
    async def test_s5_all_reauth_returns_block(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager.Tools, "_fetch_watch_later", _boom(ReauthNeeded("stale")))
        monkeypatch.setattr(youtube_manager.Tools, "_fetch_subscriptions", _boom(ReauthNeeded("stale")))

        payload = await tools.gather_candidates(sources="watch_later,subscriptions")

        assert payload.startswith("REAUTH_NEEDED")
        assert "watch_later failed: reauth" in payload
        assert "subscriptions failed: reauth" in payload
        assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload

    # @unit
    # Scenario: T8-1 S6 non-reauth failure isolation keeps healthy source results
    # Given watch_later configured with OAuth and a mocked fetch that raises urllib.error.URLError
    # And a search that yields 1 available candidate
    # When gather_candidates is called with sources="watch_later,search" and a non-empty search_query
    # Then the response is a candidates payload (not an error)
    # And the response contains the search candidate
    # And the notes include exactly "watch_later failed: transient"
    async def test_s6_non_reauth_failure_isolation(self, tools, monkeypatch):
        monkeypatch.setattr(youtube_manager.Tools, "_fetch_watch_later", _boom(urllib.error.URLError("network down")))
        flat = {"ytsearch20:rust async": ["vid-b"]}
        watch = {WATCH + "vid-b": _entry("vid-b")}
        _ytdlp_fake(monkeypatch, flat, watch)

        payload = await tools.gather_candidates(sources="watch_later,search", search_query="rust async")

        assert not payload.startswith("Error")
        assert "Search title vid-b" in payload
        assert _notes_block(payload) == "watch_later failed: transient"

    # Contract item 2 (_resolve_search_videos): a flat entry without a usable id is skipped —
    # no watch-URL fetch, no failure recorded (line-coverage pin for the resolver's id guard).
    def test_resolver_skips_idless_flat_entries(self, monkeypatch):
        calls: list[str] = []

        def fake(url, extra=None):
            calls.append(url)
            return _entry("vid-ok")

        monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)

        entries, failures = Tools._resolve_search_videos([{"id": "vid-ok"}, {}, {"id": ""}])

        assert [entry["id"] for entry in entries] == ["vid-ok"]
        assert failures == []
        assert calls == [WATCH + "vid-ok"]
