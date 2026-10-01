"""T1-3-R: subscription feed channel ids resolve from snippet.resourceId.channelId (real live shape)."""

from .conftest import api_fake, guard_urlopen, playlist_item, uploads_channel_reply

OWN_CHANNEL = "UCuserown"


def _sub_item(feed_channel: str, published: str = "2026-01-01T00:00:00Z") -> dict:
    """One real-shape subscriptions.list item: snippet.channelId is the subscriber's own channel,
    snippet.resourceId.channelId is the distinct feed channel, no contentDetails.channelId."""
    return {
        "id": feed_channel,
        "snippet": {
            "channelId": OWN_CHANNEL,
            "resourceId": {"channelId": feed_channel},
            "title": "feed",
            "publishedAt": published,
        },
    }


class TestSubscriptionChannels:
    # Scenario T1-3-R-S1 (unit): per-feed channel ids come from snippet.resourceId.channelId
    #   Given a mocked subscriptions.list response with two subscription items
    #   And every item has snippet.channelId equal to the user's own channel id
    #   And each item has a distinct snippet.resourceId.channelId for the actually-subscribed feed
    #   And no item has contentDetails.channelId
    #   And the per-feed channels.list and playlistItems.list responses return one upload item per feed
    #   When gather_candidates is called with sources "subscriptions"
    #   Then subscriptions.list is called with part "snippet" and mine "true"
    #   And channels.list is called once for each distinct snippet.resourceId.channelId
    #   And channels.list is never called with the user's own channel id as the per-feed channel id
    #   And candidates carry the distinct per-feed channel ids from snippet.resourceId.channelId
    def test_s1_per_feed_channel_ids_come_from_resource_id(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={
                "PUone": [{"items": [playlist_item("V1", "Feed one", "Chan one", "2026-09-01T00:00:00Z")]}],
                "PUtwo": [{"items": [playlist_item("V2", "Feed two", "Chan two", "2026-09-02T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [_sub_item("UCfeedone"), _sub_item("UCfeedtwo")]}],
            channels_by_id={"UCfeedone": uploads_channel_reply("PUone"), "UCfeedtwo": uploads_channel_reply("PUtwo")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        sub_calls = [params for method, params in calls if method == "subscriptions.list"]
        assert sub_calls[0] == {"part": "snippet", "mine": "true", "maxResults": 50}
        channel_ids = [params["id"] for method, params in calls if method == "channels.list"]
        assert channel_ids == ["UCfeedone", "UCfeedtwo"]
        assert OWN_CHANNEL not in channel_ids
        assert [c.video_id for c in cands] == ["V2", "V1"]
        assert {c.channel_id for c in cands} == {"UCfeedone", "UCfeedtwo"}

    # Scenario T1-3-R-S2 (unit): the 25-feed cap is preserved with the real channel id source
    #   Given a mocked subscriptions.list response with 50 subscription items
    #   And each item has a distinct snippet.resourceId.channelId
    #   When gather_candidates is called with sources "subscriptions"
    #   Then exactly 25 per-feed channels.list calls are made
    #   And exactly 25 per-feed playlistItems.list calls are made
    #   And no exception escapes gather_candidates
    def test_s2_the_25_feed_cap_is_preserved(self, tools, monkeypatch):
        items = [_sub_item(f"UC{i:04d}") for i in range(50)]
        pages = {
            f"PU{i:04d}": [
                {"items": [playlist_item(f"V{i:04d}", f"Feed {i}", f"Chan {i}", f"2026-09-{i + 1:02d}T00:00:00Z")]}
            ]
            for i in range(25)
        }
        channels_by_id = {f"UC{i:04d}": uploads_channel_reply(f"PU{i:04d}") for i in range(25)}
        calls = api_fake(
            monkeypatch,
            pages=pages,
            subscription_pages=[{"items": items}],
            channels_by_id=channels_by_id,
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        channel_ids = [params["id"] for method, params in calls if method == "channels.list"]
        assert channel_ids == [f"UC{i:04d}" for i in range(25)]
        playlist_ids = [params["playlistId"] for method, params in calls if method == "playlistItems.list"]
        assert playlist_ids == [f"PU{i:04d}" for i in range(25)]
        assert len(cands) == 20
        assert notes == ["subscriptions: 25 ok, 0 failed, 20 candidates"]

    # Scenario T1-3-R-S3 (unit): malformed subscription feed is skipped before channels.list (O-3 APPROVED)
    #   Given a mocked subscriptions.list response containing one item without snippet.resourceId.channelId
    #   When gather_candidates is called with sources "subscriptions"
    #   Then no channels.list call is made for that item
    #   And no exception escapes gather_candidates
    #   And the feed is reported as channel not found
    def test_s3_malformed_feed_skipped_before_channels_list(self, tools, monkeypatch):
        malformed = {
            "id": "UCmalformed",
            "snippet": {"channelId": OWN_CHANNEL, "title": "feed", "publishedAt": "2026-01-01T00:00:00Z"},
        }
        calls = api_fake(monkeypatch, pages={}, subscription_pages=[{"items": [malformed]}], videos={})
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        channel_ids = [params["id"] for method, params in calls if method == "channels.list"]
        assert channel_ids == []
        assert cands == []
        assert notes == ["subscriptions: 0 ok, 1 failed (e.g. channel  → channel not found)"]
