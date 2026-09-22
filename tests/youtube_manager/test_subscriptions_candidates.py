"""T6-1 B1 / T9-2 B2-new: subscriptions digest zero-candidate diagnostics (zero-entry / no usable video id / capped entries)."""

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


def _idless_entry(i: int) -> str:
    """An Atom <entry> with neither a <yt:videoId> nor a yt:video: <id> (no usable video id)."""
    return (
        "<entry>"
        f"<id>http://www.youtube.com/channel/UC{i:04d}</id>"
        f"<title>No video id {i}</title>"
        "<author><name>Feed Chan</name></author>"
        "<published>2026-09-03</published>"
        "</entry>"
    )


def _idless_feed(count: int) -> bytes:
    """An ok feed carrying ``count`` entries, none with a usable video id."""
    return _entry_feed("".join(_idless_entry(i) for i in range(count)))


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

    # Scenario: T9-2 S1 zero-entry ok feeds report feeds returned zero entries
    #   Given _fetch_subscriptions sees 1 ok channel and 1 failed channel
    #   And the ok feed contains no <entry> elements
    #   And candidate_count is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned zero entries)"
    # Scenario: T9-2 S2 idless ok feed entries report no usable video id
    #   Given _fetch_subscriptions sees 1 ok channel and 1 failed channel
    #   And the ok feed contains 2 entries with no usable video id
    #   And candidate_count is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned 2 entry(s) with no usable video id)"
    # Scenario: T9-2 S3 capped zero-candidate shape is unchanged
    #   Given _fetch_subscriptions sees 1 ok channel and 1 failed channel
    #   And the ok feed contains 1 usable entry
    #   And max_per_source is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 1 ok, 1 failed, 0 candidates (capped entries produced no candidates)"
    @pytest.mark.parametrize(
        ("ok_feed", "max_per_source", "expected_note"),
        [
            (
                FEED_HEAD + "</feed>",  # ok feed carries no <entry> element
                20,
                "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned zero entries)",
            ),
            (
                _idless_feed(2),  # ok feed carries 2 entries, none with a usable video id
                20,
                "subscriptions: 1 ok, 1 failed, 0 candidates (feeds returned 2 entry(s) with no usable video id)",
            ),
            (
                _one_entry_feed("V0", "2026-09-03", "UC0000"),  # ok feed carries an entry the cap slices away
                0,
                "subscriptions: 1 ok, 1 failed, 0 candidates (capped entries produced no candidates)",
            ),
        ],
        ids=["empty_entries", "no_video_id", "capped_to_zero"],
    )
    def test_zero_candidates_suffix(self, tools, monkeypatch, ok_feed: bytes, max_per_source: int, expected_note: str):
        _stub_api(monkeypatch, [_channel(0), _channel(1)])
        _stub_urlopen(monkeypatch, {_rss_url("UC0000"): ok_feed, _rss_url("UC0001"): _http_error(404, "Not Found")})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(max_per_source, notes)

        assert cands == []
        assert notes == [expected_note]
