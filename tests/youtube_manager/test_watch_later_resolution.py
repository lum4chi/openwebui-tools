"""Watch Later resolution: the real Watch Later playlist id is resolved by exact title match before the legacy "WL" alias.

T1-2 (youtube-live-credential-fix): gather_candidates(watch_later) returns the items the user actually saved.
"""

import email.message
import urllib.error

from .conftest import api_fake, guard_urlopen, item_row, playlist_row, video_detail


class TestResolvedWatchLaterId:
    # @unit
    # Scenario: T1-2-S1 (unit): resolved Watch Later id is used for candidate items
    #   Given a mocked YouTube API where playlists.list returns a playlist titled "Watch Later" with id "PLwl123"
    #   And playlistItems.list for playlistId "PLwl123" returns one saved video item
    #   When gather_candidates is called with sources "watch_later"
    #   Then playlistItems.list is called with playlistId "PLwl123" and not "WL"
    #   And the candidate includes the saved video
    #   And no channels.list call is made on the watch_later path
    #   And no zero-item watch_later note is emitted
    async def test_resolved_id_used_not_wl_alias(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"PLwl123": [{"items": [item_row("item-1", "saved-1")]}]},
            playlist_pages=[{"items": [playlist_row("PLwl123", "Watch Later")]}],
            videos={"saved-1": video_detail("saved-1", title="Saved video")},
        )
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [
            ("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50}),
            ("playlistItems.list", {"part": "contentDetails", "playlistId": "PLwl123", "maxResults": "20"}),
            ("videos.list", {"part": "snippet,contentDetails", "ids": "saved-1"}),
        ]
        assert "=== Candidates (1) ===" in payload
        assert "Candidate IDs: saved-1" in payload
        assert "Saved video" in payload
        assert "watch_later: playlist ok, 0 items" not in payload


class TestUnresolvedWatchLaterFallback:
    # @unit
    # Scenario: T1-2-S2 (unit): unresolved Watch Later title falls back to legacy WL
    #   Given a mocked YouTube API where playlists.list returns no playlist titled "Watch Later" or "View later"
    #   And playlistItems.list for playlistId "WL" returns no items
    #   When gather_candidates is called with sources "watch_later"
    #   Then playlistItems.list is called with playlistId "WL"
    #   And no candidate is returned
    #   And a diagnostic note records the unresolved Watch Later title lookup
    #   And the existing zero-item watch_later note is retained
    async def test_unresolved_falls_back_to_wl(self, tools, monkeypatch):
        no_match = {"items": [playlist_row("PL-mine", "Not Watch Later")]}
        calls = api_fake(
            monkeypatch,
            pages={"WL": [{"items": []}]},
            playlist_pages=[no_match, no_match],
        )
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [
            ("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50}),
            ("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50}),
            ("playlistItems.list", {"part": "contentDetails", "playlistId": "WL", "maxResults": "20"}),
        ]
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert 'watch_later: no "Watch Later" or "View later" playlist found; using legacy "WL" alias' in payload
        assert "watch_later: playlist ok, 0 items" in payload


class TestFailedWatchLaterLookup:
    # @unit
    # Scenario: T1-2-S3 (unit): Watch Later resolution errors are swallowed as diagnostics
    #   Given a mocked YouTube API where the Watch Later title lookup raises an API error
    #   And playlistItems.list for playlistId "WL" returns no items
    #   When gather_candidates is called with sources "watch_later"
    #   Then no exception escapes gather_candidates
    #   And playlistItems.list is still called with playlistId "WL"
    #   And no candidate is returned
    #   And a diagnostic note records the failed title lookup
    async def test_lookup_error_swallowed_as_diagnostic(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"WL": [{"items": []}]},
            raise_for={
                "playlists.list": urllib.error.HTTPError(
                    "https://www.googleapis.com/youtube/v3/playlists",
                    503,
                    "Service Unavailable",
                    email.message.Message(),
                    None,
                )
            },
        )
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later")

        assert calls == [
            ("playlists.list", {"part": "snippet", "mine": True, "maxResults": 50}),
            ("playlistItems.list", {"part": "contentDetails", "playlistId": "WL", "maxResults": "20"}),
        ]
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert (
            'watch_later: "Watch Later" title lookup failed (service unavailable - retry later); using legacy "WL" alias'
            in payload
        )
