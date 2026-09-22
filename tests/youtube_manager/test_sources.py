"""T1 source routing: watch_later enrichment (T1-3), search + invalid sources (T1-4), watch_later OAuth guard (T1-13)."""

import pytest

import youtube_manager
from youtube_manager import SOURCES


def _entry(video_id):
    return {
        "id": video_id,
        "title": f"Feed title {video_id}",
        "uploader": f"Feed uploader {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 120,
        "view_count": 500,
        "upload_date": "20260910",
        "description": f"Feed description {video_id}",
        "tags": ["feed-tag"],
    }


def _detail(
    video_id,
    view_count: int | None = None,
    duration: str | None = "PT2M35S",
    published_at: str | None = "2026-09-01T12:00:00Z",
):
    snippet = {
        "title": f"Detail title {video_id}",
        "channelId": f"ch-{video_id}",
        "channelTitle": f"Detail channel {video_id}",
        "description": f"Detail description {video_id}",
        "tags": [f"tag-{video_id}"],
    }
    if view_count is not None:
        snippet["viewCount"] = str(view_count)
    if published_at is not None:
        snippet["publishedAt"] = published_at
    content = {}
    if duration is not None:
        content["duration"] = duration
    return {"id": video_id, "snippet": snippet, "contentDetails": content}


def _playlist_item(video_id):
    return {"contentDetails": {"videoId": video_id}} if video_id else {"id": "item-without-video"}


def _api_fake(details, playlist_items, playlist_id="WL-1"):
    """Route _data_api_request by method; record calls as (method, params) pairs."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if method == "channels.list":
            channel: dict = {"id": "me"}
            if playlist_id is not None:
                channel["contentDetails"] = {"relatedPlaylists": {"watchLater": playlist_id}}
            return {"items": [channel]}
        if method == "playlistItems.list":
            return {"items": playlist_items}
        if method == "videos.list":
            return {"items": [details[i] for i in params["ids"].split(",")]}
        raise AssertionError(f"unexpected API method {method}")

    return fake, calls


def _ytdlp_fake(monkeypatch, flat: dict[str, list[str]], full: dict[str, dict]):
    """Patch _ytdlp_extract: flat listings serve id-only rows, watch URLs serve full entries."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        if url in flat:
            return {"entries": [{"id": video_id} for video_id in flat[url]]}
        return full[url]

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _ids_line(payload):
    return next(line for line in payload.splitlines() if line.startswith("Candidate IDs:"))


def _clear_oauth(tools):
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


class TestWatchLater:
    """T1-3 watch_later merges with Data API enrichment."""

    # @unit
    # Scenario: T1-3 watch later source
    #   Given sources includes watch_later and the Data API seam returns playlist items
    #   When gather_candidates runs
    #   Then watch-later items appear as candidates
    #   And their duration/views come from the batched videos enrichment
    #   And items already present from other sources are deduped, not duplicated
    @pytest.mark.parametrize(
        ("playlist_ids", "expected_ids", "search_overlap", "expected_video_calls", "playlist_id", "detail_overrides"),
        [
            (
                # wl-a also arrives via the search source -> deduped, not duplicated;
                # one playlist item without a videoId is skipped; wl-c detail has no
                # duration / publishedAt / viewCount keys (missing-key branches)
                ["wl-a", None, "wl-b", "wl-c"],
                ["wl-a", "wl-b", "wl-c"],
                True,
                1,
                "WL-1",
                {"wl-c": _detail("wl-c", duration=None, published_at=None)},
            ),
            (
                # 51 playlist items -> videos enrichment is batched (50 ids/call);
                # wl-25 carries a malformed ISO-8601 duration (regex-miss branch)
                [f"wl-{i:02d}" for i in range(51)],
                [f"wl-{i:02d}" for i in range(51)],
                False,
                2,
                "WL-1",
                {"wl-25": _detail("wl-25", duration="P9Y")},
            ),
            (
                # channel has no relatedPlaylists -> watch_later yields nothing,
                # no playlistItems/videos calls
                [],
                [],
                False,
                0,
                None,
                {},
            ),
        ],
        ids=["overlap_and_enrich", "batched_enrichment_order_preserved", "no_watch_later_playlist"],
    )
    async def test_merge_and_enrich(
        self,
        tools,
        monkeypatch,
        playlist_ids,
        expected_ids,
        search_overlap,
        expected_video_calls,
        playlist_id,
        detail_overrides,
    ):
        details = {vid: _detail(vid, view_count=777 if vid == "wl-b" else None) for vid in playlist_ids if vid}
        details.update(detail_overrides)
        api_fake, calls = _api_fake(details, [_playlist_item(vid) for vid in playlist_ids], playlist_id=playlist_id)
        flat = {"ytsearch51:rust async": ["wl-a"] if search_overlap else []}
        full = {"https://www.youtube.com/watch?v=wl-a": _entry("wl-a")} if search_overlap else {}
        ytdlp_calls = _ytdlp_fake(monkeypatch, flat, full)
        monkeypatch.setattr(youtube_manager, "_data_api_request", api_fake)

        payload = await tools.gather_candidates(
            sources="search,watch_later", max_per_source=51, search_query="rust async"
        )

        expected_line = "Candidate IDs: " + ", ".join(expected_ids) if expected_ids else "Candidate IDs: (none)"
        assert _ids_line(payload) == expected_line
        video_calls = [params for method, params in calls if method == "videos.list"]
        assert len(video_calls) == expected_video_calls
        if expected_video_calls == 2:
            assert video_calls[0]["ids"] == ",".join(expected_ids[:50])
            assert video_calls[1]["ids"] == expected_ids[50]
        if playlist_id is None:
            assert calls == [("channels.list", {"part": "contentDetails", "mine": "true"})]
        for method, params in calls:
            if method == "playlistItems.list":
                assert params["playlistId"] == "WL-1"
                assert params["maxResults"] == "51"
        if search_overlap:
            # first-seen (search) candidate wins the dedupe; watch-later copy dropped
            assert "Feed title wl-a" in payload
            assert "Detail title wl-a" not in payload
            # watch-later-only item enriched via the batched videos endpoint
            assert "Detail title wl-b" in payload
            assert "Detail channel wl-b" in payload
            assert "2:35" in payload  # PT2M35S rendered
            assert "777 views" in payload
            # wl-c: no duration / publishedAt / viewCount keys -> defensive render
            assert "duration unknown" in payload
            assert "date unknown" in payload
        elif expected_video_calls:
            assert "Detail title wl-00" in payload
            assert "Detail title wl-50" in payload
            assert "duration unknown" in payload  # wl-25 malformed ISO-8601 duration
        if search_overlap:
            # flat listing call first, then the per-video watch-URL fetch (B1)
            assert ytdlp_calls == ["ytsearch51:rust async", "https://www.youtube.com/watch?v=wl-a"]
        else:
            assert ytdlp_calls == ["ytsearch51:rust async"]


class TestSourcesArg:
    """T1-4 search needs search_query; unknown/empty sources rejected. T1-13 watch_later OAuth guard."""

    # @unit
    # Scenario: T1-4 search and invalid sources
    #   Given sources "search" and search_query "rust async"
    #   When gather_candidates runs
    #   Then the search results appear as a candidate source
    #   And when sources is "search" but search_query is empty
    #   Then the result is an Error string saying search needs search_query
    #   And no I/O seam is called for the invalid request
    @pytest.mark.parametrize(
        ("search_query", "expect_error"),
        [("rust async", False), ("", True), ("   ", True)],
        ids=["query_ok", "empty_query", "whitespace_query"],
    )
    async def test_search_needs_query(self, tools, monkeypatch, search_query, expect_error):
        ytdlp_calls = _ytdlp_fake(
            monkeypatch,
            {"ytsearch5:rust async": ["srch-1"]},
            {"https://www.youtube.com/watch?v=srch-1": _entry("srch-1")},
        )

        payload = await tools.gather_candidates(sources="search", max_per_source=5, search_query=search_query)

        if expect_error:
            assert payload.startswith("Error:")
            assert "search_query" in payload
            assert ytdlp_calls == []  # no I/O for the invalid request
        else:
            assert "srch-1" in payload  # search results appear as a candidate source
            assert ytdlp_calls == ["ytsearch5:rust async", "https://www.youtube.com/watch?v=srch-1"]

    # Scenario T1-4 (edge): unknown name / empty / whitespace -> error naming valid sources, no I/O
    async def test_unknown_source_error(self, tools, monkeypatch):
        ytdlp_calls = _ytdlp_fake(monkeypatch, {}, {})
        api_calls: list[str] = []

        def api(valves, method, params):
            api_calls.append(method)
            raise AssertionError("no I/O seam may be called for the invalid request")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        for bad in ("trending", "watch_later,trending", "", "   "):
            payload = await tools.gather_candidates(sources=bad)
            assert payload.startswith("Error:")
            assert "trending" in payload or bad in ("", "   ")
            for name in SOURCES:
                assert name in payload  # the error names the valid source names (watch_later, search)
        assert ytdlp_calls == []
        assert api_calls == []

    # @unit
    # Scenario: T1-13 watch_later guard
    #   Given sources "watch_later,search" with search_query set and OAuth NOT configured
    #   When gather_candidates runs
    #   Then watch_later is skipped with a note (not an error)
    #   And the search results are still returned
    #   And no exception propagates
    async def test_watch_later_guard(self, tools, monkeypatch):
        _clear_oauth(tools)
        ytdlp_calls = _ytdlp_fake(
            monkeypatch,
            {"ytsearch5:rust async": ["srch-1"]},
            {"https://www.youtube.com/watch?v=srch-1": _entry("srch-1")},
        )
        api_calls: list[str] = []

        def api(valves, method, params):
            api_calls.append(method)
            raise AssertionError("no Data API I/O for a skipped watch_later")

        monkeypatch.setattr(youtube_manager, "_data_api_request", api)

        payload = await tools.gather_candidates(
            sources="watch_later,search", max_per_source=5, search_query="rust async"
        )

        assert not payload.startswith("Error:")
        assert "srch-1" in payload  # search results are still returned
        assert "watch_later skipped" in payload  # skipped with a note, not an error
        assert ytdlp_calls == ["ytsearch5:rust async", "https://www.youtube.com/watch?v=srch-1"]
        assert api_calls == []
