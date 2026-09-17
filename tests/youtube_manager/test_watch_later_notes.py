"""T0-3 watch_later skip notes: make "empty" (no playlist / no details) distinguishable from a real result."""

import youtube_manager


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


def _wl_api_fake(monkeypatch, *, watch_later_id: str | None, playlist_items: list[dict], video_details: dict):
    """Route _data_api_request for the watch_later path; record (method, params) calls."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if method == "channels.list":
            channel: dict = {"id": "me"}
            if watch_later_id is not None:
                channel["contentDetails"] = {"relatedPlaylists": {"watchLater": watch_later_id}}
            return {"items": [channel]}
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
    # Scenario: T0-3.1 no resolved playlist id → skip note
    #   Given an authenticated watch_later source whose playlist id cannot be resolved
    #   When gather_candidates runs with watch_later
    #   Then 0 candidates are returned
    #   And the output contains "watch_later skipped (no playlist resolved)"
    async def test_no_playlist_resolved_emits_note(self, tools, monkeypatch):
        _wl_api_fake(monkeypatch, watch_later_id=None, playlist_items=[], video_details={})

        payload = await tools.gather_candidates(sources="watch_later")

        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert "watch_later skipped (no playlist resolved)" in payload

    # @unit
    # Scenario: T0-3.2 items without details → skip note
    #   Given a watch_later playlist whose items are absent from the videos.list details response
    #   When gather_candidates runs with watch_later
    #   Then 0 candidates are returned
    #   And the output contains "watch_later skipped (details unavailable)"
    async def test_items_without_details_emits_note(self, tools, monkeypatch):
        _wl_api_fake(
            monkeypatch,
            watch_later_id="WL-1",
            playlist_items=[_playlist_item("v1"), _playlist_item("v2")],
            video_details={},
        )

        payload = await tools.gather_candidates(sources="watch_later")

        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert "watch_later skipped (details unavailable)" in payload

    # @unit
    # Scenario: T0-3.3 happy path: available watch_later → no note (regression)
    #   Given a watch_later source with N resolvable videos
    #   When gather_candidates runs with watch_later
    #   Then N candidates are returned
    #   And no "watch_later skipped" line is emitted
    async def test_happy_path_no_note(self, tools, monkeypatch):
        _wl_api_fake(
            monkeypatch,
            watch_later_id="WL-1",
            playlist_items=[_playlist_item("v1"), _playlist_item("v2")],
            video_details={"v1": _detail("v1"), "v2": _detail("v2")},
        )

        payload = await tools.gather_candidates(sources="watch_later")

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
