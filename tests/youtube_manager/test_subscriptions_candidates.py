"""T6-1 B1: subscriptions digest zero-candidate diagnostics (feeds returned no usable entries / capped entries produced no candidates)."""

import email.message
import urllib.error
from collections.abc import Mapping

import pytest

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


class TestSubscriptionCandidates:
    """T6-1 B1: the zero-candidate digest suffix distinguishes why capped entries produced no candidates."""

    # @workflow [AC-1]
    # Scenario: B1 zero-candidate note distinguishes empty gathered entries
    #   Given a Tools instance with subscriptions enabled, one ok source, one failed source, and no gathered entries
    #   When the subscriptions digest note is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned no usable entries)"
    # @workflow [AC-1]
    # Scenario: B1 zero-candidate note distinguishes non-empty entries capped to zero
    #   Given a Tools instance with subscriptions enabled, one ok source, one failed source, and non-empty gathered entries that yield zero candidates
    #   When the subscriptions digest note is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (capped entries produced no candidates)"
    @pytest.mark.parametrize(
        ("ok_feed", "max_per_source", "expected_note"),
        [
            (
                FEED_HEAD + "</feed>",  # ok feed carries no <entry> element
                20,
                "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned no usable entries)",
            ),
            (
                _one_entry_feed("V0", "2026-09-03", "UC0000"),  # ok feed carries an entry the cap slices away
                0,
                "subscriptions: 1 ok, 1 failed, 0 candidates (capped entries produced no candidates)",
            ),
        ],
        ids=["empty_entries", "capped_to_zero"],
    )
    def test_zero_candidates_suffix(self, tools, monkeypatch, ok_feed: bytes, max_per_source: int, expected_note: str):
        _stub_api(monkeypatch, [_channel(0), _channel(1)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): ok_feed, _rss_url("UC0001"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(max_per_source, notes)

        assert cands == []
        assert notes == [expected_note]
