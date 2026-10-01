"""T9-2: drop-counters, zero-suffix branch priority, and headline fallback for the Data API path."""

import youtube_manager
from youtube_manager import _subscription_headline, _subscription_zero_suffix

from .conftest import idless_playlist_item, playlist_item, video_detail


class TestUploadEntriesDropCounts:
    # Scenario: T9-2 (drop_counts) _upload_entries counts raw items and dropped no-video-id items
    #   Given Data API uploads with 1 usable V1 item and 1 idless item
    #   When _upload_entries is called with a drop_counts dict
    #   Then entries is exactly the 1 usable entry with video_id "V1"
    #   And drop_counts is exactly {"raw_entries": 2, "no_video_id": 1}
    def test_upload_entries_with_drop_counts(self):
        items = [playlist_item("V1", "V1", "C1", "2026-09-03T00:00:00Z"), idless_playlist_item()]
        details = {"V1": video_detail("V1", "PT1M0S", "100")}
        drop_counts: dict[str, int] = {}

        entries = youtube_manager._upload_entries(items, details, "UC1", drop_counts)

        assert [entry["video_id"] for entry in entries] == ["V1"]
        assert drop_counts == {"raw_entries": 2, "no_video_id": 1}

    # Scenario: T9-2 (no counter) _upload_entries without drop_counts returns only usable entries
    #   Given Data API uploads with 1 usable V1 item and 1 idless item
    #   When _upload_entries is called without a drop_counts dict
    #   Then entries is exactly the 1 usable entry with video_id "V1" (no counter required or mutated)
    def test_upload_entries_without_drop_counts(self):
        items = [playlist_item("V1", "V1", "C1", "2026-09-03T00:00:00Z"), idless_playlist_item()]
        details = {"V1": video_detail("V1", "PT1M0S", "100")}

        entries = youtube_manager._upload_entries(items, details, "UC1")

        assert [entry["video_id"] for entry in entries] == ["V1"]


class TestSubscriptionZeroSuffix:
    # Scenario: T9-2 (branch priority) _subscription_zero_suffix prefers capped when entries exist
    #   Given non-empty entries
    #   When _subscription_zero_suffix is called
    #   Then the suffix is exactly "capped entries produced no candidates"
    def test_capped_priority(self):
        assert _subscription_zero_suffix([{"video_id": "V1"}]) == "capped entries produced no candidates"

    # Scenario: T9-2 (branch priority) _subscription_zero_suffix reports no usable video id when no_video_id > 0
    #   Given no_video_id 2 and raw_entries 2 and empty entries
    #   When _subscription_zero_suffix is called
    #   Then the suffix is exactly "feeds returned 2 entry(s) with no usable video id"
    def test_no_video_id(self):
        assert (
            _subscription_zero_suffix([], {"no_video_id": 2, "raw_entries": 2})
            == "feeds returned 2 entry(s) with no usable video id"
        )

    # Scenario: T9-2 (branch priority) _subscription_zero_suffix reports zero entries when zero_entry_feeds > 0
    #   Given zero_entry_feeds 1 and no no_video_id and empty entries
    #   When _subscription_zero_suffix is called
    #   Then the suffix is exactly "feeds returned zero entries"
    def test_zero_entry(self):
        assert _subscription_zero_suffix([], {"zero_entry_feeds": 1}) == "feeds returned zero entries"

    # Scenario: T9-2 (branch priority) _subscription_zero_suffix falls back when no counters and empty entries
    #   Given empty entries and no counters
    #   When _subscription_zero_suffix is called
    #   Then the suffix is exactly "feeds returned no usable entries"
    def test_fallback(self):
        assert _subscription_zero_suffix([]) == "feeds returned no usable entries"


class TestSubscriptionHeadlineFallback:
    # Scenario: T9-2 S6 fallback zero-candidate shape is retained for backward-compatible calls
    #   Given _subscription_headline is called with ok 1, failed 1, entries empty, candidate_count 0, and no drop_counts
    #   When the headline is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned no usable entries)"
    def test_headline_fallback(self):
        assert (
            _subscription_headline(1, 1, [], 0)
            == "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned no usable entries)"
        )
