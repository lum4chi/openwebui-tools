"""T1-3: subscription feed channel ids resolve from contentDetails with the snippet fallback."""

from .conftest import api_fake, guard_urlopen, playlist_item, uploads_channel_reply

OWN_CHANNEL = "UCuserown"


def _sub_item(
    snippet_channel: str, content_details_channel: str | None, published: str = "2026-01-01T00:00:00Z"
) -> dict:
    """One subscriptions.list item; snippet.channelId pins the snippet read, contentDetails optional."""
    item: dict = {
        "id": snippet_channel,
        "snippet": {"channelId": snippet_channel, "title": "feed", "publishedAt": published},
    }
    if content_details_channel is not None:
        item["contentDetails"] = {"channelId": content_details_channel}
    return item


class TestSubscriptionChannels:
    # Scenario T1-3-S1 (unit): per-feed channel ids come from contentDetails
    #   Given a mocked subscriptions.list response with two subscription items
    #   And each item has snippet.channelId equal to the user's own channel id
    #   And each item has contentDetails.channelId for a distinct actually-subscribed channel
    #   And the per-feed channels.list and playlistItems.list responses return one upload item per feed
    #   When gather_candidates is called with sources "subscriptions"
    #   Then channels.list is called once for each distinct contentDetails.channelId
    #   And channels.list is never called with the user's own channel id as the per-feed channel id
    #   And candidates are returned for both feeds
    def test_s1_per_feed_channel_ids_come_from_content_details(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={
                "PUone": [{"items": [playlist_item("V1", "Feed one", "Chan one", "2026-09-01T00:00:00Z")]}],
                "PUtwo": [{"items": [playlist_item("V2", "Feed two", "Chan two", "2026-09-02T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [_sub_item(OWN_CHANNEL, "UCfeedone"), _sub_item(OWN_CHANNEL, "UCfeedtwo")]}],
            channels_by_id={"UCfeedone": uploads_channel_reply("PUone"), "UCfeedtwo": uploads_channel_reply("PUtwo")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        channel_ids = [params["id"] for method, params in calls if method == "channels.list"]
        assert channel_ids == ["UCfeedone", "UCfeedtwo"]
        assert OWN_CHANNEL not in channel_ids
        assert [c.video_id for c in cands] == ["V2", "V1"]
        assert {c.channel_id for c in cands} == {"UCfeedone", "UCfeedtwo"}

    # Scenario T1-3-S2 (unit): the 25-feed cap is preserved
    #   Given a mocked subscriptions.list response with 50 subscription items
    #   And each item has a distinct contentDetails.channelId
    #   When gather_candidates is called with sources "subscriptions"
    #   Then exactly 25 per-feed channels.list calls are made
    #   And exactly 25 per-feed playlistItems.list calls are made
    #   And no exception escapes gather_candidates
    def test_s2_the_25_feed_cap_is_preserved(self, tools, monkeypatch):
        items = [_sub_item(OWN_CHANNEL, f"UC{i:04d}") for i in range(50)]
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

    # Scenario T1-3-S3 (unit): missing contentDetails falls back to snippet channelId
    #   Given a mocked subscriptions.list response with one subscription item
    #   And the item has no contentDetails.channelId
    #   And the item has snippet.channelId "UCsnippetFallback"
    #   When gather_candidates is called with sources "subscriptions"
    #   Then channels.list is called with id "UCsnippetFallback"
    def test_s3_missing_content_details_falls_back_to_snippet(self, tools, monkeypatch):
        calls = api_fake(
            monkeypatch,
            pages={"PUfb": [{"items": [playlist_item("Vfb", "Fallback feed", "Chan fb", "2026-09-01T00:00:00Z")]}]},
            subscription_pages=[{"items": [_sub_item("UCsnippetFallback", None)]}],
            channels_by_id={"UCsnippetFallback": uploads_channel_reply("PUfb")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        channel_ids = [params["id"] for method, params in calls if method == "channels.list"]
        assert channel_ids == ["UCsnippetFallback"]
        assert [c.video_id for c in cands] == ["Vfb"]
