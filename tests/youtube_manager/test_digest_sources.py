"""B4: digest path — OAuth-unset skipped-source notes, and Data API HTTP-status surfacing in the source notes."""

from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from youtube_manager import TasteProfile, Tools

from .conftest import api_fake, guard_urlopen, playlist_row, sub_channel, uploads_channel_reply


def _http_error(code: int, reason: str) -> HttpError:
    """A Google Data API HTTP error with the status/reason surfaced by _failure_reason."""
    return HttpError(MagicMock(status=code, reason=reason), b"")


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


class TestDigestErrorSurface:
    """T0-1: digest() surfaces the real Data API HTTP status in the source notes."""

    # T0-1.8 · workflow · provenance: BDD Task T0-1 (R2-B1 "surface the real error")
    #   Given an OAuth-configured Tools with 1 subscription channel whose uploads fetch raises HTTP 404
    #   When digest() runs
    #   Then the payload's source notes contain "HTTP 404" (the real status), not a bare "transient"
    async def test_digest_surfaces_real_http_status(self, tools, monkeypatch):
        tools.valves.verbose = True
        api_fake(
            monkeypatch,
            pages={"PLWL": [{"items": []}]},
            playlist_pages=[{"items": [playlist_row("PLWL", "Watch Later")]}],
            subscription_pages=[{"items": [sub_channel("UC0000", "Chan 0", "2026-01-01T00:00:00Z")]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
            raise_for_playlist={"PU0000": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)

        out = await tools.digest()

        assert "HTTP 404" in out
