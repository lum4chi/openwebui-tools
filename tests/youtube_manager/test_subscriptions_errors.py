"""T0-1/T1-1: surface the real Data API HTTP status per failing channel + sample-in-headline."""

import urllib.error
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_manager import ReauthNeeded

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


def _quota_error() -> HttpError:
    body = b'{"error": {"message": "You have exceeded your quota.", "errors": [{"reason": "quotaExceeded"}]}}'
    return HttpError(MagicMock(status=403, reason="quotaExceeded"), body)


class TestSubscriptionsErrorSurface:
    """T0-1: Data API HTTP status surfaced in notes + one deduped line per distinct failure reason."""

    # T0-1.1/T0-1.2/T0-1.3 · unit — real HTTP status is surfaced in the verbose per-channel line.
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 404 error (T0-1.1)
    #   When gather_candidates runs the subscriptions source
    #   Then the per-channel line is "channel UC0000 → HTTP 404: Not Found"
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 429 error (T0-1.2)
    #   When gather_candidates runs the subscriptions source
    #   Then the per-channel line is "channel UC0000 → HTTP 429: Too Many Requests"
    #   Given a subscriptions channel whose playlistItems.list raises an HTTP 503 error (T0-1.3)
    #   When gather_candidates runs the subscriptions source
    #   Then the per-channel line is "channel UC0000 → HTTP 503: Service Unavailable"
    #   Given exactly 1 channel failing with HTTP 404 (T0-1.6, subsumed by the 404 case above)
    #   When gather_candidates runs the subscriptions source
    #   Then the headline carries the sample and exactly one per-channel line is emitted
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
            f"subscriptions: 0 ok, 1 failed (e.g. channel UC0000 → HTTP {code}: {reason})",
            f"channel UC0000 → HTTP {code}: {reason}",
        ]

    # T0-1.4 · unit — a genuine URLError has no HTTP status and stays classified transient.
    #   Given a subscriptions channel whose playlistItems.list raises a URLError with no HTTP response
    #   When gather_candidates runs the subscriptions source
    #   Then the per-channel line still classifies as "transient" (connectivity failure — no status to surface)
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
        assert notes == [
            "subscriptions: 0 ok, 1 failed (e.g. channel UC0000 → transient)",
            "channel UC0000 → transient",
        ]

    # T0-1.5 · unit — 25 failing channels: headline sample + one per-channel line each, in channel order.
    #   Given 25 subscription channels failing under 3 distinct error reasons
    #   When gather_candidates runs the subscriptions source
    #   Then the headline carries the first-failure sample (channel UC0024 — newest published first)
    #   And one "channel <id> → <reason>" line is emitted per failed channel
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
        per_channel = [f"channel UC{i:04d} → HTTP {_reason_for(i)[0]}: {_reason_for(i)[1]}" for i in range(24, -1, -1)]
        headline = "subscriptions: 0 ok, 25 failed (e.g. channel UC0024 → HTTP 503: Service Unavailable)"
        assert notes == [headline, *per_channel]

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

    # S5 [unit] — AC suggestion 1 (verbatim example shape) + suggestion 3 (one-line diagnostic in the source note)
    # Scenario: all-fail run surfaces the real per-channel error with verbose OFF
    #   Given 25 channels whose playlistItems.list all raise HttpError 403 with quotaExceeded body
    #   And verbose is False (default)
    #   When gather_candidates(sources="subscriptions") runs
    #   Then notes[0] is "subscriptions: 0 ok, 25 failed (e.g. channel UCfirst → HTTP 403:
    #     <error.message> (quotaExceeded))"
    #   Using the first failed channel's real id and the API error text — never a bare count
    def test_all_fail_run_surfaces_real_per_channel_error(self, tools, monkeypatch):
        channels = [_channel(i) for i in range(25)]
        api_fake(
            monkeypatch,
            pages={},
            subscription_pages=[{"items": channels}],
            channels_by_id={f"UC{i:04d}": uploads_channel_reply(f"PU{i:04d}") for i in range(25)},
            raise_for_playlist={f"PU{i:04d}": _quota_error() for i in range(25)},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        sample = "HTTP 403: You have exceeded your quota. (quotaExceeded)"
        assert notes == [f"subscriptions: 0 ok, 25 failed (e.g. channel UC0024 → {sample})"]

    # S6 [unit] — AC suggestion 1
    # Scenario: mixed ok/failed run carries the first-failure sample
    #   Given 23 healthy channels and 2 failing (HTTP 403 then HTTP 404)
    #   When gather_candidates(sources="subscriptions") runs
    #   Then the healthy channels' candidates are returned
    #   And the note line is "subscriptions: 23 ok, 2 failed, <k> candidates (e.g. channel
    #     <first-failed-cid> → HTTP 403: …)"
    #   With the sample naming the first failed channel in channel order
    def test_mixed_run_carries_first_failure_sample(self, tools, monkeypatch):
        pages = {
            f"PU{i:04d}": [
                {"items": [playlist_item(f"V{i:04d}", f"V{i:04d}", f"C{i:04d}", f"2026-09-{i + 1:02d}T00:00:00Z")]}
            ]
            for i in range(23)
        }
        api_fake(
            monkeypatch,
            pages=pages,
            subscription_pages=[{"items": [_channel(i) for i in range(25)]}],
            channels_by_id={f"UC{i:04d}": uploads_channel_reply(f"PU{i:04d}") for i in range(25)},
            raise_for_playlist={"PU0024": _http_error(403, "Forbidden"), "PU0023": _http_error(404, "Not Found")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert len(cands) == 20
        assert notes == ["subscriptions: 23 ok, 2 failed, 20 candidates (e.g. channel UC0024 → HTTP 403: Forbidden)"]

    # S8 [unit] — AC suggestion 1 ("at least the first N failed channels")
    # Scenario: verbose mode lists every failed channel
    #   Given 3 failing channels with distinct reasons (HTTP 403, HTTP 404, reauth) and verbose True
    #   When gather_candidates(sources="subscriptions") runs
    #   Then the notes contain one line per failed channel "channel <cid> → <reason>"
    #   And the headline still carries the first-failure sample
    def test_verbose_lists_every_failed_channel(self, tools, monkeypatch):
        tools.valves.verbose = True
        api_fake(
            monkeypatch,
            pages={},
            subscription_pages=[{"items": [_channel(0), _channel(1), _channel(2)]}],
            channels_by_id={
                "UC0000": uploads_channel_reply("PU0000"),
                "UC0001": uploads_channel_reply("PU0001"),
                "UC0002": uploads_channel_reply("PU0002"),
            },
            raise_for_playlist={
                "PU0000": _http_error(403, "Forbidden"),
                "PU0001": _http_error(404, "Not Found"),
                "PU0002": ReauthNeeded("invalid_grant"),
            },
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == [
            "subscriptions: 0 ok, 3 failed (e.g. channel UC0002 → reauth)",
            "channel UC0002 → reauth",
            "channel UC0001 → HTTP 404: Not Found",
            "channel UC0000 → HTTP 403: Forbidden",
        ]
