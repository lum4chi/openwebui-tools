"""T1 feedback aggregates in the digest payload (T1-6)."""

import pytest

import youtube_manager
from youtube_manager import NOTE_FEEDBACK, NOTE_TASTE

from .conftest import sample_feedback_log

# rec1: Ch A, 300s  -> <10m band
# rec2: Ch B, 3600s -> >30m band
# rec3: Ch A, 900s  -> 10-30m band
# rec4: Ch B, no duration -> excluded from band counts
ENTRY_DURATIONS = {"rec1": 300, "rec2": 3600, "rec3": 900, "rec4": None}
ENTRY_CHANNELS = {"rec1": "Ch A", "rec2": "Ch B", "rec3": "Ch A", "rec4": "Ch B"}

# rows: (date, video_id, decision, title, source, reason)
ROWS = [
    ("2026-09-01", "rec1", "watched", "t", "recommended", ""),
    ("2026-09-02", "rec1", "skipped", "t", "recommended", "too long"),
    ("2026-09-03", "rec1", "skipped", "t", "recommended", "again"),
    ("2026-09-04", "rec2", "listened", "t", "subscriptions", ""),
    ("2026-09-05", "rec2", "skipped", "t", "subscriptions", "boring"),
    ("2026-09-06", "rec3", "skipped", "t", "recommended", "length"),
    ("2026-09-07", "rec4", "skipped", "t", "recommended", "no duration"),
    # ghost: feedback row for a video not in this digest -> totals only
    ("2026-09-08", "ghost", "skipped", "t", "search", "not in digest"),
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
        ":ytrec": [_entry(vid) for vid in ("rec1", "rec2")],
        ":ytsubs": [_entry(vid) for vid in ("rec3", "rec4")],
    }


class TestAggregates:
    """T1-6 payload includes taste profile + deterministic feedback aggregates."""

    # @unit
    # Scenario: T1-6 aggregates in payload
    #   Given a taste-profile document exists and the feedback-log has watched/listened/skipped rows
    #   When digest runs
    #   Then the payload embeds the taste profile text
    #   And it reports total counts per decision
    #   And it reports skip counts per duration band for the candidates in this digest
    #   And it reports per-channel watch/listen vs skip counts
    #   And the same inputs always produce the same numbers (deterministic)
    async def test_payload_includes_stats(self, tools, monkeypatch, fake_store, _by_url):
        monkeypatch.setattr(
            youtube_manager, "_ytdlp_extract", lambda url, extra=None: {"entries": _by_url.get(url, [])}
        )
        fake_store.docs[NOTE_TASTE] = "PREFER-ROBOTICS-CLIPS"
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(ROWS)

        payload = await tools.digest()

        assert "PREFER-ROBOTICS-CLIPS" in payload  # taste profile text embedded
        assert "watched=1" in payload
        assert "listened=1" in payload
        assert "skipped=6" in payload  # ghost row counts in totals...
        assert "<10m=2" in payload  # ...but only digest candidates count per band
        assert "10-30m=1" in payload
        assert ">30m=1" in payload  # rec4 (no duration) and ghost excluded from bands
        assert "Ch A (watch/listen 1, skip 3)" in payload  # rec1 watched + 2 skips, rec3 skip
        assert "Ch B (watch/listen 1, skip 2)" in payload  # rec2 listened + skip, rec4 skip

    # Scenario T1-6 (determinism): same inputs -> identical payload
    async def test_deterministic(self, tools, monkeypatch, fake_store, _by_url):
        monkeypatch.setattr(
            youtube_manager, "_ytdlp_extract", lambda url, extra=None: {"entries": _by_url.get(url, [])}
        )
        fake_store.docs[NOTE_TASTE] = "PREFER-ROBOTICS-CLIPS"
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(ROWS)

        first = await tools.digest()
        second = await tools.digest()

        assert first == second  # same inputs always produce the same numbers
