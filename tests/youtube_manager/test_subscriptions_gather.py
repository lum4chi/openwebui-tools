"""T2: subscriptions as a gather/digest source — happy path, dedupe, OAuth guard, cap, default.

Scenarios T2-1..T2-7 (plan .opencode/plans/youtube-subscriptions.md); Gherkin preserved verbatim.
"""

import io
from collections.abc import Mapping
from unittest.mock import patch

import youtube_manager
from youtube_manager import NOTE_TASTE, ReauthNeeded, _rss_url

from .conftest import sample_taste_profile
from .test_resolution import _real_service

FEED_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">'
)


def _feed(entries: list[tuple[str, str, str]]) -> bytes:
    """Minimal Atom feed from (video_id, published, channel_id) triples (T1 entry shape)."""
    body = "".join(
        f"<entry><id>yt:video:{vid}</id><yt:videoId>{vid}</yt:videoId>"
        f"<yt:channelId>{chan}</yt:channelId><title>Video {vid}</title>"
        f"<author><name>Feed Chan</name></author><published>{published}</published></entry>"
        for vid, published, chan in entries
    )
    return (FEED_HEAD + body + "</feed>").encode()


def _stub_feeds(monkeypatch, feeds: Mapping[str, bytes]) -> list[str]:
    """Patch the RSS transport (urllib.request.urlopen); serve feed bytes per URL; record URLs."""
    calls: list[str] = []

    def fake(url, timeout=None):
        calls.append(url)
        return io.BytesIO(feeds[url])

    monkeypatch.setattr(youtube_manager.urllib.request, "urlopen", fake)
    return calls


def _api_fake(
    monkeypatch,
    channels: list[dict] | None = None,
    watch_later_items: list[dict] | None = None,
    details: dict[str, dict] | None = None,
    raise_for: dict[str, Exception] | None = None,
) -> list[tuple[str, dict]]:
    """Patch the _data_api_request seam; record calls as (method, params) pairs."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if raise_for is not None and method in raise_for:
            raise raise_for[method]
        if method == "subscriptions.list":
            return {"items": channels or []}
        if method == "channels.list":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"watchLater": "WL-1"}}}]}
        if method == "playlistItems.list":
            return {"items": watch_later_items or []}
        if method == "videos.list":
            return {"items": [(details or {}).get(i, _detail(i)) for i in params["ids"].split(",")]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


def _detail(video_id: str) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"Detail title {video_id}",
            "channelId": f"ch-{video_id}",
            "channelTitle": f"Detail channel {video_id}",
            "description": "",
            "tags": [],
            "publishedAt": "2026-09-01T12:00:00Z",
        },
        "contentDetails": {"duration": "PT2M35S"},
    }


def _ytdlp_fake(monkeypatch, flat: dict[str, list[str]], full: dict[str, dict]) -> list[str]:
    """Patch _ytdlp_extract: flat listings serve id-only rows, watch URLs serve full entries."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        if url in flat:
            return {"entries": [{"id": video_id} for video_id in flat[url]]}
        return full[url]

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _entry(video_id: str) -> dict:
    return {
        "id": video_id,
        "title": f"Feed title {video_id}",
        "uploader": f"Feed uploader {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 120,
        "view_count": 500,
        "upload_date": "20260910",
        "description": f"Feed description {video_id}",
        "tags": ["feed-tag"],
    }


def _clear_oauth(tools) -> None:
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


def _capture_candidates(monkeypatch) -> list[list]:
    """Wrap _candidates_payload; capture merged candidates per gather call."""
    captured: list[list] = []
    real = youtube_manager._candidates_payload

    def spy(candidates, notes):
        captured.append(list(candidates))
        return real(candidates, notes)

    monkeypatch.setattr(youtube_manager, "_candidates_payload", spy)
    return captured


class TestGatherSubscriptions:
    # T2-1 · workflow · provenance: AC-1 (same candidate path) + AC-2 (existing OAuth, no new valves)
    # Given OAuth valves configured (only the existing three google_* fields)
    #   and the real-client harness (discovery.build patched) routing "subscriptions.list"
    #   to a payload with 2 channels, and urlopen stubbed with 1-entry RSS per channel
    # When gather_candidates(sources="subscriptions") is called (no search_query)
    # Then the payload contains both subscription candidates, each with "subscriptions" in sources
    # And the harness call log contains ("subscriptions.list", ...) with mine "true" and part "snippet"
    # And the payload has no error text
    async def test_gather_happy_path_real_client(self, tools, monkeypatch):
        channels = [
            {"snippet": {"channelId": "UC1", "channelTitle": "One", "publishedAt": "2026-01-01T00:00:00Z"}},
            {"snippet": {"channelId": "UC2", "channelTitle": "Two", "publishedAt": "2026-02-01T00:00:00Z"}},
        ]
        feeds = {
            _rss_url("UC1"): _feed([("S1", "2026-09-12T10:00:00+00:00", "UC1")]),
            _rss_url("UC2"): _feed([("S2", "2026-09-11T09:00:00+00:00", "UC2")]),
        }
        _stub_feeds(monkeypatch, feeds)
        captured = _capture_candidates(monkeypatch)
        with (
            _real_service({"subscriptions.list": {"items": channels}}) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            payload = await tools.gather_candidates(sources="subscriptions")

        assert not payload.startswith("Error")
        assert "Video S1" in payload and "Video S2" in payload
        assert [c.video_id for c in captured[0]] == ["S1", "S2"]
        assert all("subscriptions" in c.sources for c in captured[0])
        method, params = calls[0]
        assert method == "subscriptions.list"
        assert params["mine"] == "true" and params["part"] == "snippet"

    # T2-2 · workflow · provenance: AC-1 (same path ⇒ same video_id dedup, first-seen wins)
    # Given sources="watch_later,subscriptions" with the same video_id present in both
    #   (watch_later via _data_api_request seam; subscriptions via urlopen stub)
    # When gather_candidates is called
    # Then exactly one candidate carries that video_id
    # And its sources contains both "watch_later" and "subscriptions" (union)
    # And first-seen ordering is unchanged (watch_later entry position kept)
    async def test_cross_source_dedupe_union(self, tools, monkeypatch):
        items = [{"contentDetails": {"videoId": "SHARED"}}, {"contentDetails": {"videoId": "WL2"}}]
        _api_fake(
            monkeypatch,
            channels=[{"snippet": {"channelId": "UC1", "channelTitle": "One"}}],
            watch_later_items=items,
            details={"SHARED": _detail("SHARED"), "WL2": _detail("WL2")},
        )
        _stub_feeds(monkeypatch, {_rss_url("UC1"): _feed([("SHARED", "2026-09-12T10:00:00+00:00", "UC1")])})
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later,subscriptions")

        assert not payload.startswith("Error")
        merged = captured[0]
        assert [c.video_id for c in merged] == ["SHARED", "WL2"]  # first-seen ordering unchanged
        shared = next(c for c in merged if c.video_id == "SHARED")
        assert shared.sources == ["watch_later", "subscriptions"]
        assert shared.title == "Detail title SHARED"  # first-seen (watch_later) wins

    # T2-5 · unit · provenance: AC-2 (existing OAuth gate; no new login surface)
    # Given OAuth valves NOT configured and sources="subscriptions"
    # When gather_candidates is called
    # Then the payload carries the note "subscriptions skipped: OAuth not configured"
    # And neither subscriptions.list nor urlopen is invoked, and no exception is raised
    async def test_oauth_guard_skip_note(self, tools, monkeypatch):
        _clear_oauth(tools)
        calls = _api_fake(monkeypatch)
        urls = _stub_feeds(monkeypatch, {})

        payload = await tools.gather_candidates(sources="subscriptions")

        assert not payload.startswith("Error")
        assert "subscriptions skipped: OAuth not configured" in payload
        assert calls == []
        assert urls == []

    # T2-6 · workflow · provenance: AC-1 (same path ⇒ per-source cap applies)
    # Given 3 channels × 2 RSS entries (published spread across channels) and max_per_source=3
    # When gather_candidates(sources="subscriptions") is called
    # Then exactly 3 subscription candidates are returned — the 3 newest by published
    async def test_max_per_source_caps_newest(self, tools, monkeypatch):
        channels = [
            {"snippet": {"channelId": "UCA", "channelTitle": "A", "publishedAt": "2026-01-01T00:00:00Z"}},
            {"snippet": {"channelId": "UCB", "channelTitle": "B", "publishedAt": "2026-01-02T00:00:00Z"}},
            {"snippet": {"channelId": "UCC", "channelTitle": "C", "publishedAt": "2026-01-03T00:00:00Z"}},
        ]
        feeds = {
            _rss_url("UCA"): _feed(
                [("A1", "2026-09-10T00:00:00+00:00", "UCA"), ("A2", "2026-09-09T00:00:00+00:00", "UCA")]
            ),
            _rss_url("UCB"): _feed(
                [("B1", "2026-09-12T00:00:00+00:00", "UCB"), ("B2", "2026-09-08T00:00:00+00:00", "UCB")]
            ),
            _rss_url("UCC"): _feed(
                [("C1", "2026-09-11T00:00:00+00:00", "UCC"), ("C2", "2026-09-07T00:00:00+00:00", "UCC")]
            ),
        }
        _api_fake(monkeypatch, channels=channels)
        _stub_feeds(monkeypatch, feeds)
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="subscriptions", max_per_source=3)

        assert not payload.startswith("Error")
        assert [c.video_id for c in captured[0]] == ["B1", "C1", "A1"]  # 3 newest by published

    # T2-7 · unit · provenance: [OPEN] — pins current behavior; user has not stated desired default (Open question 1)
    # Given a default gather_candidates call (sources omitted)
    # When it runs
    # Then subscriptions.list is NOT invoked (default remains "search" only)
    async def test_default_sources_excludes_subscriptions(self, tools, monkeypatch):
        calls = _api_fake(monkeypatch)
        urls = _stub_feeds(monkeypatch, {})
        ytdlp = _ytdlp_fake(
            monkeypatch,
            {"ytsearch20:rust async": ["dflt-1"]},
            {"https://www.youtube.com/watch?v=dflt-1": _entry("dflt-1")},
        )

        payload = await tools.gather_candidates(search_query="rust async")

        assert not payload.startswith("Error")
        assert ytdlp == [
            "ytsearch20:rust async",
            "https://www.youtube.com/watch?v=dflt-1",
        ]  # default sources = "search" only
        assert calls == []  # subscriptions.list NOT invoked
        assert urls == []


class TestDigestSubscriptions:
    # T2-3 · workflow · provenance: AC-1 ("surface among the candidates the digest works over")
    # Given a taste profile with zero topics, OAuth configured, fake_state seeded
    #   and subscriptions stubbed (2 entries) with watch_later healthy-but-empty
    # When digest() is called
    # Then the digest output contains both subscription video titles
    #   (fixture sized under any render display cap — verify render_digest's window when writing)
    # And the pre-merge source counts include subscriptions = 2
    async def test_digest_includes_subscription_titles(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile([], [])
        _api_fake(
            monkeypatch,
            channels=[{"snippet": {"channelId": "UC1", "channelTitle": "One"}}],
            watch_later_items=[],
            details={},
        )
        feeds = {
            _rss_url("UC1"): _feed(
                [("SUB1", "2026-09-12T10:00:00+00:00", "UC1"), ("SUB2", "2026-09-11T09:00:00+00:00", "UC1")]
            )
        }
        _stub_feeds(monkeypatch, feeds)

        payload = await tools.digest()

        assert not payload.startswith("REAUTH_NEEDED")
        assert "Video SUB1" in payload
        assert "Video SUB2" in payload
        assert "subscriptions=2" in payload

    # T2-4 · workflow · provenance: AC-2 + research #5 (existing reauth UX)
    # Given OAuth configured, watch_later healthy-but-empty
    #   and _data_api_request raising ReauthNeeded for "subscriptions.list"
    # When digest() is called
    # Then the payload starts with "REAUTH_NEEDED" (reauth block, same shape as the watch_later path)
    async def test_digest_reauth_block_on_subscription_failure(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile([], [])
        _api_fake(
            monkeypatch,
            channels=[{"snippet": {"channelId": "UC1", "channelTitle": "One"}}],
            watch_later_items=[],
            raise_for={"subscriptions.list": ReauthNeeded("Google credential rejected by the Data API")},
        )
        _stub_feeds(monkeypatch, {_rss_url("UC1"): _feed([("SUB1", "2026-09-12T10:00:00+00:00", "UC1")])})

        payload = await tools.digest()

        assert payload.startswith("REAUTH_NEEDED")
        assert "subscriptions failed: reauth" in payload
        assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload
