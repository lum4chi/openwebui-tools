"""T2-1 gather_candidates: skip unknown source tokens with a warning note (backlog item 1 / A.1)."""

import pytest

import youtube_manager
from youtube_manager import parse_sources_arg


def _entry(video_id):
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


def _seed_search(monkeypatch):
    """Patch _ytdlp_extract: flat search listing + per-video watch-URL entry for srch-1."""

    def fake(url, extra=None):
        if url == "ytsearch5:rust async":
            return {"entries": [{"id": "srch-1"}]}
        if url == "https://www.youtube.com/watch?v=srch-1":
            return _entry("srch-1")
        raise AssertionError(f"unexpected yt-dlp url {url}")

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)


def _guard_io(monkeypatch) -> list[str]:
    """Fail any I/O seam call; return the ytdlp call log."""
    ytdlp_calls: list[str] = []

    def no_ytdlp(url, extra=None):
        ytdlp_calls.append(url)
        raise AssertionError("no yt-dlp I/O for the rejected request")

    def no_api(valves, method, params, user_id=None):
        raise AssertionError(f"no Data API I/O for the rejected request ({method})")

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", no_ytdlp)
    monkeypatch.setattr(youtube_manager, "_data_api_request", no_api)
    return ytdlp_calls


class TestSourcesUnknownSkip:
    """T2-1: valid tokens run, unknown tokens are named on skip-note lines, all-unknown still errors."""

    # @unit
    # Scenario: T2-1-S1 mixed sources run the valid ones and note the skipped tokens (unit)
    #   Given a configured Tools instance with a seeded search result
    #   When gather_candidates(sources="search,bogus", search_query="rust async")
    #   Then the output contains the search candidates
    #   And the "=== Source notes ===" section contains the line
    #     "bogus skipped: unknown source (valid sources: watch_later, search, subscriptions)"
    #   And the output contains no "Error:" line
    async def test_mixed_sources_note_and_run(self, tools, monkeypatch):
        _seed_search(monkeypatch)

        payload = await tools.gather_candidates(sources="search,bogus", max_per_source=5, search_query="rust async")

        assert "srch-1" in payload
        assert "=== Source notes ===" in payload
        notes = payload.split("=== Source notes ===", 1)[1].splitlines()
        assert "bogus skipped: unknown source (valid sources: watch_later, search, subscriptions)" in notes
        assert not any(line.startswith("Error:") for line in payload.splitlines())

    # @unit
    # Scenario: T2-1-S2 all-unknown sources still fail with the existing actionable error (unit)
    #   Given a configured Tools instance
    #   When gather_candidates(sources="bogus,nope")
    #   And when gather_candidates(sources="bogus")
    #   Then the output is exactly "Error: unknown source name(s) in 'bogus,nope' - valid sources: watch_later, search, subscriptions"
    #   And "Error: unknown source name(s) in 'bogus' - valid sources: watch_later, search, subscriptions"
    #   And no API call is made
    @pytest.mark.parametrize(
        ("sources", "expected"),
        [
            (
                "bogus,nope",
                "Error: unknown source name(s) in 'bogus,nope' - valid sources: watch_later, search, subscriptions",
            ),
            (
                "bogus",
                "Error: unknown source name(s) in 'bogus' - valid sources: watch_later, search, subscriptions",
            ),
        ],
        ids=["two_unknown", "single_unknown"],
    )
    async def test_all_unknown_returns_existing_error(self, tools, monkeypatch, sources, expected):
        ytdlp_calls = _guard_io(monkeypatch)

        payload = await tools.gather_candidates(sources=sources)

        assert payload == expected
        assert ytdlp_calls == []

    # @unit
    # Scenario: T2-1-S3 every unknown token is named on its own note line (unit)
    #   Given a configured Tools instance with a seeded search result
    #   When gather_candidates(sources="bogus,search,nope", search_query="rust async")
    #   Then the "=== Source notes ===" section contains both lines
    #     "bogus skipped: unknown source (valid sources: watch_later, search, subscriptions)"
    #     "nope skipped: unknown source (valid sources: watch_later, search, subscriptions)"
    #   And the search candidates are present
    async def test_multiple_unknowns_each_named(self, tools, monkeypatch):
        _seed_search(monkeypatch)

        payload = await tools.gather_candidates(
            sources="bogus,search,nope", max_per_source=5, search_query="rust async"
        )

        notes = payload.split("=== Source notes ===", 1)[1].splitlines()
        assert "bogus skipped: unknown source (valid sources: watch_later, search, subscriptions)" in notes
        assert "nope skipped: unknown source (valid sources: watch_later, search, subscriptions)" in notes
        assert "srch-1" in payload

    # @unit
    # Scenario: T2-1-S4 parse_sources_arg splits tokens and ignores empty tokens (unit)
    #   Given the module function parse_sources_arg
    #   When called with "watch_later, search ,bogus"
    #   Then it returns (["watch_later", "search"], ["bogus"])
    #   When called with "" and with ",,"
    #   Then it returns ([], [])
    #   When called with "bogus"
    #   Then it returns ([], ["bogus"])
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("watch_later, search ,bogus", (["watch_later", "search"], ["bogus"])),
            ("", ([], [])),
            (",,", ([], [])),
            ("bogus", ([], ["bogus"])),
        ],
        ids=["mixed", "empty", "only_separators", "all_unknown"],
    )
    def test_parse_sources_arg_token_split(self, raw, expected):
        assert parse_sources_arg(raw) == expected

    # @unit
    # Scenario: T2-1-S5 the actionable search_query error survives the new parsing (unit)
    #   Given a configured Tools instance
    #   When gather_candidates(sources="search,bogus") with no search_query
    #   Then the output is exactly "Error: search needs search_query (e.g. search_query='rust async')"
    async def test_search_needs_query_still_errors_with_unknown(self, tools, monkeypatch):
        ytdlp_calls = _guard_io(monkeypatch)

        payload = await tools.gather_candidates(sources="search,bogus")

        assert payload == "Error: search needs search_query (e.g. search_query='rust async')"
        assert ytdlp_calls == []
