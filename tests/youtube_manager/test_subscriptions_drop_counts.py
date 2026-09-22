"""T9-2 B2-new: _parse_rss drop-counters, _subscription_zero_suffix branch priority, _subscription_headline fallback shape."""

from youtube_manager import _parse_rss, _subscription_headline, _subscription_zero_suffix

FEED_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
    'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
)


def _entry_feed(*entries: str) -> bytes:
    return (FEED_HEAD + "".join(entries) + "</feed>").encode()


def _usable_entry(video_id: str) -> str:
    return (
        "<entry>"
        f"<id>yt:video:{video_id}</id><yt:videoId>{video_id}</yt:videoId>"
        "<yt:channelId>UC0000</yt:channelId>"
        f"<title>Video {video_id}</title>"
        "<author><name>Feed Chan</name></author>"
        "<published>2026-09-03</published>"
        "</entry>"
    )


def _idless_entry(i: int) -> str:
    """An Atom <entry> with neither a <yt:videoId> nor a yt:video: <id> (no usable video id)."""
    return (
        "<entry>"
        f"<id>http://www.youtube.com/channel/UC{i:04d}</id>"
        f"<title>No video id {i}</title>"
        "<author><name>Feed Chan</name></author>"
        "<published>2026-09-03</published>"
        "</entry>"
    )


class TestParseRssDropCounts:
    # Scenario: T9-2 (drop_counts) _parse_rss counts raw entries and dropped no-video-id entries
    #   Given a feed with 1 usable V1 entry and 1 idless entry
    #   When _parse_rss is called with a drop_counts dict
    #   Then entries is exactly the 1 usable entry with video_id "V1"
    #   And drop_counts is exactly {"raw_entries": 2, "no_video_id": 1}
    def test_parse_rss_with_drop_counts(self):
        raw = _entry_feed(_usable_entry("V1"), _idless_entry(0))
        drop_counts: dict[str, int] = {}

        entries = _parse_rss(raw, drop_counts)

        assert len(entries) == 1
        assert entries[0]["video_id"] == "V1"
        assert drop_counts == {"raw_entries": 2, "no_video_id": 1}

    # Scenario: T9-2 (no counter) _parse_rss without drop_counts returns only usable entries
    #   Given a feed with 1 usable V1 entry and 1 idless entry
    #   When _parse_rss is called without a drop_counts dict
    #   Then entries is exactly the 1 usable entry with video_id "V1" (no counter required or mutated)
    def test_parse_rss_without_drop_counts(self):
        raw = _entry_feed(_usable_entry("V1"), _idless_entry(0))

        entries = _parse_rss(raw)

        assert len(entries) == 1
        assert entries[0]["video_id"] == "V1"


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
