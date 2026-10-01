"""T1-2-C S5/S6: check_setup reports the watch_later surrogate playlist status and stays READY.

The watch_later source is a user-maintained playlist named by the watch_later_playlist_title valve
(default "Watch Later"), resolved by exact trimmed title match against playlists.list — never the
hidden "WL" system alias.
"""

from unittest.mock import patch

from youtube_manager import Tools

from .conftest import api_fake, guard_urlopen, listing_page, playlist_row, sub_channel, uploads_channel_reply


class TestWatchLaterValveDefault:
    # @unit
    # Scenario T1-2-C objective: the watch_later_playlist_title valve defaults to "Watch Later"
    #   Given a freshly constructed Tools instance (no valves set)
    #   When the watch_later_playlist_title valve is read
    #   Then it equals "Watch Later"
    def test_watch_later_playlist_title_defaults_to_watch_later(self):
        assert Tools().valves.watch_later_playlist_title == "Watch Later"


class TestWatchLaterValveSetup:
    """check_setup's watch_later line reflects the surrogate (valve-named) playlist status."""

    # @unit
    # Scenario T1-2-C-S5 (unit): check_setup FOUND reports surrogate playlist checked and stays READY
    #   Given a mocked check_setup API where the valve-title playlist exists
    #   When check_setup is exercised
    #   Then no playlistItems.list call uses playlistId "WL"
    #   And the watch_later line is watch_later: ok (surrogate playlist checked)
    #   And the overall setup status remains READY
    #   # provenance: user instruction "check_setup reports the surrogate status (found/not found) and stays READY"
    async def test_check_setup_found_reports_surrogate_checked_and_stays_ready(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"PLWL": [listing_page([])], "PU0000": [listing_page([])]},
            playlist_pages=[{"items": [playlist_row("PLWL", "Watch Later")]}],
            subscription_pages=[{"items": [sub_channel("UC0000", own_channel_id="UCown0000")]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
        )
        guard_urlopen(monkeypatch)
        with patch("youtube_manager._oauth_token", return_value={"access_token": "fake"}):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (subscription feed checked)",
            "watch_later: ok (surrogate playlist checked)",
            "READY",
        ]
        assert all(params.get("playlistId") != "WL" for method, params in calls if method == "playlistItems.list")

    # @unit
    # Scenario T1-2-C-S6 (unit): check_setup NOT FOUND reports surrogate playlist not found and stays READY
    #   Given a mocked check_setup API where the valve-title playlist is absent
    #   When check_setup is exercised
    #   Then no playlistItems.list call is made
    #   And no playlistItems.list call uses playlistId "WL"
    #   And the watch_later line is watch_later: ok (surrogate playlist not found)
    #   And the overall setup status remains READY
    #   # provenance: user instruction "check_setup reports the surrogate status (found/not found) and stays READY"
    async def test_check_setup_not_found_reports_surrogate_not_found_and_stays_ready(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={},
            playlist_pages=[{"items": [playlist_row("PLother", "Some other playlist")]}],
            subscription_pages=[{"items": []}],
        )
        guard_urlopen(monkeypatch)
        with patch("youtube_manager._oauth_token", return_value={"access_token": "fake"}):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (0 subscriptions)",
            "watch_later: ok (surrogate playlist not found)",
            "READY",
        ]
        assert all(method != "playlistItems.list" for method, _ in calls)
