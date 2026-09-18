"""T3-1: deterministic subscription ok/failed tally + verbose raw detail + distinct not-configured/failed notes.

Drives the subscriptions source (``_fetch_subscriptions`` / ``_gather_one``) and asserts on the emitted
note lines. BDD: plan ``.opencode/plans/youtube-production-readiness.md`` · Task T3-1 (Bug #1 · UX-1 · UX-2).
"""

import email.message
import re
import urllib.error
from collections.abc import Mapping

import youtube_manager
from youtube_manager import SUBSCRIPTION_CHANNEL_CAP, Tools, _rss_url

FEED_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
    'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
)


def _entry_feed(entry_xml: str) -> bytes:
    return (FEED_HEAD + entry_xml + "</feed>").encode()


def _one_entry_feed(video_id: str, published: str, channel_id: str) -> bytes:
    return _entry_feed(
        "<entry>"
        f"<id>yt:video:{video_id}</id><yt:videoId>{video_id}</yt:videoId>"
        f"<yt:channelId>{channel_id}</yt:channelId>"
        f"<title>Video {video_id}</title>"
        "<author><name>Feed Chan</name></author>"
        f"<published>{published}</published>"
        f'<media:group><media:content url="https://example.com/{video_id}" type="video"/>'
        f"<media:description>desc {video_id}</media:description></media:group>"
        "</entry>"
    )


class _FakeResp:
    """urlopen answer: file-like read() + context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code: int, reason: str) -> urllib.error.HTTPError:
    """A real HTTP response error (RSS urlopen raises these for 4xx/5xx); hdrs/fp are unused here."""
    return urllib.error.HTTPError("https://www.youtube.com/feeds/atom.xml", code, reason, email.message.Message(), None)


def _channel(i: int) -> dict:
    return {
        "id": f"UC{i:04d}",
        "snippet": {
            "channelId": f"UC{i:04d}",
            "channelTitle": f"Chan {i}",
            "publishedAt": f"2026-01-{i + 1:02d}T00:00:00Z",
        },
    }


def _stub_urlopen(monkeypatch, feeds: Mapping[str, bytes | Exception]) -> list[str]:
    """Patch urllib.request.urlopen to serve feed bytes per URL (or raise); record URLs."""
    calls: list[str] = []

    def fake(url, timeout=None):
        calls.append(url)
        outcome = feeds[url]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResp(outcome)

    monkeypatch.setattr(youtube_manager.urllib.request, "urlopen", fake)
    return calls


def _stub_api(monkeypatch, items: list[dict]) -> None:
    """Patch youtube_manager._data_api_request; subscriptions.list replies with the given items."""

    def fake(valves, method, params):
        if method != "subscriptions.list":
            raise AssertionError(f"unexpected API method {method}")
        return {"items": items}

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)


class TestSubscriptionNotes:
    """T3-1: deterministic ok/failed tally + verbose raw detail + distinct not-configured/failed notes."""

    # T3-1.A1 · workflow · provenance: Bug #1 (3) "report succeeded and failed counts"
    #   Given OAuth is configured
    #   And the subscriptions list returns 3 channels
    #   And 2 channel RSS feeds succeed
    #   And 1 channel RSS feed fails with HTTP 404
    #   When gather_candidates runs the subscriptions source
    #   Then the default subscriptions note is exactly "subscriptions: 2 ok, 1 failed"
    def test_ok_and_failed_counts_reported(self, tools, monkeypatch):
        channels = [_channel(i) for i in range(3)]
        _stub_api(monkeypatch, channels)
        _stub_urlopen(
            monkeypatch,
            {
                _rss_url("UC0000"): _one_entry_feed("V0", "2026-09-03", "UC0000"),
                _rss_url("UC0001"): _one_entry_feed("V1", "2026-09-02", "UC0001"),
                _rss_url("UC0002"): _http_error(404, "Not Found"),
            },
        )
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert len(cands) == 2
        assert notes == ["subscriptions: 2 ok, 1 failed"]

    # T3-1.A2 · unit · provenance: Bug #1 (2) "make the count deterministic (set-based)"
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
        assert first_ids == second_ids  # identical across runs
        assert len(first_ids) == SUBSCRIPTION_CHANNEL_CAP
        assert first_ids == sorted(first_ids)  # tie-break is channelId ascending
        assert first_ids == [f"UC{i:04d}" for i in range(SUBSCRIPTION_CHANNEL_CAP)]

    # T3-1.A3 · workflow · provenance: Bug #1 (1)+(3) deterministic headline for identical inputs
    #   Given OAuth is configured
    #   And the subscriptions list and RSS outcomes are identical across two runs
    #   When gather_candidates runs the subscriptions source in both runs
    #   Then the default subscriptions note is byte-identical in both runs
    def test_headline_deterministic_across_runs(self, tools, monkeypatch):
        channels = [_channel(i) for i in range(3)]
        _stub_api(monkeypatch, channels)
        _stub_urlopen(
            monkeypatch,
            {
                _rss_url("UC0000"): _one_entry_feed("V0", "2026-09-03", "UC0000"),
                _rss_url("UC0001"): _one_entry_feed("V1", "2026-09-02", "UC0001"),
                _rss_url("UC0002"): _http_error(404, "Not Found"),
            },
        )
        notes_a: list[str] = []
        notes_b: list[str] = []

        tools._fetch_subscriptions(20, notes_a)
        tools._fetch_subscriptions(20, notes_b)

        assert notes_a == notes_b  # byte-identical headline
        assert notes_a[0] == "subscriptions: 2 ok, 1 failed"

    # T3-1.B1 · workflow · provenance: UX-1 (friendly wrapper; raw detail hidden by default)
    #   Given OAuth is configured
    #   And 1 channel RSS feed fails with HTTP 404
    #   And Valves.verbose is False
    #   When gather_candidates runs the subscriptions source
    #   Then the default subscriptions note does not contain "HTTP 404"
    #   And it does not contain "channel(s) failed:"
    def test_default_note_has_no_raw_status(self, tools, monkeypatch):
        _stub_api(monkeypatch, [_channel(0)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        assert tools.valves.verbose is False
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == ["subscriptions: 0 ok, 1 failed"]
        joined = "\n".join(notes)
        assert "HTTP 404" not in joined
        assert "channel(s) failed:" not in joined

    # T3-1.B2 · workflow · provenance: UX-1 (raw per-reason detail behind verbose)
    #   Given OAuth is configured
    #   And 1 channel RSS feed fails with HTTP 404
    #   And Valves.verbose is True
    #   When gather_candidates runs the subscriptions source
    #   Then the note includes the friendly headline
    #   And it includes "1 channel(s) failed: HTTP 404: Not Found"
    def test_verbose_note_has_raw_per_reason(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, [_channel(0)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert "subscriptions: 0 ok, 1 failed" in notes  # friendly headline
        assert "1 channel(s) failed: HTTP 404: Not Found" in notes  # raw per-reason detail

    # T3-1.B3 · unit · provenance: UX-1 (verbose off by default)
    #   Given a Tools instance with default Valves
    #   When the Valves are read
    #   Then verbose is False
    def test_valves_default_verbose_false(self):
        t = Tools()
        assert t.valves.verbose is False

    # T3-1.C1 · workflow · provenance: UX-2 (OAuth unset → existing skip note only)
    #   Given OAuth is not configured
    #   When gather_candidates runs with watch_later and subscriptions
    #   Then the notes contain "watch_later skipped: OAuth not configured"
    #   And the notes contain "subscriptions skipped: OAuth not configured"
    #   And the notes do not contain "channel(s) failed:"
    #   And the notes do not contain "subscriptions: "
    def test_oauth_unset_emits_skip_note_only(self):
        t = Tools()  # bare, OAuth unset
        notes: list[str] = []
        t._gather_one("watch_later", 20, "", notes)
        t._gather_one("subscriptions", 20, "", notes)
        assert "watch_later skipped: OAuth not configured" in notes
        assert "subscriptions skipped: OAuth not configured" in notes
        assert "channel(s) failed:" not in notes
        assert "subscriptions: " not in notes

    # T3-1.C2 · workflow · provenance: UX-2 (OAuth set channel 404 → one friendly line by default)
    #   Given OAuth is configured
    #   And the subscriptions list succeeds
    #   And 1 channel RSS feed fails with HTTP 404
    #   And Valves.verbose is False
    #   When gather_candidates runs the subscriptions source
    #   Then the subscriptions note contains exactly one subscriptions summary line
    #   And that line matches the exact locked format "subscriptions: {ok} ok, {failed} failed"
    def test_oauth_set_404_single_friendly_line(self, tools, monkeypatch):
        _stub_api(monkeypatch, [_channel(0)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 1  # exactly one summary line
        assert re.fullmatch(r"subscriptions: \d+ ok, \d+ failed", notes[0])  # locked format
        assert notes[0] == "subscriptions: 0 ok, 1 failed"

    # T3-1.C3 · workflow · provenance: UX-2 (unset OAuth and failed channels are distinguishable)
    #   Given two otherwise identical scenarios
    #   And scenario A has OAuth unset
    #   And scenario B has OAuth set with one channel RSS 404
    #   When gather_candidates runs each scenario
    #   Then scenario A notes contain "subscriptions skipped: OAuth not configured"
    #   And scenario B notes contain the subscriptions summary line with counts
    #   And scenario B notes do not contain "subscriptions skipped: OAuth not configured"
    def test_unset_vs_failed_distinct_notes(self, tools, monkeypatch):
        tools_a = Tools()  # scenario A: OAuth unset
        notes_a: list[str] = []
        tools_a._gather_one("subscriptions", 20, "", notes_a)
        # scenario B: OAuth set, one channel RSS 404
        _stub_api(monkeypatch, [_channel(0)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        notes_b: list[str] = []
        tools._gather_one("subscriptions", 20, "", notes_b)
        assert "subscriptions skipped: OAuth not configured" in notes_a
        assert "subscriptions: 0 ok, 1 failed" in notes_b  # summary line with counts
        assert "subscriptions skipped: OAuth not configured" not in notes_b
