"""T1 source routing: watch_later enrichment (T1-3), search opt-in + invalid sources (T1-4)."""

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
                channel["relatedPlaylists"] = {"watchLaterPlaylistId": playlist_id}
            return {"items": [channel]}
        if method == "playlistItems.list":
            return {"items": playlist_items}
        if method == "videos.list":
            return {"items": [details[i] for i in params["ids"].split(",")]}
        raise AssertionError(f"unexpected API method {method}")

    return fake, calls


def _details(vids, **specials):
    out = {vid: _detail(vid, view_count=777 if vid == "wl-b" else None) for vid in vids}
    out.update(specials)
    return out


def _ytdlp_fake(monkeypatch, by_url):
    """Patch _ytdlp_extract to serve entries per URL; return the called-URL list."""
    calls: list[str] = []

    def fake(url, valves, extra=None):
        calls.append(url)
        return {"entries": by_url.get(url, [])}

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _ids_line(payload):
    return next(line for line in payload.splitlines() if line.startswith("Candidate IDs:"))


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
        ("playlist_ids", "expected_ids", "rec_overlap", "expected_video_calls", "playlist_id", "detail_overrides"),
        [
            (
                # wl-a also arrives via the recommended feed -> deduped, not duplicated;
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
        rec_overlap,
        expected_video_calls,
        playlist_id,
        detail_overrides,
    ):
        details = {vid: _detail(vid, view_count=777 if vid == "wl-b" else None) for vid in playlist_ids if vid}
        details.update(detail_overrides)
        api_fake, calls = _api_fake(details, [_playlist_item(vid) for vid in playlist_ids], playlist_id=playlist_id)
        ytdlp_by_url = {":ytrec": [_entry("wl-a")]} if rec_overlap else {}
        ytdlp_calls = _ytdlp_fake(monkeypatch, ytdlp_by_url)
        monkeypatch.setattr(youtube_manager, "_data_api_request", api_fake)

        payload = await tools.gather_candidates(sources="recommended,watch_later", max_per_source=51)

        expected_line = "Candidate IDs: " + ", ".join(expected_ids) if expected_ids else "Candidate IDs: (none)"
        assert _ids_line(payload) == expected_line
        video_calls = [params for method, params in calls if method == "videos.list"]
        assert len(video_calls) == expected_video_calls
        if expected_video_calls == 2:
            assert video_calls[0]["ids"] == ",".join(expected_ids[:50])
            assert video_calls[1]["ids"] == expected_ids[50]
        if playlist_id is None:
            assert calls == [("channels.list", {"part": "snippet,relatedPlaylists", "mine": "true"})]
        for method, params in calls:
            if method == "playlistItems.list":
                assert params["playlistId"] == "WL-1"
                assert params["maxResults"] == "51"
        if rec_overlap:
            # first-seen (recommended) candidate wins the dedupe; watch-later copy dropped
            assert "Feed title wl-a" in payload
            assert "Detail title wl-a" not in payload
            assert payload.count("wl-a") == 3  # title + channel on the candidate line + one Candidate IDs entry
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
        assert ytdlp_calls == [":ytrec"]


class TestSourcesArg:
    """T1-4 search opt-in via search_query; unknown source names rejected."""

    # @unit
    # Scenario: T1-4 search and invalid sources
    #   Given search_query "rust async" and sources "recommended"
    #   When gather_candidates runs
    #   Then search results appear as a candidate source
    #   And when sources contains an unknown name (e.g. "trending")
    #   Then the result is an Error string naming the valid source names
    #   And no I/O seam is called for the invalid request
    @pytest.mark.parametrize(
        ("sources", "search_query", "expect_search_url"),
        [
            ("recommended", "rust async", True),  # search auto-included via search_query
            ("recommended,search", "rust async", True),  # explicit search source
            ("recommended,search", "", False),  # search listed but no query -> yields nothing
        ],
        ids=["auto_include", "explicit_search", "no_query_no_search"],
    )
    async def test_search_included(self, tools, monkeypatch, sources, search_query, expect_search_url):
        ytdlp_calls = _ytdlp_fake(
            monkeypatch,
            {
                ":ytrec": [_entry("rec-1")],
                "ytsearch5:rust async": [_entry("srch-1")],
            },
        )

        payload = await tools.gather_candidates(sources=sources, max_per_source=5, search_query=search_query)

        search_urls = [url for url in ytdlp_calls if "ytsearch" in url]
        assert bool(search_urls) is expect_search_url
        if expect_search_url:
            assert search_urls == ["ytsearch5:rust async"]
            assert "srch-1" in payload  # search results appear as a candidate source
            assert "rec-1" in payload
        else:
            assert "srch-1" not in payload
            assert "rec-1" in payload

    # Scenario T1-4 (edge): unknown source name -> error without I/O
    async def test_unknown_source_error(self, tools, monkeypatch):
        def boom(url, valves, extra=None):
            raise AssertionError("no I/O seam may be called for the invalid request")

        _ytdlp_fake(monkeypatch, {})
        monkeypatch.setattr(youtube_manager, "_data_api_request", boom)

        payload = await tools.gather_candidates(sources="recommended,trending")

        assert payload.startswith("Error: ")
        assert "trending" in payload
        for name in SOURCES:
            assert name in payload  # the error names the valid source names
