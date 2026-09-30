"""T2: subscriptions as a gather/digest source — happy path, dedupe, OAuth guard, cap, default."""

import youtube_manager
from youtube_manager import NOTE_TASTE, ReauthNeeded

from .conftest import guard_urlopen, playlist_row, sample_taste_profile
from .conftest import playlist_item as pi
from .conftest import sub_channel as sc
from .conftest import video_detail as vd


def _api_fake(
    monkeypatch,
    channels=None,
    watch_later_items=None,
    uploads_by_channel=None,
    uploads_pages=None,
    details=None,
    raise_for=None,
):
    """Patch the _data_api_request seam; record calls as (method, params) pairs."""
    calls = []

    def fake(valves, method, params, user_id=None):
        calls.append((method, dict(params)))
        if raise_for is not None and method in raise_for:
            raise raise_for[method]
        if method == "subscriptions.list":
            return {"items": channels or []}
        if method == "channels.list":
            uploads = (uploads_by_channel or {}).get(params.get("id"))
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": uploads}}}] if uploads else []}
        if method == "playlists.list":
            return {"items": [playlist_row("PLWL", "Watch Later")]}
        if method == "playlistItems.list":
            if params.get("playlistId") == "PLWL":
                return {"items": watch_later_items or []}
            return {"items": (uploads_pages or {}).get(params.get("playlistId"), [])}
        if method == "videos.list":
            detail_map = details or {}
            ids = [vid for vid in str(params.get("id", "")).split(",") if vid]
            return {"items": [detail_map[vid] for vid in ids if vid in detail_map]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


def _detail(vid: str) -> dict:
    snippet = {"title": f"Detail title {vid}", "channelTitle": "Detail channel", "publishedAt": "2026-09-01T12:00:00Z"}
    return {"id": vid, "snippet": snippet, "contentDetails": {"duration": "PT2M35S"}}


def _ytdlp_fake(monkeypatch, flat, full):
    """Patch _ytdlp_extract: flat listings serve id-only rows, watch URLs serve full entries."""
    calls = []

    def fake(url, extra=None):
        calls.append(url)
        if url in flat:
            return {"entries": [{"id": vid} for vid in flat[url]]}
        return full[url]

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _entry(vid: str) -> dict:
    row = {"id": vid, "title": f"T {vid}", "uploader": f"U {vid}", "duration": 120, "view_count": 500}
    row.update(upload_date="20260910", description=f"D {vid}", tags=[])
    return row


def _clear_oauth(tools) -> None:
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


def _capture_candidates(monkeypatch):
    """Wrap _candidates_payload; capture merged candidates per gather call."""
    captured = []
    real = youtube_manager._candidates_payload

    def spy(candidates, notes):
        captured.append(list(candidates))
        return real(candidates, notes)

    monkeypatch.setattr(youtube_manager, "_candidates_payload", spy)
    return captured


def _page(*items):
    return list(items)


class TestGatherSubscriptions:
    # T2-1 Given OAuth configured + Data API harness; When gather subscriptions; Then both candidates and subscriptions.list called
    async def test_gather_happy_path_real_client(self, tools, monkeypatch):
        calls = _api_fake(
            monkeypatch,
            channels=[sc("UC1", "One"), sc("UC2", "Two")],
            uploads_by_channel={"UC1": "PU1", "UC2": "PU2"},
            uploads_pages={
                "PU1": _page(pi("S1", "S1", "One", "2026-09-12T10:00:00Z")),
                "PU2": _page(pi("S2", "S2", "Two", "2026-09-11T09:00:00Z")),
            },
            details={"S1": vd("S1", title="Video S1"), "S2": vd("S2", title="Video S2")},
        )
        guard_urlopen(monkeypatch)
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="subscriptions")

        assert not payload.startswith("Error")
        assert "Video S1" in payload and "Video S2" in payload
        assert [c.video_id for c in captured[0]] == ["S1", "S2"]
        assert all("subscriptions" in c.sources for c in captured[0])
        method, params = calls[0]
        assert method == "subscriptions.list"
        assert params["mine"] == "true" and params["part"] == "snippet"

    # @unit
    # Scenario T1-4-S5 (unit): a malformed video in a subscription channel batch is skipped within the channel
    #   Given a subscription channel whose videos.list batch holds one healthy video and one malformed item
    #   When gather_candidates is called with sources "subscriptions"
    #   Then no exception escapes gather_candidates
    #   And the healthy video is still returned as a candidate for that feed
    #   And the skip is reported via the notes and the per-channel failure reporting for channel-level errors is unchanged
    async def test_malformed_channel_video_skipped_within_channel(self, tools, monkeypatch):
        _api_fake(
            monkeypatch,
            channels=[sc("UC1", "One")],
            uploads_by_channel={"UC1": "PU1"},
            uploads_pages={
                "PU1": _page(
                    pi("S1", "S1", "One", "2026-09-12T10:00:00Z"),
                    pi("S2", "S2", "One", "2026-09-11T09:00:00Z"),
                )
            },
            details={"S1": vd("S1", title="Video S1"), "S2": vd("S2", title="Video S2", views="not-a-number")},
        )
        guard_urlopen(monkeypatch)
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="subscriptions")

        assert not payload.startswith("Error")
        assert [c.video_id for c in captured[0]] == ["S1"]
        assert "subscriptions: 1 ok, 0 failed, 1 candidates" in payload
        assert "subscriptions skipped 1 video(s): S2 (ValueError)" in payload

    # T2-2 Given same video id in watch_later and subscriptions; When gather both; Then one candidate, union sources, first-seen wins
    async def test_cross_source_dedupe_union(self, tools, monkeypatch):
        _api_fake(
            monkeypatch,
            channels=[sc("UC1", "One")],
            watch_later_items=[{"contentDetails": {"videoId": "SHARED"}}, {"contentDetails": {"videoId": "WL2"}}],
            uploads_by_channel={"UC1": "PU1"},
            uploads_pages={"PU1": _page(pi("SHARED", "Shared", "One", "2026-09-12T10:00:00Z"))},
            details={"SHARED": _detail("SHARED"), "WL2": _detail("WL2")},
        )
        guard_urlopen(monkeypatch)
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="watch_later,subscriptions")

        assert not payload.startswith("Error")
        merged = captured[0]
        assert [c.video_id for c in merged] == ["SHARED", "WL2"]
        shared = next(c for c in merged if c.video_id == "SHARED")
        assert shared.sources == ["watch_later", "subscriptions"]
        assert shared.title == "Detail title SHARED"

    # T2-5 Given OAuth NOT configured; When gather subscriptions; Then skip note and no API/urlopen calls
    async def test_oauth_guard_skip_note(self, tools, monkeypatch):
        _clear_oauth(tools)
        calls = _api_fake(monkeypatch)
        guard_urlopen(monkeypatch)

        payload = await tools.gather_candidates(sources="subscriptions")

        assert not payload.startswith("Error")
        assert "subscriptions skipped: OAuth not configured" in payload
        assert calls == []

    # T2-6 Given 3 channels × 2 uploads and max_per_source=3; When gather subscriptions; Then 3 newest candidates
    async def test_max_per_source_caps_newest(self, tools, monkeypatch):
        a1 = pi("A1", "A1", "A", "2026-09-10T00:00:00Z")
        a2 = pi("A2", "A2", "A", "2026-09-09T00:00:00Z")
        b1 = pi("B1", "B1", "B", "2026-09-12T00:00:00Z")
        b2 = pi("B2", "B2", "B", "2026-09-08T00:00:00Z")
        c1 = pi("C1", "C1", "C", "2026-09-11T00:00:00Z")
        c2 = pi("C2", "C2", "C", "2026-09-07T00:00:00Z")
        _api_fake(
            monkeypatch,
            channels=[sc("UCA", "A"), sc("UCB", "B"), sc("UCC", "C")],
            uploads_by_channel={"UCA": "PUA", "UCB": "PUB", "UCC": "PUC"},
            uploads_pages={"PUA": _page(a1, a2), "PUB": _page(b1, b2), "PUC": _page(c1, c2)},
            details={},
        )
        guard_urlopen(monkeypatch)
        captured = _capture_candidates(monkeypatch)

        payload = await tools.gather_candidates(sources="subscriptions", max_per_source=3)

        assert not payload.startswith("Error")
        assert [c.video_id for c in captured[0]] == ["B1", "C1", "A1"]

    # T2-7 Given a default gather_candidates call; When it runs; Then subscriptions.list is NOT invoked
    async def test_default_sources_excludes_subscriptions(self, tools, monkeypatch):
        calls = _api_fake(monkeypatch)
        guard_urlopen(monkeypatch)
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
        ]
        assert calls == []


class TestDigestSubscriptions:
    # T2-3 Given taste profile, OAuth configured, subscriptions stubbed (2), watch_later empty; When digest; Then both titles
    async def test_digest_includes_subscription_titles(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile([], [])
        _api_fake(
            monkeypatch,
            channels=[sc("UC1", "One")],
            watch_later_items=[],
            uploads_by_channel={"UC1": "PU1"},
            uploads_pages={
                "PU1": _page(
                    pi("SUB1", "SUB1", "One", "2026-09-12T10:00:00Z"), pi("SUB2", "SUB2", "One", "2026-09-11T09:00:00Z")
                )
            },
            details={"SUB1": vd("SUB1", title="Video SUB1"), "SUB2": vd("SUB2", title="Video SUB2")},
        )
        guard_urlopen(monkeypatch)

        payload = await tools.digest()

        assert not payload.startswith("REAUTH_NEEDED")
        assert "Video SUB1" in payload
        assert "Video SUB2" in payload
        assert "subscriptions=2" in payload

    # T2-4 / T8-5 S2 Given watch_later healthy and subscriptions ReauthNeeded; When digest; Then REAUTH_NEEDED plus healthy payload
    async def test_digest_reauth_block_on_subscription_failure(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile([], [])
        _api_fake(
            monkeypatch,
            channels=[sc("UC1", "One")],
            watch_later_items=[],
            raise_for={"subscriptions.list": ReauthNeeded("Google credential rejected by the Data API")},
        )
        guard_urlopen(monkeypatch)

        payload = await tools.digest()

        assert payload.startswith("REAUTH_NEEDED")
        assert "subscriptions failed: reauth" in payload
        assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload
        assert "=== Candidates (" in payload
