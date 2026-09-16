"""B4: digest path reports the two OAuth-gated sources (watch_later, subscriptions) as skipped when OAuth is unset."""

from youtube_manager import TasteProfile, Tools


class TestDigestSources:
    """B4: `_digest_sources` else-branch — OAuth unset → both gated sources reported as skipped."""

    # T2-1 · workflow · provenance: AC-2 (OAuth unset → digest reports both gated sources as skipped)
    #   Given a Tools() with OAuth unset (default Valves) and an empty state store
    #   When digest() runs
    #   Then the payload contains "watch_later skipped: OAuth not configured"
    #   And the payload contains "subscriptions skipped: OAuth not configured"
    #   And the payload contains "=== Source notes ==="
    async def test_digest_reports_skipped_sources_oauth_unset(self, fake_store):
        t = Tools()  # bare, OAuth unset (default Valves); store seeded with nothing

        out = await t.digest()

        assert "watch_later skipped: OAuth not configured" in out
        assert "subscriptions skipped: OAuth not configured" in out
        assert "=== Source notes ===" in out

    # T2-2 · unit · provenance: AC-2 (pure: _digest_sources returns the two notes + empty source_counts)
    #   Given a Tools() with OAuth unset and a TasteProfile(set(), "") (post-batch-1 shape)
    #   When _digest_sources(profile) runs
    #   Then notes == ["watch_later skipped: OAuth not configured", "subscriptions skipped: OAuth not configured"]
    #   And source_counts == {}   (no candidates)
    def test_digest_sources_notes_oauth_unset(self):
        t = Tools()  # bare, OAuth unset (default Valves)
        profile = TasteProfile(set(), "")  # post-batch-1 shape: (disliked, text)

        batches, source_counts, notes, reauth = t._digest_sources(profile)

        assert notes == [
            "watch_later skipped: OAuth not configured",
            "subscriptions skipped: OAuth not configured",
        ]
        assert source_counts == {}  # no candidates
        assert batches == []
        assert reauth == set()
