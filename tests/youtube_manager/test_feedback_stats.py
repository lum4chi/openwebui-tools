"""Q1(b): feedback stats `totals` are latest-wins per video_id; channels/bands are session-scoped (candidate rows only)."""

from youtube_manager import (
    NOTE_FEEDBACK,
    Candidate,
    FeedbackEntry,
    Tools,
    aggregate_feedback,
)

from .conftest import sample_feedback_log


def _candidate(video_id: str, channel_name: str, duration_sec: int | None) -> Candidate:
    return Candidate(
        video_id=video_id,
        title=f"Title {video_id}",
        channel_name=channel_name,
        channel_id=f"ch-{video_id}",
        duration_sec=duration_sec,
        views=100,
        published="2026-09-01",
        description="desc",
        tags=[],
        sources=["digest"],
    )


class TestFeedbackStats:
    """Q1(b): `stats.totals` is latest-wins per video_id; `channel_counts`/bands are candidate-scoped (latest-wins rows only)."""

    # T1-1 · unit · provenance: AC-1 (totals are latest-wins per video_id, NOT a double-count; scoped parts exclude ghost rows)
    #   Given a feedback log with two "watched" rows (one id present in the current candidates,
    #         one a stale/ghost id) and one "skipped" row (three distinct video_ids -> every row is its video's latest)
    #   When aggregate_feedback(rows, candidates) runs
    #   Then stats.totals["watched"] == 2   (== exactly the latest-wins row count — NOT double-counted, NOT a per-session 1)
    #   And stats.channel_counts reflects only the candidate row (the ghost row is excluded — session-scoped)
    def test_totals_latest_wins_not_double_counted(self):
        candidates = [_candidate("vidA", "Chan A", 900)]
        entries = [
            FeedbackEntry("2026-09-01", "vidA", "watched", "t", "digest", ""),
            FeedbackEntry("2026-09-02", "ghost", "watched", "t", "digest", ""),
            FeedbackEntry("2026-09-03", "vidS", "skipped", "t", "digest", "too long"),
        ]

        stats = aggregate_feedback(entries, candidates)

        # latest-wins: both watched rows survive (distinct video_ids: vidA, ghost) — not a per-session 1
        assert stats.totals["watched"] == 2
        assert stats.totals == {"watched": 2, "skipped": 1}
        # session-scoped: only the candidate row; both ghost rows (watched ghost + skipped ghost) are excluded
        assert stats.channel_counts == [("Chan A", 1, 0)]
        assert stats.skips_by_duration_band == {}

    # @unit [AC-4]
    # Scenario: Q1(b) latest-wins aggregation keeps the newest row per video
    #   Given feedback rows for video "abc" dated "2026-01-01" with state skipped and "2026-01-02" with state watched
    #   And candidates containing video "abc"
    #   When aggregate_feedback runs
    #   Then totals.watched is 1
    #   And totals.skipped is 0
    def test_latest_wins_per_video_id(self):
        candidates = [_candidate("abc", "Chan A", 900)]
        entries = [
            FeedbackEntry("2026-01-01", "abc", "skipped", "t", "digest", ""),
            FeedbackEntry("2026-01-02", "abc", "watched", "t", "digest", ""),
        ]

        stats = aggregate_feedback(entries, candidates)

        assert stats.totals.get("watched") == 1
        assert stats.totals.get("skipped", 0) == 0

    # @unit [AC-4]
    # Scenario: Q1(b) latest-wins tie-break favors the later input row
    #   Given two feedback rows for video "abc" dated "2026-01-02", one skipped then one watched
    #   And candidates containing video "abc"
    #   When aggregate_feedback runs
    #   Then totals.watched is 1
    #   And totals.skipped is 0
    def test_latest_wins_tie_later_row_wins(self):
        candidates = [_candidate("abc", "Chan A", 900)]
        entries = [
            FeedbackEntry("2026-01-02", "abc", "skipped", "t", "digest", ""),
            FeedbackEntry("2026-01-02", "abc", "watched", "t", "digest", ""),
        ]

        stats = aggregate_feedback(entries, candidates)

        assert stats.totals.get("watched") == 1
        assert stats.totals.get("skipped", 0) == 0

    # @unit [AC-4]
    # Scenario: Q1(b) ghost rows stay excluded from session-scoped stats
    #   Given a latest-wins feedback row for video "ghost" not present in candidates
    #   When aggregate_feedback runs
    #   Then channel_counts excludes "ghost"
    #   And skips_by_duration_band excludes "ghost"
    #   And totals still includes the latest-wins row
    def test_latest_wins_ghost_rows_excluded_from_scoped_stats(self):
        entries = [FeedbackEntry("2026-01-01", "ghost", "skipped", "t", "digest", "too long")]

        stats = aggregate_feedback(entries, [])

        assert stats.totals == {"skipped": 1}
        assert stats.channel_counts == []
        assert stats.skips_by_duration_band == {}

    # @unit [AC-4]
    # Scenario: Q2 feedback stats label uses latest-wins wording (reworked from T1-2; rendered via digest(), OAuth unset)
    #   Given non-empty feedback stats with skipped=1 and watched=2
    #   When the feedback stats lines are rendered
    #   Then the line "feedback (latest wins): skipped=1 watched=2" is present
    #   And the line "cumulative (all recorded)" is absent
    #   And the payload does NOT contain the bare label "totals:"
    async def test_feedback_stats_label_latest_wins(self, fake_store):
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
            [
                ("2026-09-01", "vidA", "watched", "t", "digest", ""),
                ("2026-09-02", "vidB", "watched", "t", "digest", ""),
                ("2026-09-03", "vidC", "skipped", "t", "digest", "too long"),
            ]
        )
        t = Tools()

        out = await t.digest()

        assert "feedback (latest wins): skipped=1 watched=2" in out
        assert "cumulative (all recorded)" not in out
        assert "totals:" not in out
