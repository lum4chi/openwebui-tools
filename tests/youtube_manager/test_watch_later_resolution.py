"""T1-2-C: Watch Later source resolution from the user-maintained valve-named playlist (no legacy "WL" alias).

gather_candidates(watch_later) resolves the watch_later_playlist_title valve by exact trimmed title match against
playlists.list (first match wins on collision). NOT FOUND / lookup error -> 0 candidates + a None-safe diagnostic
note, and NO playlistItems.list call with the legacy "WL" alias.
"""

import email.message
import urllib.error

from .conftest import api_fake, guard_urlopen, item_row, playlist_row, video_detail


def _no_match_page() -> dict:
    """A playlists.list page with no row whose trimmed title equals the valve default."""
    return {"items": [playlist_row("PLother", "Some other playlist")]}


def _http_503() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://www.googleapis.com/youtube/v3/playlists", 503, "Service Unavailable", email.message.Message(), None
    )


class TestWatchLaterValveResolution:
    """Resolution of the valve-named Watch Later playlist before any playlistItems.list call."""

    # @unit
    # Scenario T1-2-C-S1 (unit): valve-resolved user playlist is the Watch Later source
    #   Given a Tools valve watch_later_playlist_title equal to "Watch Later"
    #   And a mocked playlists.list response containing one playlist titled "Watch Later" with id "PLuser"
    #   And a mocked playlistItems.list response for playlistId "PLuser" containing one saved video
    #   When gather_candidates is called with sources "watch_later"
    #   Then playlists.list is used to resolve the valve title
    #   And playlistItems.list is called with playlistId "PLuser"
    #   And no playlistItems.list call uses playlistId "WL"
    #   And the candidates include the saved video
    #   # provenance: user acceptance verbatim 1 and 2
    # @unit
    # Scenario T1-4-S1 (unit): the watch-later step surfaces the user's single saved video from a real-shaped videos.list response
    #   Given the valve title resolves a watch-later playlist holding exactly one item with video id "saved-1"
    #   And the mocked videos.list response for that id is one item with snippet title/channel and contentDetails.duration (real shape via the video_detail fixture helper)
    #   When gather_candidates is called with sources "watch_later"
    #   Then no exception escapes gather_candidates
    #   And watch_later contributes exactly one candidate for saved-1
    # @unit
    # Scenario T1-4-S2 (unit): the videos.list request uses the real API parameter name id
    #   Given a watch-later source with one saved video
    #   When gather_candidates is called with sources "watch_later"
    #   Then the videos.list call is made with parameter id equal to the comma-joined video ids
    #   And no videos.list call carries an ids parameter
    async def test_valve_resolved_playlist_is_watch_later_source(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"PLuser": [{"items": [item_row("item-1", "saved-1")]}]},
            playlist_pages=[{"items": [playlist_row("PLuser", "Watch Later")]}],
            videos={"saved-1": video_detail("saved-1", duration="PT1M30S", title="Saved video")},
        )
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [
            ("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50}),
            ("playlistItems.list", {"part": "contentDetails", "playlistId": "PLuser", "maxResults": "20"}),
            ("videos.list", {"part": "snippet,contentDetails", "id": "saved-1"}),
        ]
        assert "=== Candidates (1) ===" in payload
        assert "Candidate IDs: saved-1" in payload

    # @unit
    # Scenario T1-4-S4 (unit): a malformed video in a watch-later batch is skipped, counted and reported without aborting the batch
    #   Given a watch-later batch holding one healthy video and one malformed item without a usable snippet
    #   When gather_candidates is called with sources "watch_later"
    #   Then no exception escapes gather_candidates
    #   And the healthy video is still returned as a candidate
    #   And the notes report exactly 1 skipped video with the malformed id and a reason
    async def test_malformed_watch_later_item_skipped_counted_reported(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={"PLuser": [{"items": [item_row("item-1", "saved-1"), item_row("item-2", "bad-1")]}]},
            playlist_pages=[{"items": [playlist_row("PLuser", "Watch Later")]}],
            videos={
                "saved-1": video_detail("saved-1", duration="PT1M30S", title="Saved video"),
                "bad-1": video_detail("bad-1"),
            },
        )
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert "=== Candidates (1) ===" in payload
        assert "Candidate IDs: saved-1" in payload
        skip_notes = [line for line in payload.splitlines() if line.startswith("watch_later skipped 1 video(s):")]
        assert skip_notes == ["watch_later skipped 1 video(s): bad-1 (ValueError)"]

    # @unit
    # Scenario T1-2-C-S2 (unit): absent valve playlist returns zero candidates without a WL API call
    #   Given a Tools valve watch_later_playlist_title equal to "Watch Later"
    #   And a mocked playlists.list response containing no playlist whose trimmed title equals "Watch Later"
    #   When gather_candidates is called with sources "watch_later"
    #   Then no playlistItems.list call is made
    #   And no playlistItems.list call uses playlistId "WL"
    #   And no candidates are returned
    #   And an internal diagnostic note records the missing playlist
    #   And no exception escapes gather_candidates
    #   # provenance: user acceptance verbatim 1 + ratified O-1/O-2
    async def test_absent_valve_playlist_returns_zero_candidates_without_wl_call(self, tools, monkeypatch):
        calls = api_fake(monkeypatch, pages={}, playlist_pages=[_no_match_page()])
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50})]
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert 'watch_later: no playlist titled "Watch Later" found' in payload

    # @unit
    # Scenario T1-2-C-S3 (unit): trimmed valve title matches trimmed playlist title
    #   Given a Tools valve watch_later_playlist_title equal to "  Watch Later  "
    #   And a mocked playlists.list response containing one playlist titled "Watch Later" with id "PLuser"
    #   And a mocked playlistItems.list response for playlistId "PLuser" containing one saved video
    #   When gather_candidates is called with sources "watch_later"
    #   Then playlistItems.list is called with playlistId "PLuser"
    #   And no playlistItems.list call uses playlistId "WL"
    #   # provenance: user instruction "exact title match (trimmed)"
    async def test_trimmed_valve_title_matches_trimmed_playlist_title(self, tools, monkeypatch):
        tools.valves.watch_later_playlist_title = "  Watch Later  "
        calls = api_fake(
            monkeypatch,
            pages={"PLuser": [{"items": [item_row("item-1", "saved-1")]}]},
            playlist_pages=[{"items": [playlist_row("PLuser", "Watch Later")]}],
            videos={"saved-1": video_detail("saved-1", title="Saved video")},
        )
        guard_urlopen(monkeypatch)

        await tools.gather_candidates(sources="watch_later")

        items = [params for method, params in calls if method == "playlistItems.list"]
        assert items == [{"part": "contentDetails", "playlistId": "PLuser", "maxResults": "20"}]
        assert all(params.get("playlistId") != "WL" for params in items)

    # @unit
    # Scenario T1-2-C-S4 (unit): title collision uses first playlists.list match deterministically
    #   Given a Tools valve watch_later_playlist_title equal to "Watch Later"
    #   And a mocked playlists.list response containing two playlists whose trimmed title equals "Watch Later"
    #     in order "PLfirst" then "PLsecond"
    #   When gather_candidates is called with sources "watch_later"
    #   Then playlistItems.list is called with playlistId "PLfirst"
    #   And playlistItems.list is not called with playlistId "PLsecond"
    #   And no playlistItems.list call uses playlistId "WL"
    #   # provenance: user instruction "Title-collision edge: define deterministic behavior (first match)"
    async def test_title_collision_uses_first_match(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"PLfirst": [{"items": [item_row("item-1", "saved-1")]}]},
            playlist_pages=[
                {"items": [playlist_row("PLfirst", "Watch Later"), playlist_row("PLsecond", "Watch Later")]}
            ],
            videos={"saved-1": video_detail("saved-1", title="Saved video")},
        )
        guard_urlopen(monkeypatch)

        await tools.gather_candidates(sources="watch_later")

        items = [params for method, params in calls if method == "playlistItems.list"]
        assert items == [{"part": "contentDetails", "playlistId": "PLfirst", "maxResults": "20"}]
        assert all(params.get("playlistId") not in ("WL", "PLsecond") for params in items)

    # @unit
    # Scenario T1-2-C-S7 (unit): playlist lookup error returns zero candidates without a WL API call
    #   Given a Tools valve watch_later_playlist_title equal to "Watch Later"
    #   And a mocked playlists.list resolution that raises an API error
    #   When gather_candidates is called with sources "watch_later"
    #   Then no playlistItems.list call is made
    #   And no playlistItems.list call uses playlistId "WL"
    #   And no candidates are returned
    #   And an internal diagnostic note records the lookup error
    #   And no exception escapes gather_candidates
    #   # provenance: ratified O-2 + no "WL" API call
    async def test_lookup_error_returns_zero_candidates_without_wl_call(self, tools, monkeypatch):
        calls = api_fake(monkeypatch, pages={}, raise_for={"playlists.list": _http_503()})
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50})]
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert 'watch_later: "Watch Later" title lookup failed (service unavailable - retry later)' in payload
