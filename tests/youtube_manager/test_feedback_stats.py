"""B2 relabel: feedback stats `totals` are cumulative (all recorded); channels/bands are session-scoped."""

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
    """B2: `stats.totals` is cumulative (every recorded row), `channel_counts`/bands are candidate-scoped."""

    # T1-1 · unit · provenance: AC-1 (totals are cumulative-by-design, NOT a double-count; scoped parts exclude ghost rows)
    #   Given a feedback log with two "watched" rows (one id present in the current candidates,
    #         one a stale/ghost id) and one "skipped" row
    #   When aggregate_feedback(rows, candidates) runs
    #   Then stats.totals["watched"] == 2   (== exactly the row count — NOT double-counted, NOT a per-session 1)
    #   And stats.channel_counts reflects only the candidate row (the ghost row is excluded — session-scoped)
    def test_totals_cumulative_not_double_counted(self):
        candidates = [_candidate("vidA", "Chan A", 900)]
        entries = [
            FeedbackEntry("2026-09-01", "vidA", "watched", "t", "digest", ""),
            FeedbackEntry("2026-09-02", "ghost", "watched", "t", "digest", ""),
            FeedbackEntry("2026-09-03", "vidS", "skipped", "t", "digest", "too long"),
        ]

        stats = aggregate_feedback(entries, candidates)

        # cumulative: BOTH watched rows counted (the ghost watched row included) — not a per-session 1, not double-counted
        assert stats.totals["watched"] == 2
        assert stats.totals == {"watched": 2, "skipped": 1}
        # session-scoped: only the candidate row; both ghost rows (watched ghost + skipped ghost) are excluded
        assert stats.channel_counts == [("Chan A", 1, 0)]
        assert stats.skips_by_duration_band == {}

    # T1-2 · workflow · provenance: AC-1 (relabel: cumulative label present, bare "totals:" gone)
    #   Given a feedback log with 2 "watched" + 1 "skipped" rows, OAuth unset (no candidates -> all rows are cumulative-only)
    #   When digest() runs
    #   Then the payload contains "cumulative (all recorded): skipped=1 watched=2"
    #   And the payload does NOT contain the bare label "totals:"
    async def test_digest_relabels_cumulative(self, fake_store):
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
            [
                ("2026-09-01", "vidA", "watched", "t", "digest", ""),
                ("2026-09-02", "vidB", "watched", "t", "digest", ""),
                ("2026-09-03", "vidC", "skipped", "t", "digest", "too long"),
            ]
        )
        t = Tools()

        out = await t.digest()

        assert "cumulative (all recorded): skipped=1 watched=2" in out
        assert "totals:" not in out
