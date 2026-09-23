"""Watch Later notes: literal WL path, details-unavailable note, API failure surfacing, readiness probe.

T3-1 (youtube-manager-bugfixes): watch_later zero-candidates note.
"""

import email.message
import urllib.error

import youtube_manager
from youtube_manager import ReauthNeeded, Tools

from .conftest import sample_candidates


def _playlist_item(video_id: str) -> dict:
    return {"contentDetails": {"videoId": video_id}}


def _detail(video_id: str) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Detail title {video_id}",
            "channelId": f"ch-{video_id}",
            "channelTitle": f"Detail channel {video_id}",
            "description": f"Detail description {video_id}",
            "tags": [f"tag-{video_id}"],
            "viewCount": "100",
            "publishedAt": "2026-09-01T12:00:00Z",
        },
        "contentDetails": {"duration": "PT2M35S"},
    }


def _wl_api_fake(monkeypatch, *, playlist_items: list[dict], video_details: dict):
    """Route _data_api_request for the watch_later path (literal WL); record (method, params) calls."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if method == "channels.list":
            raise AssertionError("channels.list must never be called on the watch_later path")
        if method == "playlistItems.list":
            return {"items": playlist_items}
        if method == "videos.list":
            wanted = params["ids"].split(",")
            return {"items": [video_details[i] for i in wanted if i in video_details]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


def _clear_oauth(tools):
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


class TestWatchLaterNotes:
    # @unit
    # Scenario: T9-1 S4 a Watch Later API failure surfaces through gather_candidates
    #   Given OAuth is configured
    #   And playlistItems.list raises an HTTP 404 error for playlistId "WL"
    #   When gather_candidates runs with sources="watch_later"
    #   Then the result is exactly "Error: watch_later: HTTP 404: Not Found"
    async def test_watch_later_api_failure_404(self, tools, monkeypatch):
        def api(valves, method, params):
            if method == "channels.list":
                raise AssertionError("channels.list must never be called on the watch_later path")
            if method == "playlistItems.list":
                assert params == {"part": "contentDetails", "playlistId": "WL", "maxResults": "20"}
                raise urllib.error.HTTPError(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    404,
                    "Not Found",
                    email.message.Message(),
                    None,
                )
            raise AssertionError(f"unexpected API method {method}")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        payload = await tools.gather_candidates(sources="watch_later")

        assert payload == "Error: watch_later: HTTP 404: Not Found"

    # @unit
    # Scenario: Q4 Watch Later skip note uses colon format when details unavailable
    #   Given a watch_later playlist whose items are absent from the videos.list details response
    #   When gather_candidates runs with watch_later
    #   Then the output contains "watch_later skipped: details unavailable"
    #   And the output does not contain "watch_later skipped ("
    async def test_items_without_details_emits_note(self, tools, monkeypatch):
        _wl_api_fake(
            monkeypatch,
            playlist_items=[_playlist_item("v1"), _playlist_item("v2")],
            video_details={},
        )

        payload = await tools.gather_candidates(sources="watch_later")

        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert "watch_later skipped: details unavailable" in payload
        assert "watch_later skipped (" not in payload

    # @unit
    # Scenario: T0-3.3 happy path: available watch_later → no note (regression)
    #   Given a watch_later source with N resolvable videos
    #   When gather_candidates runs with watch_later
    #   Then N candidates are returned
    #   And no "watch_later skipped" line is emitted
    # Scenario: T9-1 S1 Watch Later reads the canonical WL playlist directly
    #   Given OAuth is configured
    #   And the Data API seam serves playlistItems.list for playlistId "WL"
    #   When _fetch_watch_later runs
    #   Then playlistItems.list is called with part "contentDetails", playlistId "WL", and maxResults str(max_per_source)
    #     And channels.list is never called
    #     And the returned candidates are labelled "watch_later"
    async def test_happy_path_no_note(self, tools, monkeypatch):
        calls = _wl_api_fake(
            monkeypatch,
            playlist_items=[_playlist_item("v1"), _playlist_item("v2")],
            video_details={"v1": _detail("v1"), "v2": _detail("v2")},
        )

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls[0] == ("playlistItems.list", {"part": "contentDetails", "playlistId": "WL", "maxResults": "20"})
        assert not any(method == "channels.list" for method, _ in calls)
        assert "=== Candidates (2) ===" in payload
        assert "Detail title v1" in payload
        assert "Detail title v2" in payload
        assert "watch_later skipped" not in payload

    # @unit
    # Scenario: T0-3.4 OAuth-unset note preserved (regression)
    #   Given OAuth not configured
    #   When gather_candidates runs with watch_later
    #   Then the existing OAuth-not-configured skip note is still emitted
    async def test_oauth_unset_note_preserved(self, tools, monkeypatch):
        _clear_oauth(tools)
        calls: list[str] = []

        def api(valves, method, params):
            calls.append(method)
            raise AssertionError("no Data API I/O for a skipped watch_later")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        payload = await tools.gather_candidates(sources="watch_later")

        assert "watch_later skipped: OAuth not configured" in payload
        assert "=== Candidates (0) ===" in payload
        assert calls == []


class TestWatchLaterProbe:
    """T9-1: Tools._watch_later_probe readiness probe (literal WL; no candidates, no notes)."""

    # @unit
    # Scenario: T9-1 S2 check_setup is READY only when the WL probe succeeds
    #   Given the OAuth fields are complete and the token status is valid
    #   And Tools._watch_later_probe returns "ok (playlist checked)"
    #   When check_setup runs
    #   Then the result lines are exactly "search: ok", "subscriptions: ok", "watch_later: ok (playlist checked)", "READY"
    async def test_probe_success_reports_ok(self, tools, monkeypatch):
        calls: list[tuple[str, dict]] = []

        def api(valves, method, params):
            calls.append((method, dict(params)))
            if method == "channels.list":
                raise AssertionError("channels.list must never be called on the watch_later path")
            if method == "playlistItems.list":
                return {"items": []}
            raise AssertionError(f"unexpected API method {method}")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        assert await tools._watch_later_probe() == "ok (playlist checked)"
        assert calls == [("playlistItems.list", {"part": "contentDetails", "playlistId": "WL", "maxResults": "1"})]

    # @unit
    # Scenario: T9-1 S3 check_setup is NOT READY when the WL probe fails
    #   Given the OAuth fields are complete and the token status is valid
    #   And Tools._watch_later_probe returns "CHECK FAILED - reauth"
    #   When check_setup runs
    #   Then the watch_later line is exactly "watch_later: CHECK FAILED - reauth"
    #   And the final line is exactly "NOT READY"
    async def test_probe_reauth_reports_check_failed(self, tools, monkeypatch):
        def api(valves, method, params):
            if method == "channels.list":
                raise AssertionError("channels.list must never be called on the watch_later path")
            if method == "playlistItems.list":
                raise ReauthNeeded("Google credential rejected by the Data API")
            raise AssertionError(f"unexpected API method {method}")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        assert await tools._watch_later_probe() == "CHECK FAILED - reauth"


class TestWatchLaterZeroNote:
    """T3-1: an empty-but-valid watch_later playlist carries the zero note (distinguishable from not-found)."""

    # @unit
    # Scenario: T3-1.S1 — standalone: an empty-but-valid watch_later playlist carries the zero note (not a bare zero-candidate payload)
    # Given OAuth is configured and the Data API serves an empty playlistItems.list for playlistId "WL" (0 items)
    # When the agent calls gather_candidates with sources="watch_later"
    # Then the result starts with "=== Candidates (0) ===" and lists "Candidate IDs: (none)"
    # And the result carries the note "watch_later: playlist ok, 0 items"
    async def test_empty_watch_later_carries_zero_note(self, tools, monkeypatch):
        _wl_api_fake(monkeypatch, playlist_items=[], video_details={})

        payload = await tools.gather_candidates(sources="watch_later")

        assert payload.startswith("=== Candidates (0) ===")
        assert "Candidate IDs: (none)" in payload
        assert "watch_later: playlist ok, 0 items" in payload

    # @unit
    # Scenario: T3-1.S2 — multi-source: an empty-but-valid watch_later playlist still carries the zero note alongside a healthy source's results
    # Given gather is requested with sources="watch_later,subscriptions"
    # And the Data API serves an empty playlistItems.list for playlistId "WL" (0 items) while the subscriptions source completes and returns one candidate
    # When the agent calls gather_candidates
    # Then the result is NOT an error (does not start with "Error:")
    # And the result lists the subscriptions candidate
    # And the result carries the note "watch_later: playlist ok, 0 items"
    async def test_empty_watch_later_multi_source_carries_zero_note(self, tools, monkeypatch):
        _wl_api_fake(monkeypatch, playlist_items=[], video_details={})
        monkeypatch.setattr(Tools, "_fetch_subscriptions", lambda self, max_per_source, notes: sample_candidates(1))

        payload = await tools.gather_candidates(sources="watch_later,subscriptions")

        assert not payload.startswith("Error:")
        assert "Sample video 0" in payload
        assert "watch_later: playlist ok, 0 items" in payload

    # @unit
    # Scenario: T3-1.S3 — regression guard: a NON-empty watch_later playlist does NOT carry the zero note (and no "watch_later skipped" note)
    # Given OAuth is configured and the Data API serves a watch_later playlist with 2 resolvable items (v1, v2)
    # When the agent calls gather_candidates with sources="watch_later"
    # Then the result starts with "=== Candidates (2) ==="
    # And the result does NOT contain "watch_later: playlist ok, 0 items"
    # And the result does NOT contain "watch_later skipped"
    async def test_non_empty_watch_later_carries_no_zero_note(self, tools, monkeypatch):
        _wl_api_fake(
            monkeypatch,
            playlist_items=[_playlist_item("v1"), _playlist_item("v2")],
            video_details={"v1": _detail("v1"), "v2": _detail("v2")},
        )

        payload = await tools.gather_candidates(sources="watch_later")

        assert "=== Candidates (2) ===" in payload
        assert "watch_later: playlist ok, 0 items" not in payload
        assert "watch_later skipped" not in payload

    # @unit
    # Scenario: T3-1.S4 — digest-path safety: the zero note is None-safe (notes=None on the digest path must not crash and must not append)
    # Given the watch_later Data API serves an empty playlistItems.list (0 items)
    # When _fetch_watch_later runs with notes omitted (notes defaults to None, as the digest path calls it)
    # Then 0 candidates are returned and no exception is raised
    async def test_zero_note_none_safe_digest_path(self, tools, monkeypatch):
        _wl_api_fake(monkeypatch, playlist_items=[], video_details={})

        candidates = tools._fetch_watch_later(20)

        assert candidates == []
