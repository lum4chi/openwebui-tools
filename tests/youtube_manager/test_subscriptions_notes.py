"""T3-1: deterministic subscription ok/failed tally + verbose raw detail + distinct not-configured/failed notes."""

import re
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import youtube_manager
from youtube_manager import SUBSCRIPTION_CHANNEL_CAP, Tools

from .conftest import guard_urlopen, playlist_item, sub_channel


def _http_error(code: int, reason: str) -> HttpError:
    return HttpError(MagicMock(status=code, reason=reason), b"")


def _stub_api(
    monkeypatch,
    channels: list[dict],
    uploads_by_channel: dict[str, str],
    items_by_uploads: dict[str, list[dict]],
    raise_for: dict[str, Exception] | None = None,
    details: dict[str, dict] | None = None,
) -> None:
    """Stateless _data_api_request responder for the per-channel subscriptions Data API path."""

    def fake(valves, method, params):
        if method == "subscriptions.list":
            return {"items": channels}
        if method == "channels.list":
            uploads = uploads_by_channel.get(params.get("id"))
            if uploads:
                return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": uploads}}}]}
            return {"items": []}
        if method == "playlistItems.list":
            playlist_id = params.get("playlistId")
            if raise_for is not None and playlist_id in raise_for:
                raise raise_for[playlist_id]
            return {"items": items_by_uploads.get(playlist_id, [])}
        if method == "videos.list":
            detail_map = details or {}
            ids = [vid for vid in str(params.get("ids", "")).split(",") if vid]
            return {"items": [detail_map[vid] for vid in ids if vid in detail_map]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr("youtube_manager._data_api_request", fake)


class TestSubscriptionNotes:
    """T3-1: deterministic ok/failed tally + verbose raw detail + distinct not-configured/failed notes."""

    # T3-1.A1 · workflow — 2 ok + 1 failed yields the deterministic candidate headline.
    #   Given OAuth is configured
    #   And the subscriptions list returns 3 channels
    #   And 2 channels' uploads lists return 1 entry each
    #   And 1 channel's playlistItems.list fails with HttpError 404
    #   When gather_candidates runs the subscriptions source
    #   Then the default subscriptions note is exactly
    #     "subscriptions: 2 ok, 1 failed, 2 candidates (e.g. channel UC2 → HTTP 404: Not Found)"
    def test_ok_and_failed_counts_reported(self, tools, monkeypatch):
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0"), sub_channel("UC1"), sub_channel("UC2")],
            uploads_by_channel={"UC0": "PU0", "UC1": "PU1", "UC2": "PU2"},
            items_by_uploads={
                "PU0": [playlist_item("V0", "V0", "C0", "2026-09-03T00:00:00Z")],
                "PU1": [playlist_item("V1", "V1", "C1", "2026-09-02T00:00:00Z")],
                "PU2": [],
            },
            raise_for={"PU2": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert len(cands) == 2
        assert notes == ["subscriptions: 2 ok, 1 failed, 2 candidates (e.g. channel UC2 → HTTP 404: Not Found)"]

    # T3-1.A2 · unit — channel selection is deterministic across shuffled raw orders.
    #   Given OAuth is configured
    #   And the subscriptions list returns more than SUBSCRIPTION_CHANNEL_CAP channels with identical publishedAt
    #   When _list_subscription_channels is invoked with shuffled raw channel orders
    #   Then the selected channels are identical across runs
    #   And the tie-break is channelId ascending
    def test_channel_order_deterministic_tiebreak(self, tools, monkeypatch):
        published = "2026-01-01T00:00:00Z"
        raw = [
            {"id": f"UC{i:04d}", "snippet": {"channelId": f"UC{i:04d}", "publishedAt": published}}
            for i in range(SUBSCRIPTION_CHANNEL_CAP + 5)
        ]

        def serve(order: list[int]) -> None:
            monkeypatch.setattr(
                youtube_manager,
                "_data_api_request",
                lambda valves, method, params: {"items": [raw[i] for i in order]},
            )

        serve(list(range(len(raw))))
        first = tools._list_subscription_channels()
        serve(list(reversed(range(len(raw)))))
        second = tools._list_subscription_channels()

        first_ids = [item["snippet"]["channelId"] for item in first]
        second_ids = [item["snippet"]["channelId"] for item in second]
        assert first_ids == second_ids
        assert len(first_ids) == SUBSCRIPTION_CHANNEL_CAP
        assert first_ids == sorted(first_ids)
        assert first_ids == [f"UC{i:04d}" for i in range(SUBSCRIPTION_CHANNEL_CAP)]

    # T3-1.A3 · workflow — identical inputs produce byte-identical headlines across runs.
    #   Given OAuth is configured
    #   And the subscriptions list and Data API outcomes are identical across two runs
    #   When gather_candidates runs the subscriptions source in both runs
    #   Then the default subscriptions note is byte-identical in both runs
    def test_headline_deterministic_across_runs(self, tools, monkeypatch):
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0"), sub_channel("UC1"), sub_channel("UC2")],
            uploads_by_channel={"UC0": "PU0", "UC1": "PU1", "UC2": "PU2"},
            items_by_uploads={
                "PU0": [playlist_item("V0", "V0", "C0", "2026-09-03T00:00:00Z")],
                "PU1": [playlist_item("V1", "V1", "C1", "2026-09-02T00:00:00Z")],
                "PU2": [],
            },
            raise_for={"PU2": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        notes_a: list[str] = []
        notes_b: list[str] = []

        tools._fetch_subscriptions(20, notes_a)
        tools._fetch_subscriptions(20, notes_b)

        assert notes_a == notes_b
        assert notes_a[0] == "subscriptions: 2 ok, 1 failed, 2 candidates (e.g. channel UC2 → HTTP 404: Not Found)"

    # T3-1.B1 · workflow — default note is a single-line diagnostic with the first-failure sample.
    #   Given OAuth is configured
    #   And 1 channel's playlistItems.list fails with HttpError 404
    #   And Valves.verbose is False
    #   When gather_candidates runs the subscriptions source
    #   Then the default note is one line with the first-failure sample, not a bare count
    #   And it does not contain "channel(s) failed:"
    def test_default_note_is_single_line_diagnostic(self, tools, monkeypatch):
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0")],
            uploads_by_channel={"UC0": "PU0"},
            items_by_uploads={"PU0": []},
            raise_for={"PU0": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        assert tools.valves.verbose is False
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == ["subscriptions: 0 ok, 1 failed (e.g. channel UC0 → HTTP 404: Not Found)"]
        assert "channel(s) failed:" not in "\n".join(notes)

    # T3-1.B2 · workflow — verbose note carries the per-reason detail.
    #   Given OAuth is configured
    #   And 1 channel's playlistItems.list fails with HttpError 404
    #   And Valves.verbose is True
    #   When gather_candidates runs the subscriptions source
    #   Then the note includes the friendly headline with the first-failure sample
    #   And it includes "channel UC0 → HTTP 404: Not Found"
    def test_verbose_note_has_raw_per_reason(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0")],
            uploads_by_channel={"UC0": "PU0"},
            items_by_uploads={"PU0": []},
            raise_for={"PU0": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert "subscriptions: 0 ok, 1 failed (e.g. channel UC0 → HTTP 404: Not Found)" in notes
        assert "channel UC0 → HTTP 404: Not Found" in notes

    # T3-1.B3 · unit — verbose is off by default.
    #   Given a Tools instance with default Valves
    #   When the Valves are read
    #   Then verbose is False
    def test_valves_default_verbose_false(self):
        t = Tools()
        assert t.valves.verbose is False

    # T3-1.C1 · workflow — OAuth unset emits the skip note only.
    #   Given OAuth is not configured
    #   When gather_candidates runs with watch_later and subscriptions
    #   Then the notes contain "watch_later skipped: OAuth not configured"
    #   And the notes contain "subscriptions skipped: OAuth not configured"
    #   And the notes do not contain "channel(s) failed:"
    #   And the notes do not contain "subscriptions: "
    def test_oauth_unset_emits_skip_note_only(self):
        t = Tools()
        notes: list[str] = []
        t._gather_one("watch_later", 20, "", notes)
        t._gather_one("subscriptions", 20, "", notes)
        assert "watch_later skipped: OAuth not configured" in notes
        assert "subscriptions skipped: OAuth not configured" in notes
        assert "channel(s) failed:" not in notes
        assert "subscriptions: " not in notes

    # T3-1.C2 · workflow — OAuth set + failing channel emits exactly one friendly line by default.
    #   Given OAuth is configured
    #   And the subscriptions list succeeds
    #   And 1 channel's playlistItems.list fails with HttpError 404
    #   And Valves.verbose is False
    #   When gather_candidates runs the subscriptions source
    #   Then the subscriptions note contains exactly one subscriptions summary line
    #   And that line matches the exact locked format "subscriptions: {ok} ok, {failed} failed (e.g. …)"
    def test_oauth_set_404_single_friendly_line(self, tools, monkeypatch):
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0")],
            uploads_by_channel={"UC0": "PU0"},
            items_by_uploads={"PU0": []},
            raise_for={"PU0": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 1
        assert re.fullmatch(r"subscriptions: \d+ ok, \d+ failed \(e\.g\. .+\)", notes[0])
        assert notes[0] == "subscriptions: 0 ok, 1 failed (e.g. channel UC0 → HTTP 404: Not Found)"

    # T3-1.C3 · workflow — unset OAuth and failed channels remain distinguishable.
    #   Given two otherwise identical scenarios
    #   And scenario A has OAuth unset
    #   And scenario B has OAuth set with one channel's playlistItems.list 404
    #   When gather_candidates runs each scenario
    #   Then scenario A notes contain "subscriptions skipped: OAuth not configured"
    #   And scenario B notes contain the subscriptions summary line with counts
    #   And scenario B notes do not contain "subscriptions skipped: OAuth not configured"
    def test_unset_vs_failed_distinct_notes(self, tools, monkeypatch):
        tools_a = Tools()
        notes_a: list[str] = []
        tools_a._gather_one("subscriptions", 20, "", notes_a)
        _stub_api(
            monkeypatch,
            channels=[sub_channel("UC0")],
            uploads_by_channel={"UC0": "PU0"},
            items_by_uploads={"PU0": []},
            raise_for={"PU0": _http_error(404, "Not Found")},
        )
        guard_urlopen(monkeypatch)
        notes_b: list[str] = []
        tools._gather_one("subscriptions", 20, "", notes_b)
        assert "subscriptions skipped: OAuth not configured" in notes_a
        assert "subscriptions: 0 ok, 1 failed (e.g. channel UC0 → HTTP 404: Not Found)" in notes_b
        assert "subscriptions skipped: OAuth not configured" not in notes_b
