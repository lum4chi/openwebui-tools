"""T1 subscriptions plumbing: RSS parse (T1-1/T1-2) + _fetch_subscriptions (T1-3..T1-6)."""

import urllib.error
from collections.abc import Mapping
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import youtube_manager
from youtube_manager import (
    SUBSCRIPTION_CHANNEL_CAP,
    QuotaError,
    ReauthNeeded,
    _parse_rss,
    _rss_url,
    candidates_from_rss,
)

FEED_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
    'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
)

# Canned Atom feed in the verified 2026-09-15 live shape: 2 entries, media:content@duration
# on entry A only, views under media:community/media:statistics, <published> in +00:00 form.
RSS_SAMPLE = (
    FEED_HEAD + "<title>Chan A</title>"
    "<entry>"
    "<id>yt:video:V1</id><yt:videoId>V1</yt:videoId><yt:channelId>UCA</yt:channelId>"
    "<title>A</title>"
    '<link rel="alternate" href="https://www.youtube.com/watch?v=V1"/>'
    "<author><name>Chan A</name></author>"
    "<published>2026-09-14T17:30:39+00:00</published>"
    "<updated>2026-09-14T17:30:39+00:00</updated>"
    "<media:group>"
    "<media:title>A</media:title>"
    '<media:content url="https://www.youtube.com/v/V1" type="video" duration="125"/>'
    "<media:description>desc A</media:description>"
    "<media:community>"
    '<media:starRating count="3" average="5" min="1" max="5"/>'
    '<media:statistics views="123"/>'
    "</media:community>"
    "</media:group>"
    "</entry>"
    "<entry>"
    "<id>yt:video:V2</id><yt:videoId>V2</yt:videoId><yt:channelId>UCA</yt:channelId>"
    "<title>B</title>"
    "<author><name>Chan A</name></author>"
    "<published>2026-09-10T08:00:00+00:00</published>"
    "<updated>2026-09-10T08:00:00+00:00</updated>"
    "<media:group>"
    "<media:title>B</media:title>"
    '<media:content url="https://www.youtube.com/v/V2" type="video"/>'
    "<media:description>desc B</media:description>"
    "<media:community>"
    '<media:starRating count="1" average="4" min="1" max="5"/>'
    '<media:statistics views="7"/>'
    "</media:community>"
    "</media:group>"
    "</entry>"
    "</feed>"
).encode()


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


def _channel(i: int) -> dict:
    return {
        "id": f"UC{i:04d}",
        "snippet": {
            "channelId": f"UC{i:04d}",
            "channelTitle": f"Chan {i}",
            "publishedAt": f"2026-01-{i + 1:02d}T00:00:00Z",
        },
    }


class TestRssParse:
    # T1-1 · unit · provenance: AC-1 + AC-3 (candidates surface via stdlib RSS path)
    # Given a canned Atom feed with 2 entries in the verified 2026-09-15 shape
    #   (entry A: id "yt:video:V1", yt:videoId V1, title "A", author/name "Chan A",
    #    published "2026-09-14T17:30:39+00:00", media:content@duration="125",
    #    media:description "desc A", media:statistics@views="123")
    #   (entry B: same fields, id "yt:video:V2", no duration attribute, views "7")
    # When _parse_rss is called on it
    # Then it returns 2 entry dicts
    # And entry A = video_id "V1", title "A", channel_name "Chan A", published "2026-09-14",
    #   duration_sec 125, views 123, description "desc A"
    # And entry B = video_id "V2", duration_sec None, views 7
    # And candidates_from_rss maps them to Candidate with tags [] and sources ["subscriptions"]
    def test_full_entry_parses(self):
        entries = _parse_rss(RSS_SAMPLE)
        assert len(entries) == 2
        a, b = entries
        assert a["video_id"] == "V1"
        assert a["title"] == "A"
        assert a["channel_name"] == "Chan A"
        assert a["channel_id"] == "UCA"
        assert a["published"] == "2026-09-14"
        assert a["duration_sec"] == 125
        assert a["views"] == 123
        assert a["description"] == "desc A"
        assert b["video_id"] == "V2"
        assert b["duration_sec"] is None
        assert b["views"] == 7
        cands = candidates_from_rss(entries, "subscriptions")
        assert [c.video_id for c in cands] == ["V1", "V2"]
        assert all(c.tags == [] for c in cands)
        assert all(c.sources == ["subscriptions"] for c in cands)

    # T1-2 · unit · provenance: AC-1 + AC-3 (robust parse; repo edge-case rule)
    # Given an entry with only atom id "yt:video:V9" (no yt:videoId element) and no media:group
    #   and a second entry with no resolvable video id at all
    # When _parse_rss is called
    # Then the first entry parses with video_id "V9", duration_sec None, views None, description None
    # And the second entry is skipped (not in the result)
    def test_missing_optionals_and_skips_idless(self):
        feed = _entry_feed("<entry><id>yt:video:V9</id></entry><entry><title>no resolvable id</title></entry>")
        entries = _parse_rss(feed)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["video_id"] == "V9"
        assert entry["duration_sec"] is None
        assert entry["views"] is None
        assert entry["description"] is None

    # T1-2 edge complement · unit · provenance: repo edge-case rule (error paths must be tested)
    # Given a feed with one entry whose media:statistics@views="12k" (non-integer attribute)
    # When _parse_rss is called
    # Then the entry parses with video_id "V7" and views None instead of raising
    def test_defensive_parse_of_malformed_content(self):
        feed = _entry_feed(
            '<entry><id>yt:video:V7</id><media:group><media:statistics views="12k"/></media:group></entry>'
        )
        entries = _parse_rss(feed)
        assert len(entries) == 1
        assert entries[0]["video_id"] == "V7"
        assert entries[0]["views"] is None


class TestFetchSubscriptions:
    # T1-3 · workflow · provenance: work-package research #4 (bounded fetch — explicit directive)
    # Given a stubbed _data_api_request serving subscriptions.list with 30 channels (distinct snippet.publishedAt)
    #   and a stubbed urlopen returning a 1-entry RSS feed per channel
    # When _fetch_subscriptions(max_per_source=20, notes) runs
    # Then urlopen is called exactly SUBSCRIPTION_CHANNEL_CAP (25) times
    # And the 25 fetched channels are the 25 most-recently-subscribed (snippet.publishedAt desc)
    # And every returned Candidate has sources ["subscriptions"], a non-empty channel_id, and is sorted by published desc
    def test_channel_cap_and_most_recent_first(self, tools, monkeypatch):
        channels = [_channel(i) for i in range(30)]
        pages = {None: {"items": channels[:20], "nextPageToken": "p2"}, "p2": {"items": channels[20:]}}
        calls = _stub_api(monkeypatch, lambda params: pages[params.get("pageToken")])
        feeds = {
            _rss_url(f"UC{i:04d}"): _one_entry_feed(f"V{i:02d}", f"2026-09-{i + 1:02d}", f"UC{i:04d}")
            for i in range(30)
        }
        urls = _stub_urlopen(monkeypatch, feeds)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert notes == ["subscriptions: 25 ok, 0 failed, 20 candidates"]
        assert [params["maxResults"] for _, params in calls] == [50, 50]
        assert "pageToken" not in calls[0][1]
        assert calls[1][1]["pageToken"] == "p2"
        assert len(urls) == SUBSCRIPTION_CHANNEL_CAP
        assert {url.rsplit("=", 1)[-1] for url in urls} == {f"UC{i:04d}" for i in range(5, 30)}
        assert len(cands) == 20
        assert all(c.sources == ["subscriptions"] for c in cands)
        assert all(c.channel_id for c in cands)
        published = [c.published for c in cands]
        assert published == sorted(published, reverse=True)

    # T1-4 · workflow · provenance: research #5 + AC-1 (other channels must still surface)
    # Given 3 subscribed channels and channel #2's RSS raising urllib.error.URLError
    # When _fetch_subscriptions(20, notes) runs
    # Then candidates from channels #1 and #3 are returned and channel #2's are absent
    # And Valves.verbose is True, so the note is the summary "subscriptions: 2 ok, 1 failed, 2 candidates" plus the deduped "1 channel(s) failed: transient" line
    def test_per_channel_failure_isolated(self, tools, monkeypatch):
        channels = [_channel(i) for i in range(3)]
        _stub_api(monkeypatch, lambda params: {"items": channels})
        feeds = {
            _rss_url("UC0000"): _one_entry_feed("V0", "2026-09-03", "UC0000"),
            _rss_url("UC0001"): urllib.error.URLError("connect boom"),
            _rss_url("UC0002"): _one_entry_feed("V2", "2026-09-01", "UC0002"),
        }
        _stub_urlopen(monkeypatch, feeds)
        notes: list[str] = []
        tools.valves.verbose = True

        cands = tools._fetch_subscriptions(20, notes)

        assert [c.video_id for c in cands] == ["V0", "V2"]
        assert notes == ["subscriptions: 2 ok, 1 failed, 2 candidates", "1 channel(s) failed: transient"]

    # T1-5 · workflow · provenance: research #5 + research doc A1 (subscriptionNotFound pitfall)
    # Given _data_api_request raises a raw HttpError with status 404 for subscriptions.list
    # When _fetch_subscriptions(20, notes) runs
    # Then it returns [] without raising
    # And notes records the failure
    def test_source_level_404_returns_empty_with_note(self, tools, monkeypatch):
        err = HttpError(MagicMock(status=404, reason="Not Found"), b'{"error": {"message": "subscriptionNotFound"}}')
        _stub_api(monkeypatch, lambda params: (_ for _ in ()).throw(err))
        urls = _stub_urlopen(monkeypatch, {})
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert len(notes) == 1
        assert notes[0].startswith("subscriptions")
        assert "404" in notes[0]
        assert urls == []

    # T1-6 · workflow · provenance: research #5 (existing reauth/quota UX preserved)
    # Given subscriptions.list raising ReauthNeeded (case A) resp. QuotaError (case B)
    # When _fetch_subscriptions(20, notes) runs
    # Then the same exception type propagates to the caller (parametrize A/B)
    @pytest.mark.parametrize("exc", [ReauthNeeded, QuotaError], ids=["reauth", "quota"])
    def test_reauth_and_quota_propagate(self, tools, monkeypatch, exc):
        _stub_api(monkeypatch, lambda params: (_ for _ in ()).throw(exc("boom")))
        notes: list[str] = []

        with pytest.raises(exc):
            tools._fetch_subscriptions(20, notes)

    # T1-5 implementation complement (decision 5): only 404 is special-cased, so any other raw
    # HttpError (e.g. 500) must propagate to the caller, preserving gather-path propagation.
    def test_non_404_http_error_propagates(self, tools, monkeypatch):
        err = HttpError(MagicMock(status=500, reason="Server Error"), b"server error")
        _stub_api(monkeypatch, lambda params: (_ for _ in ()).throw(err))
        notes: list[str] = []

        with pytest.raises(HttpError):
            tools._fetch_subscriptions(20, notes)
        assert notes == []
