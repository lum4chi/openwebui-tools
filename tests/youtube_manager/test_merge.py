"""T1 merge + enrichment mapping (scenarios T1-2, T1-5)."""

import pytest

from youtube_manager import Candidate, candidates_from_ytdlp, merge_candidates

SAMPLE_TAGS = ["rust", "async"]


def ytdlp_entry(video_id, **overrides):
    """Full yt-dlp feed entry; overrides may set a value to None to drop the key."""
    entry = {
        "id": video_id,
        "title": f"Title {video_id}",
        "uploader": f"Uploader {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 65,
        "view_count": 1234,
        "timestamp": 1757520000,
        "description": f"desc {video_id}",
        "tags": SAMPLE_TAGS,
    }
    for key, value in overrides.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


class TestMerge:
    """Dedupe/merge + raw-entry -> Candidate mapping."""

    # @unit
    # Scenario: T1-2 dedupe merge
    #   Given the same video id appears in both the recommended and subscription feeds
    #   When candidates are merged
    #   Then exactly one candidate remains for that id
    #   And its sources list contains both "recommended" and "subscriptions"
    #   And first-seen order across sources is preserved
    @pytest.mark.parametrize(
        ("lists", "expected_ids", "expected_sources"),
        [
            # same id in both feeds -> one candidate, union sources, first-seen order
            (
                [
                    [Candidate("a", "A", "ch", None, None, None, None, None, [], ["recommended"])],
                    [
                        Candidate("a", "A", "ch", None, None, None, None, None, [], ["subscriptions"]),
                        Candidate("b", "B", "ch", None, None, None, None, None, [], ["subscriptions"]),
                    ],
                ],
                ["a", "b"],
                {"a": ["recommended", "subscriptions"], "b": ["subscriptions"]},
            ),
            # no overlap -> every candidate kept, order = first-seen across sources
            (
                [
                    [Candidate("a", "A", "ch", None, None, None, None, None, [], ["recommended"])],
                    [Candidate("b", "B", "ch", None, None, None, None, None, [], ["subscriptions"])],
                ],
                ["a", "b"],
                {"a": ["recommended"], "b": ["subscriptions"]},
            ),
            # duplicate source names across feeds are not repeated in the union
            (
                [
                    [Candidate("a", "A", "ch", None, None, None, None, None, [], ["recommended"])],
                    [Candidate("a", "A", "ch", None, None, None, None, None, [], ["recommended"])],
                ],
                ["a"],
                {"a": ["recommended"]},
            ),
        ],
        ids=["overlap_union", "no_overlap", "same_source_not_duplicated"],
    )
    def test_cross_source_dedupe(self, lists, expected_ids, expected_sources):
        merged = merge_candidates(lists)
        assert [cand.video_id for cand in merged] == expected_ids
        for cand in merged:
            assert cand.sources == expected_sources[cand.video_id]

    # @unit
    # Scenario: T1-5 enrichment fields
    #   Given raw feed entries with title, channel, duration, views, published date, description, tags
    #   When candidates are built
    #   Then each Candidate carries all seven fields mapped correctly
    #   And missing optional fields become None/[] rather than errors
    @pytest.mark.parametrize(
        ("entry", "expect"),
        [
            (
                # full entry: every field mapped (timestamp -> YYYY-MM-DD published date)
                ytdlp_entry("full"),
                {
                    "video_id": "full",
                    "title": "Title full",
                    "channel_name": "Uploader full",
                    "channel_id": "ch-full",
                    "duration_sec": 65,
                    "views": 1234,
                    "published": "2025-09-10",
                    "description": "desc full",
                    "tags": SAMPLE_TAGS,
                },
            ),
            (
                # no timestamp -> upload_date (YYYYMMDD) reformatted to YYYY-MM-DD
                ytdlp_entry("dated", timestamp=None, upload_date="20260830"),
                {"published": "2026-08-30"},
            ),
            (
                # optional fields missing -> None / [] rather than errors
                ytdlp_entry(
                    "bare",
                    title=None,
                    uploader=None,
                    channel_id=None,
                    duration=None,
                    view_count=None,
                    timestamp=None,
                    description=None,
                    tags=None,
                    channel="Fallback Channel",
                ),
                {
                    "video_id": "bare",
                    "title": "",
                    "channel_name": "Fallback Channel",
                    "channel_id": None,
                    "duration_sec": None,
                    "views": None,
                    "published": None,
                    "description": None,
                    "tags": [],
                },
            ),
        ],
        ids=["full_mapping", "upload_date", "missing_optional_fields"],
    )
    def test_enrichment_mapping(self, entry, expect):
        (cand,) = candidates_from_ytdlp([entry], "recommended")
        for field, value in expect.items():
            assert getattr(cand, field) == value
        assert cand.sources == ["recommended"]
