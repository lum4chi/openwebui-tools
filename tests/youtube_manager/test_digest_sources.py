"""B4: digest path — OAuth-unset skipped-source notes, and RSS HTTP-status surfacing in the source notes."""

import email.message
import urllib.error
from collections.abc import Mapping

import youtube_manager
from youtube_manager import TasteProfile, Tools, _rss_url


def _channel(i: int) -> dict:
    return {
        "id": f"UC{i:04d}",
        "snippet": {
            "channelId": f"UC{i:04d}",
            "channelTitle": f"Chan {i}",
            "publishedAt": f"2026-01-{i + 1:02d}T00:00:00Z",
        },
    }


def _http_error(code: int, reason: str) -> urllib.error.HTTPError:
    """A real HTTP response error (RSS urlopen raises these for 4xx/5xx); hdrs/fp are unused here."""
    return urllib.error.HTTPError("https://www.youtube.com/feeds/atom.xml", code, reason, email.message.Message(), None)


def _stub_urlopen(monkeypatch, feeds: Mapping[str, Exception]) -> None:
    """Patch urllib.request.urlopen to raise the per-URL RSS outcome."""

    def fake(url, timeout=None):
        raise feeds[url]

    monkeypatch.setattr(youtube_manager.urllib.request, "urlopen", fake)


def _stub_api(monkeypatch, subscriptions_items: list[dict]) -> None:
    """Route channels.list -> no Watch Later, subscriptions.list -> the given items."""

    def fake(valves, method, params):
        if method == "channels.list":
            return {"items": []}
        if method == "subscriptions.list":
            return {"items": subscriptions_items}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)


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
    """T0-1: digest() surfaces the real RSS HTTP status in the source notes (not a bare "transient")."""

    # T0-1.8 · workflow · provenance: BDD Task T0-1 (R2-B1 "surface the real error")
    #   Given an OAuth-configured Tools with 1 subscription channel whose RSS feed fetch raises HTTP 404
    #   When digest() runs
    #   Then the payload's source notes contain "HTTP 404" (the real status), not a bare "transient"
    async def test_digest_surfaces_real_http_status(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, [_channel(0)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})

        out = await tools.digest()

        assert "HTTP 404" in out
        assert "transient" not in out
