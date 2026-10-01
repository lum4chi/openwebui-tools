"""T0-1 subscriptions plumbing: per-channel Data API fetch + source-level failure behavior."""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_manager import QuotaError, ReauthNeeded

from .conftest import (
    api_fake,
    empty_channel_reply,
    guard_urlopen,
    listing_page,
    no_uploads_channel_reply,
    playlist_item,
    sub_channel,
    uploads_channel_reply,
    video_detail,
)


def _happy_api(monkeypatch):
    return api_fake(
        monkeypatch,
        pages={
            "PU1": [
                {
                    "items": [
                        playlist_item("V1", "One", "Chan 1", "2026-09-03T00:00:00Z", "d1"),
                        playlist_item("V2", "Two", "Chan 1", "2026-09-01T00:00:00Z", "d2"),
                        playlist_item("V3", "Three", "Chan 1", "2026-09-02T00:00:00Z", "d3"),
                    ]
                }
            ],
            "PU2": [
                {
                    "items": [
                        playlist_item("V4", "Four", "Chan 2", "2026-09-04T00:00:00Z", "d4"),
                        playlist_item("V5", "Five", "Chan 2", "2026-08-31T00:00:00Z", "d5"),
                    ]
                }
            ],
        },
        subscription_pages=[{"items": [sub_channel("UC1"), sub_channel("UC2")]}],
        channels_by_id={"UC1": uploads_channel_reply("PU1"), "UC2": uploads_channel_reply("PU2")},
        videos={
            "V1": video_detail("V1", "PT1M0S", "100"),
            "V2": video_detail("V2", "PT2M0S", "200"),
            "V3": video_detail("V3", "PT3M0S", "300"),
            "V4": video_detail("V4", "PT4M0S", "400"),
            "V5": video_detail("V5", "PT5M0S", "500"),
        },
    )


class TestFetchSubscriptions:
    # S1 [unit] — subscriptions returns candidates via the Data API with full metadata.
    #   Given mocked Data API with subscriptions.list returning channels U1, U2
    #   And channels.list returning uploads playlists PU1, PU2 for U1, U2
    #   And playlistItems.list returning 3 items on PU1 and 2 items on PU2 (resourceId/title/publishedAt/description)
    #   And videos.list returning contentDetails + statistics for all 5 video ids
    #   And urlopen patched to raise if called (no network)
    #   When gather_candidates(sources="subscriptions", max_per_source=20) runs
    #   Then 5 candidates are returned, each carrying video_id, title, channel_name, channel_id, published as YYYY-MM-DD, duration_sec, views, description
    #   And candidates are sorted newest-first across channels with sources ["subscriptions"]
    #   And the note line is "subscriptions: 2 ok, 0 failed, 5 candidates"
    # @unit
    # Scenario T1-4-S3 (unit): subscription feeds surface candidates from real-shaped videos.list responses
    #   # trace: user's verbatim live run "FAIL subscriptions candidates=0; feeds=<25 distinct channels, each 17-20 items>"
    #   Given 3 subscription feeds each yielding 2 uploads via the mocked channels.list and playlistItems.list responses
    #   And the mocked videos.list response holds one real-shaped item for each of the 6 video ids
    #   When gather_candidates is called with sources "subscriptions"
    #   Then no exception escapes gather_candidates
    #   And 6 candidates are returned across the 3 feeds carrying the per-feed channel ids
    def test_s1_returns_candidates_via_data_api(self, tools, monkeypatch):
        _happy_api(monkeypatch)
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert [c.video_id for c in cands] == ["V4", "V1", "V3", "V2", "V5"]
        assert all(c.sources == ["subscriptions"] for c in cands)
        by_id = {c.video_id: c for c in cands}
        assert by_id["V1"].title == "One"
        assert by_id["V1"].channel_name == "Chan 1"
        assert by_id["V1"].channel_id == "UC1"
        assert by_id["V1"].published == "2026-09-03"
        assert by_id["V1"].duration_sec == 60
        assert by_id["V1"].views == 100
        assert by_id["V1"].description == "d1"
        assert by_id["V5"].channel_id == "UC2"
        assert notes == ["subscriptions: 2 ok, 0 failed, 5 candidates"]

    # S2 [unit] — per-channel fetch uses the authenticated Data API call sequence, not RSS.
    #   Given the S1 happy-path mocks
    #   When gather_candidates(sources="subscriptions") runs
    #   Then the recorded API calls include subscriptions.list(part=snippet, mine=true, maxResults=50)
    #   And for each channel: channels.list(part=contentDetails, id=<channel_id>)
    #   And playlistItems.list(part=snippet, playlistId=<uploads>, maxResults="20")
    #   And videos.list(part="snippet,contentDetails,statistics") with the channel's video ids
    #   And urllib.request.urlopen is never called
    def test_s2_per_channel_data_api_call_sequence(self, tools, monkeypatch):
        calls = _happy_api(monkeypatch)
        guard_urlopen(monkeypatch)

        tools._fetch_subscriptions(20, [])

        assert calls[0] == ("subscriptions.list", {"part": "snippet", "mine": "true", "maxResults": 50})
        channel_calls = [params for method, params in calls if method == "channels.list"]
        assert channel_calls == [
            {"part": "contentDetails", "id": "UC1"},
            {"part": "contentDetails", "id": "UC2"},
        ]
        playlist_calls = {params["playlistId"]: params for method, params in calls if method == "playlistItems.list"}
        assert playlist_calls == {
            "PU1": {"part": "snippet", "playlistId": "PU1", "maxResults": "20"},
            "PU2": {"part": "snippet", "playlistId": "PU2", "maxResults": "20"},
        }
        video_calls = [params for method, params in calls if method == "videos.list"]
        assert [p["part"] for p in video_calls] == [
            "snippet,contentDetails,statistics",
            "snippet,contentDetails,statistics",
        ]
        assert [p["id"] for p in video_calls] == ["V1,V2,V3", "V4,V5"]

    # S3 [unit] — one failing channel does not sink the rest.
    #   Given 2 channels where U2's playlistItems.list raises HttpError 403
    #   When gather_candidates(sources="subscriptions") runs
    #   Then U1's candidates are returned and no exception propagates
    #   And the note reports 1 ok, 1 failed
    def test_s3_one_failing_channel_is_isolated(self, tools, monkeypatch):
        err = HttpError(MagicMock(status=403, reason="Forbidden"), b'{"error": {"message": "quota"}}')
        api_fake(
            monkeypatch,
            pages={
                "PU1": [{"items": [playlist_item("V1", "One", "Chan 1", "2026-09-03T00:00:00Z", "d1")]}],
                "PU2": [{"items": []}],
            },
            subscription_pages=[{"items": [sub_channel("UC1"), sub_channel("UC2")]}],
            channels_by_id={"UC1": uploads_channel_reply("PU1"), "UC2": uploads_channel_reply("PU2")},
            videos={"V1": video_detail("V1", "PT1M0S", "100")},
            raise_for_playlist={"PU2": err},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert [c.video_id for c in cands] == ["V1"]
        assert notes == ["subscriptions: 1 ok, 1 failed, 1 candidates (e.g. channel UC2 → HTTP 403: quota)"]

    # S4 [unit] — max_per_source boundary 1.
    #   Given 3 channels each with 5 playlist entries
    #   When max_per_source is 1 then exactly 1 candidate (the single newest overall)
    def test_s4_max_per_source_one_returns_single_newest(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={
                "PA": [{"items": [playlist_item("A1", "A1", "A", "2026-09-01T00:00:00Z")]}],
                "PB": [{"items": [playlist_item("B1", "B1", "B", "2026-09-03T00:00:00Z")]}],
                "PC": [{"items": [playlist_item("C1", "C1", "C", "2026-09-02T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [sub_channel("UCA"), sub_channel("UCB"), sub_channel("UCC")]}],
            channels_by_id={
                "UCA": uploads_channel_reply("PA"),
                "UCB": uploads_channel_reply("PB"),
                "UCC": uploads_channel_reply("PC"),
            },
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(1, notes)

        assert [c.video_id for c in cands] == ["B1"]
        assert notes == ["subscriptions: 3 ok, 0 failed, 1 candidates"]

    # S4 [unit] — max_per_source boundary 0 preserves the capped-entries diagnostic.
    #   Given 3 channels each with 5 playlist entries
    #   And when max_per_source is 0 then 0 candidates and the note line ends with "0 candidates (capped entries produced no candidates)"
    def test_s4_max_per_source_zero_caps_to_zero(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={
                "PA": [{"items": [playlist_item("A1", "A1", "A", "2026-09-01T00:00:00Z")]}],
                "PB": [{"items": [playlist_item("B1", "B1", "B", "2026-09-03T00:00:00Z")]}],
                "PC": [{"items": [playlist_item("C1", "C1", "C", "2026-09-02T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [sub_channel("UCA"), sub_channel("UCB"), sub_channel("UCC")]}],
            channels_by_id={
                "UCA": uploads_channel_reply("PA"),
                "UCB": uploads_channel_reply("PB"),
                "UCC": uploads_channel_reply("PC"),
            },
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(0, notes)

        assert cands == []
        assert notes == ["subscriptions: 3 ok, 0 failed, 0 candidates (capped entries produced no candidates)"]

    # S4 [unit] — default 20 caps 25 probed channels to 20 candidates.
    #   Given 3 channels each with 5 playlist entries
    #   And when default 20 with 25 channels then 20 candidates and all 25 channels are probed
    def test_s4_default_caps_to_twenty_across_25_channels(self, tools, monkeypatch):
        channels = [sub_channel(f"UC{i:03d}") for i in range(25)]
        pages = {
            f"PU{i:03d}": [
                {"items": [playlist_item(f"V{i:03d}", f"Title {i}", f"Chan {i}", f"2026-09-{i + 1:02d}T00:00:00Z")]}
            ]
            for i in range(25)
        }
        channels_by_id = {f"UC{i:03d}": uploads_channel_reply(f"PU{i:03d}") for i in range(25)}
        calls = api_fake(
            monkeypatch,
            pages=pages,
            subscription_pages=[{"items": channels}],
            channels_by_id=channels_by_id,
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert len(cands) == 20
        assert notes == ["subscriptions: 25 ok, 0 failed, 20 candidates"]
        assert [params["id"] for method, params in calls if method == "channels.list"] == [
            f"UC{i:03d}" for i in range(25)
        ]

    # T1-5 · workflow — source-level 404 from subscriptions.list returns empty with a note.
    #   Given _data_api_request raises a raw HttpError with status 404 for subscriptions.list
    #   When _fetch_subscriptions(20, notes) runs
    #   Then it returns [] without raising
    #   And notes records the failure
    def test_source_level_404_returns_empty_with_note(self, tools, monkeypatch):
        err = HttpError(MagicMock(status=404, reason="Not Found"), b'{"error": {"message": "subscriptionNotFound"}}')
        api_fake(monkeypatch, pages={}, raise_for={"subscriptions.list": err})
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 1
        assert notes[0].startswith("subscriptions")
        assert "404" in notes[0]

    # T1-6 · workflow — ReauthNeeded and QuotaError from subscriptions.list still propagate.
    #   Given subscriptions.list raising ReauthNeeded (case A) resp. QuotaError (case B)
    #   When _fetch_subscriptions(20, notes) runs
    #   Then the same exception type propagates to the caller (parametrize A/B)
    @pytest.mark.parametrize("exc", [ReauthNeeded, QuotaError], ids=["reauth", "quota"])
    def test_reauth_and_quota_propagate(self, tools, monkeypatch, exc):
        api_fake(monkeypatch, pages={}, raise_for={"subscriptions.list": exc("boom")})
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        with pytest.raises(exc):
            tools._fetch_subscriptions(20, notes)

    # T1-5 implementation complement — non-404 source-level HttpError propagates.
    # Given a 500 HttpError on subscriptions.list; When _fetch_subscriptions runs; Then it propagates and notes stay empty
    def test_non_404_http_error_propagates(self, tools, monkeypatch):
        err = HttpError(MagicMock(status=500, reason="Server Error"), b"server error")
        api_fake(monkeypatch, pages={}, raise_for={"subscriptions.list": err})
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        with pytest.raises(HttpError):
            tools._fetch_subscriptions(20, notes)
        assert notes == []

    # T0-1 Data API boundary — channels.list with no uploads yields the soft "channel not found" reason.
    # Given channels.list has no uploads; When _collect_channel runs; Then it returns ("UC1", "channel not found")
    @pytest.mark.parametrize("reply", [empty_channel_reply(), no_uploads_channel_reply()], ids=["empty", "no_uploads"])
    def test_collect_channel_reports_channel_not_found(self, tools, monkeypatch, reply):
        api_fake(monkeypatch, pages={}, channels_by_id={"UC1": reply})
        guard_urlopen(monkeypatch)

        assert tools._collect_channel(sub_channel("UC1"), [], 20) == ("UC1", "channel not found")

    # T0-1 contract — channel enumeration pagination preserved: the second subscriptions.list call carries pageToken.
    # Given page 1 returns a pageToken; When _list_subscription_channels runs; Then the second call carries that pageToken
    def test_subscription_channels_follow_page_token(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={},
            subscription_pages=[
                listing_page([sub_channel("UC1")], token="page-2"),
                listing_page([sub_channel("UC2")]),
            ],
        )
        guard_urlopen(monkeypatch)

        channels = tools._list_subscription_channels()

        assert [(ch.get("snippet") or {}).get("channelId") for ch in channels] == ["UC1", "UC2"]
        sub_calls = [params for method, params in calls if method == "subscriptions.list"]
        assert sub_calls[0] == {"part": "snippet", "mine": "true", "maxResults": 50}
        assert sub_calls[1] == {
            "part": "snippet",
            "mine": "true",
            "maxResults": 50,
            "pageToken": "page-2",
        }
