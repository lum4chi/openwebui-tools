"""T0-1 · R2-B1: surface the real RSS HTTP status + dedup to one line per distinct reason.

Drives the subscriptions source (``_fetch_subscriptions``) and inspects the deduped failure
notes it emits. The BDD (plan ``.opencode/plans/youtube-production-readiness.md`` · Task T0-1)
is workflow-level: each scenario feeds a channel's RSS via stubbed ``urlopen`` and asserts on
the emitted note lines (one per distinct failure reason).
"""

import email.message
import urllib.error
from collections.abc import Mapping

import youtube_manager
from youtube_manager import _rss_url

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


def _reason_for(i: int) -> tuple[int, str]:
    """3 distinct reasons across the 25 channels: i>=15 -> 503, 5<=i<15 -> 429, i<5 -> 404."""
    if i >= 15:
        return 503, "Service Unavailable"
    if i >= 5:
        return 429, "Too Many Requests"
    return 404, "Not Found"


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


def _stub_api(monkeypatch, responder) -> list[tuple[str, dict]]:
    """Patch youtube_manager._data_api_request; responder(params) replies or raises."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if method != "subscriptions.list":
            raise AssertionError(f"unexpected API method {method}")
        return responder(params)

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


class TestSubscriptionsErrorSurface:
    """T0-1: RSS HTTP status surfaced in notes + one deduped line per distinct failure reason."""

    # T0-1.1 · unit · provenance: BDD Task T0-1 (R2-B1 "surface the real error")
    #   Given a subscriptions channel whose RSS feed fetch raises an HTTP 404 error
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 404" and an HTTP reason phrase
    #   And it does not contain the bare word "transient"
    def test_http_404_surfaces_real_status(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, lambda params: {"items": [_channel(0)]})
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 2
        assert notes[0] == "subscriptions: 0 ok, 1 failed"
        assert "HTTP 404" in notes[1]
        assert "Not Found" in notes[1]
        assert "transient" not in notes[1]

    # T0-1.2 · unit · provenance: BDD Task T0-1 (R2-B1 "surface the real error")
    #   Given a subscriptions channel whose RSS feed fetch raises an HTTP 429 error
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 429"
    def test_http_429_surfaces_real_status(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, lambda params: {"items": [_channel(0)]})
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(429, "Too Many Requests")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 2
        assert notes[0] == "subscriptions: 0 ok, 1 failed"
        assert "HTTP 429" in notes[1]

    # T0-1.3 · unit · provenance: BDD Task T0-1 (R2-B1 "surface the real error")
    #   Given a subscriptions channel whose RSS feed fetch raises an HTTP 503 error
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line contains "HTTP 503"
    #   And it does not contain the bare word "transient"
    def test_http_503_surfaces_real_status(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, lambda params: {"items": [_channel(0)]})
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(503, "Service Unavailable")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 2
        assert notes[0] == "subscriptions: 0 ok, 1 failed"
        assert "HTTP 503" in notes[1]
        assert "transient" not in notes[1]

    # T0-1.4 · unit · provenance: BDD Task T0-1 (R2-B1 — no status to surface)
    #   Given a subscriptions channel whose RSS feed fetch raises a URLError with no HTTP response (DNS failure / connection refused)
    #   When gather_candidates runs the subscriptions source
    #   Then the failure line still classifies as "transient" (connectivity failure — no status to surface)
    def test_genuine_urlerror_stays_transient(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, lambda params: {"items": [_channel(0)]})
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): urllib.error.URLError("connect boom")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 2
        assert notes[0] == "subscriptions: 0 ok, 1 failed"
        assert "transient" in notes[1]

    # T0-1.5 · unit · provenance: BDD Task T0-1 (R2-B1 "Dedup — one line per distinct error, not one per channel")
    #   Given 25 subscription channels failing under 3 distinct error reasons
    #   When gather_candidates runs the subscriptions source
    #   Then exactly 3 failure lines are emitted, one per distinct reason
    #   And each line is prefixed with its channel count (e.g. "5 channel(s) failed: HTTP 404: Not Found")
    #   And the 25-channel total is preserved (nothing lost, nothing per-channel duplicated)
    def test_dedup_one_line_per_distinct_reason(self, tools, monkeypatch):
        tools.valves.verbose = True
        channels = [_channel(i) for i in range(25)]
        _stub_api(monkeypatch, lambda params: {"items": channels})
        feeds = {_rss_url(f"UC{i:04d}"): _http_error(*_reason_for(i)) for i in range(25)}
        _stub_urlopen(monkeypatch, feeds)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        # processed in publishedAt desc (i 24->0): 503 first (i15-24), then 429 (i5-14), then 404 (i0-4)
        assert cands == []
        assert len(notes) == 4
        assert notes[0] == "subscriptions: 0 ok, 25 failed"
        assert notes[1] == "10 channel(s) failed: HTTP 503: Service Unavailable"
        assert notes[2] == "10 channel(s) failed: HTTP 429: Too Many Requests"
        assert notes[3] == "5 channel(s) failed: HTTP 404: Not Found"

    # T0-1.6 · unit · provenance: BDD Task T0-1 (R2-B1 "Dedup ... one line per distinct error")
    #   Given exactly 1 subscription channel whose RSS feed fetch raises an HTTP 404 error
    #   When gather_candidates runs the subscriptions source
    #   Then exactly 1 failure line "1 channel(s) failed: HTTP 404: Not Found" is emitted
    def test_single_failing_channel_exact_format(self, tools, monkeypatch):
        tools.valves.verbose = True
        _stub_api(monkeypatch, lambda params: {"items": [_channel(0)]})
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == ["subscriptions: 0 ok, 1 failed", "1 channel(s) failed: HTTP 404: Not Found"]

    # T0-1.7 · unit · provenance: BDD Task T0-1 (regression — healthy channels unaffected)
    #   Given subscription channels whose RSS feeds parse cleanly
    #   When gather_candidates runs the subscriptions source
    #   Then their candidates are returned and no failure lines are emitted
    def test_healthy_channels_no_failure_lines(self, tools, monkeypatch):
        _stub_api(monkeypatch, lambda params: {"items": [_channel(i) for i in range(2)]})
        feeds = {
            _rss_url("UC0000"): _one_entry_feed("V0", "2026-09-03", "UC0000"),
            _rss_url("UC0001"): _one_entry_feed("V1", "2026-09-01", "UC0001"),
        }
        _stub_urlopen(monkeypatch, feeds)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert [c.video_id for c in cands] == ["V0", "V1"]
        assert notes == ["subscriptions: 2 ok, 0 failed, 2 candidates"]
