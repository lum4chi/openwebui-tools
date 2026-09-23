"""T0-1: surface the real Data API HTTP status + dedup to one line per distinct reason."""

import urllib.error
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from .conftest import api_fake, guard_urlopen, playlist_item, sub_channel, uploads_channel_reply


def _http_error(code: int, reason: str) -> HttpError:
    return HttpError(MagicMock(status=code, reason=reason), b"")


def _channel(i: int) -> dict:
    return sub_channel(f"UC{i:04d}", published=f"2026-01-{i + 1:02d}T00:00:00Z")


def _reason_for(i: int) -> tuple[int, str]:
    """3 distinct reasons across the 25 channels: i>=15 -> 503, 5<=i<15 -> 429, i<5 -> 404."""
    if i >= 15:
        return 503, "Service Unavailable"
    if i >= 5:
        return 429, "Too Many Requests"
    return 404, "Not Found"


class TestSubscriptionsErrorSurface:
    """T0-1: Data API HTTP status surfaced in notes + one deduped line per distinct failure reason."""

    # T0-1.1/T0-1.2/T0-1.3 · unit — real HTTP status is surfaced in the verbose failure line.
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 404 error (T0-1.1)
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 404" and the reason phrase
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 429 error (T0-1.2)
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 429" and the reason phrase
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 503 error (T0-1.3)
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 503" and the reason phrase
    #   Given exactly 1 channel failing with HTTP 404 (T0-1.6, subsumed by the 404 case above)
    #   When gather_candidates runs the subscriptions source
    #   Then exactly 1 failure line "1 channel(s) failed: transient HTTP 404: Not Found" is emitted
    @pytest.mark.parametrize(
        ("code", "reason"),
        [(404, "Not Found"), (429, "Too Many Requests"), (503, "Service Unavailable")],
    )
    def test_http_status_surfaces_real_status(self, tools, monkeypatch, code: int, reason: str):
        tools.valves.verbose = True
        api_fake(
            monkeypatch,
            pages={"PU0000": [{"items": []}]},
            subscription_pages=[{"items": [_channel(0)]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
            raise_for_playlist={"PU0000": _http_error(code, reason)},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == [
            "subscriptions: 0 ok, 1 failed",
            f"1 channel(s) failed: transient HTTP {code}: {reason}",
        ]

    # T0-1.4 · unit — a genuine URLError has no HTTP status and stays classified transient.
    #   Given a subscriptions channel whose playlistItems.list raises a URLError with no HTTP response
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line still classifies as "transient" (connectivity failure — no status to surface)
    def test_genuine_urlerror_stays_transient(self, tools, monkeypatch):
        tools.valves.verbose = True
        api_fake(
            monkeypatch,
            pages={"PU0000": [{"items": []}]},
            subscription_pages=[{"items": [_channel(0)]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
            raise_for_playlist={"PU0000": urllib.error.URLError("connect boom")},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == ["subscriptions: 0 ok, 1 failed", "1 channel(s) failed: transient"]

    # T0-1.5 · unit — 25 failing channels dedup to one line per distinct reason.
    #   Given 25 subscription channels failing under 3 distinct error reasons
    #   When gather_candidates runs the subscriptions source
    #   Then exactly 3 failure lines are emitted, one per distinct reason
    #   And each line is prefixed with its channel count (e.g. "5 channel(s) failed: transient HTTP 404: Not Found")
    #   And the 25-channel total is preserved (nothing lost, nothing per-channel duplicated)
    def test_dedup_one_line_per_distinct_reason(self, tools, monkeypatch):
        tools.valves.verbose = True
        channels = [_channel(i) for i in range(25)]
        api_fake(
            monkeypatch,
            pages={},
            subscription_pages=[{"items": channels}],
            channels_by_id={f"UC{i:04d}": uploads_channel_reply(f"PU{i:04d}") for i in range(25)},
            raise_for_playlist={f"PU{i:04d}": _http_error(*_reason_for(i)) for i in range(25)},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == [
            "subscriptions: 0 ok, 25 failed",
            "10 channel(s) failed: transient HTTP 503: Service Unavailable",
            "10 channel(s) failed: transient HTTP 429: Too Many Requests",
            "5 channel(s) failed: transient HTTP 404: Not Found",
        ]

    # T0-1.7 · unit — healthy channels return candidates without failure lines.
    #   Given subscription channels whose uploads lists return entries cleanly
    #   When gather_candidates runs the subscriptions source
    #   Then their candidates are returned and no failure lines are emitted
    def test_healthy_channels_no_failure_lines(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={
                "PU0000": [{"items": [playlist_item("V0", "V0", "C0", "2026-09-03T00:00:00Z")]}],
                "PU0001": [{"items": [playlist_item("V1", "V1", "C1", "2026-09-01T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [sub_channel("UC0000"), sub_channel("UC0001")]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000"), "UC0001": uploads_channel_reply("PU0001")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert [c.video_id for c in cands] == ["V0", "V1"]
        assert notes == ["subscriptions: 2 ok, 0 failed, 2 candidates"]
