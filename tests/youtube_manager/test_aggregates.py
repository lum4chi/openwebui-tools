"""T1 feedback aggregates in the digest payload (T1-6): stats, per-source counts, determinism."""

import pytest

import youtube_manager
from youtube_manager import NOTE_FEEDBACK, NOTE_TASTE

from .conftest import sample_feedback_log, sample_taste_profile

TOPICS = ["rust async", "postgres"]

# rec1: Ch A, 300s  -> <10m band
# rec2: Ch B, 3600s -> >30m band
# rec3: Ch A, 900s  -> 10-30m band
# rec4: Ch B, no duration -> excluded from band counts
ENTRY_DURATIONS = {"rec1": 300, "rec2": 3600, "rec3": 900, "rec4": None}
ENTRY_CHANNELS = {"rec1": "Ch A", "rec2": "Ch B", "rec3": "Ch A", "rec4": "Ch B"}

# rows: (date, video_id, decision, title, source, reason)
ROWS = [
    ("2026-09-01", "rec1", "watched", "t", "search:rust async", ""),
    ("2026-09-02", "rec1", "skipped", "t", "search:rust async", "too long"),
    ("2026-09-03", "rec1", "skipped", "t", "search:rust async", "again"),
    ("2026-09-04", "rec2", "listened", "t", "search:postgres", ""),
    ("2026-09-05", "rec2", "skipped", "t", "search:postgres", "boring"),
    ("2026-09-06", "rec3", "skipped", "t", "search:postgres", "length"),
    ("2026-09-07", "rec4", "skipped", "t", "search:rust async", "no duration"),
    # ghost: feedback row for a video not in this digest -> totals only
    ("2026-09-08", "ghost", "skipped", "t", "search:rust async", "not in digest"),
]


def _entry(video_id):
    return {
        "id": video_id,
        "title": f"Title {video_id}",
        "uploader": ENTRY_CHANNELS[video_id],
        "channel_id": f"ch-{video_id}",
        "duration": ENTRY_DURATIONS[video_id],
        "view_count": 100,
        "upload_date": "20260910",
        "description": f"Desc {video_id}",
        "tags": ["tag"],
    }


@pytest.fixture
def _by_url():
    return {
        "ytsearch20:rust async": [_entry(vid) for vid in ("rec1", "rec2")],
        "ytsearch20:postgres": [_entry(vid) for vid in ("rec3", "rec4")],
    }


def _api_fake(monkeypatch, video_ids=("wl1",)):
    """Route _data_api_request on the watch_later + subscriptions paths (OAuth is set in the tools fixture)."""
    details = {
        "wl1": {
            "id": "wl1",
            "snippet": {
                "title": "Detail title wl1",
                "channelId": "ch-wl1",
                "channelTitle": "Detail channel wl1",
                "description": "Detail description wl1",
                "tags": ["wl-tag"],
                "publishedAt": "2026-09-01T12:00:00Z",
            },
            "contentDetails": {"duration": "PT2M35S"},
        },
        "rec1": {
            "id": "rec1",
            "snippet": {
                "title": "rec1 title",
                "channelId": "ch-rec",
                "channelTitle": "Ch A",
                "publishedAt": "2026-09-10T00:00:00Z",
                "viewCount": "5000",
            },
            "contentDetails": {"duration": "PT5M"},
        },
        "rec2": {
            "id": "rec2",
            "snippet": {
                "title": "rec2 title",
                "channelId": "ch-rec",
                "channelTitle": "Ch B",
                "publishedAt": "2026-09-09T00:00:00Z",
                "viewCount": "1200000",
            },
            "contentDetails": {"duration": "PT1H"},
        },
        "rec3": {
            "id": "rec3",
            "snippet": {
                "title": "rec3 title",
                "channelId": "ch-rec",
                "channelTitle": "Ch A",
                "publishedAt": "2026-09-08T00:00:00Z",
            },
            "contentDetails": {"duration": "PT15M"},
        },
        # rec4 has no contentDetails -> duration_sec None -> excluded from band counts
        "rec4": {
            "id": "rec4",
            "snippet": {
                "title": "rec4 title",
                "channelId": "ch-rec",
                "channelTitle": "Ch B",
                "publishedAt": "2026-09-07T00:00:00Z",
            },
        },
    }

    def fake(valves, method, params, user_id=None):
        if method == "channels.list":
            raise AssertionError("channels.list must never be called on the watch_later path")
        if method == "playlists.list":
            return {"items": [{"id": "PLWL", "snippet": {"title": "Watch Later"}}]}
        if method == "playlistItems.list":
            return {"items": [{"contentDetails": {"videoId": vid}} for vid in video_ids]}
        if method == "videos.list":
            return {"items": [details[i] for i in params["id"].split(",")]}
        if method == "subscriptions.list":
            return {"items": []}  # no channels -> source attempted, yields 0 candidates
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)


def _seed(monkeypatch, fake_store, by_url, video_ids=("wl1",)):
    """Seed both test doubles + the two state docs the digest reads."""
    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", lambda url, extra=None: {"entries": by_url.get(url, [])})
    _api_fake(monkeypatch, video_ids)
    fake_store.docs[NOTE_TASTE] = sample_taste_profile(TOPICS, [])
    fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(ROWS)


class TestAggregates:
    """T1-6 payload includes taste profile + deterministic feedback aggregates + per-source counts."""

    # @unit
    # Scenario: T1-6 aggregates in payload
    #   Given a taste-profile document exists and the feedback-log has watched/listened/skipped rows
    #   When digest runs
    #   Then the payload embeds the taste profile text
    #   And it reports total counts per decision
    #   And it reports no band/channel rows when no log row references a candidate in this digest
    #   And it reports a Sources section with `watch_later` and `subscriptions` counts (no `search:<topic>` entries)
    #   And the same inputs always produce the same numbers (deterministic)
    async def test_payload_includes_stats_and_sources(self, tools, monkeypatch, fake_store, _by_url):
        _seed(monkeypatch, fake_store, _by_url)

        payload = await tools.digest()

        assert "- rust async" in payload  # taste profile text embedded (## Topics)
        assert "- postgres" in payload
        assert "feedback (latest wins): skipped=5" in payload  # latest-wins: 5 of 8 rows survive, all skipped
        assert "watched=" not in payload
        assert "listened=" not in payload
        # no band/channel rows: none of the log rows references a candidate in this digest
        assert "skips by duration" not in payload
        assert "channels:" not in payload
        # per-source candidate counts (pre-merge, every attempted source)
        assert "watch_later=1" in payload
        assert "subscriptions=0" in payload
        assert "search:" not in payload  # model-driven digest: no per-topic search fan-out

    # @unit
    # Scenario: (AC-1 fallout — no dedicated BDD id) feedback stats when log rows intersect digest candidates
    #   Given a taste-profile document exists and the feedback-log has watched/listened/skipped rows
    #   And the digest candidates (watch_later) include the videos referenced by the log
    #   When digest runs
    #   Then it reports skip counts per duration band for the candidates in this digest
    #   And it reports per-channel watch/listen vs skip counts
    #   And it renders candidate views in human units (K / M)
    async def test_band_and_channel_stats_when_candidates_intersect_log(self, tools, monkeypatch, fake_store, _by_url):
        _seed(monkeypatch, fake_store, _by_url, video_ids=("wl1", "rec1", "rec2", "rec3", "rec4"))

        payload = await tools.digest()

        # bands: only latest-wins skipped rows whose video is a candidate in this digest, by duration
        assert "<10m=1" in payload  # rec1 skipped (latest row), 300s
        assert "10-30m=1" in payload  # rec3 skipped x1, 900s
        assert ">30m=1" in payload  # rec2 skipped (latest row), 3600s; rec4 (no duration) excluded
        # channels: latest-wins rows for candidate videos, watched/listened vs skipped
        assert "channels: Ch A (watch/listen 0, skip 2) | Ch B (watch/listen 0, skip 2)" in payload
        assert "feedback (latest wins): skipped=5" in payload  # totals span every latest-wins row incl. the ghost
        # candidate views rendered in human units
        assert "5K views" in payload  # rec1 viewCount 5000
        assert "1.2M views" in payload  # rec2 viewCount 1200000
        # sources: model-driven digest, watch_later carries the whole candidate set
        assert "watch_later=5" in payload
        assert "search:" not in payload

    # Scenario T1-6 (determinism): same inputs -> identical payload
    async def test_deterministic(self, tools, monkeypatch, fake_store, _by_url):
        _seed(monkeypatch, fake_store, _by_url)

        first = await tools.digest()
        second = await tools.digest()

        assert first == second  # same inputs always produce the same numbers
