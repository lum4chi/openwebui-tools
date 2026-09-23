"""T0-1 (BUG-1): structured bot_check search error + search backoff cooldown (scenarios T0-1.S1–T0-1.S5)."""

from yt_dlp.utils import ExtractorError

import youtube_manager

WATCH = "https://www.youtube.com/watch?v="
BOT_CHECK = "Sign in to confirm you're not a bot"
EXPECTED_ERROR = "Error: YouTube search blocked by bot check — wait before retrying (search is rate-limited); other sources are unaffected."


def _entry(video_id: str) -> dict:
    return {
        "id": video_id,
        "title": f"Search title {video_id}",
        "uploader": f"Search channel {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 300,
        "view_count": 1000,
        "upload_date": "20260910",
        "description": f"Search description {video_id}",
        "tags": [],
    }


def _ytdlp_fake(monkeypatch, routes: dict):
    """Patch _ytdlp_extract: record every URL called; route by exact URL to a dict reply or an Exception to raise."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        outcome = routes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _freezing_clock(monkeypatch, value: float) -> None:
    monkeypatch.setattr(youtube_manager, "_now", lambda: value)


class TestSearchBotCheck:
    """T0-1: the structured bot_check error + backoff cooldown (S1–S5)."""

    # @unit
    # Scenario: T0-1.S1 structured error on bot_check (Path B: flat ok, every per-video resolution bot-checked — the user's Section E repro)
    # Given a search where the flat ytsearch fetch returns entries but every per-video resolution raises the bot-check error "Sign in to confirm you're not a bot"
    # When the agent calls gather_candidates with sources="search" and search_query="rust async"
    # Then the result is exactly "Error: YouTube search blocked by bot check — wait before retrying (search is rate-limited); other sources are unaffected."
    # And the result is not the raw string "Error: bot_check"
    # And the search bot-check cooldown is recorded (tools._search_bot_check_at is not None)
    async def test_s1_structured_error_path_b(self, tools, monkeypatch):
        _ytdlp_fake(
            monkeypatch,
            {
                "ytsearch20:rust async": {"entries": [{"id": "vid-a"}, {"id": "vid-b"}]},
                WATCH + "vid-a": ExtractorError(BOT_CHECK),
                WATCH + "vid-b": ExtractorError(BOT_CHECK),
            },
        )

        result = await tools.gather_candidates(sources="search", search_query="rust async")

        assert result == EXPECTED_ERROR
        assert result != "Error: bot_check"
        assert tools._search_bot_check_at is not None

    # @unit
    # Scenario: T0-1.S2 structured error on bot_check (Path A: the flat search fetch itself is bot-checked — same required message, no raw sentinel)
    # Given a search where the flat ytsearch fetch raises the bot-check error "Sign in to confirm you're not a bot"
    # When the agent calls gather_candidates with sources="search" and search_query="machine learning"
    # Then the result is exactly "Error: YouTube search blocked by bot check — wait before retrying (search is rate-limited); other sources are unaffected."
    # And the result is not the raw string "Error: search: bot_check"
    # And the search bot-check cooldown is recorded (tools._search_bot_check_at is not None)
    async def test_s2_structured_error_path_a(self, tools, monkeypatch):
        _ytdlp_fake(monkeypatch, {"ytsearch20:machine learning": ExtractorError(BOT_CHECK)})

        result = await tools.gather_candidates(sources="search", search_query="machine learning")

        assert result == EXPECTED_ERROR
        assert result != "Error: search: bot_check"
        assert tools._search_bot_check_at is not None

    # @unit
    # Scenario: T0-1.S3 backoff: a search inside the cooldown fails fast (no _ytdlp_extract call, no network)
    # Given the search bot-check cooldown is active (the injected _now clock is within SEARCH_BOT_CHECK_COOLDOWN_SECONDS of tools._search_bot_check_at)
    # When the agent calls gather_candidates with sources="search" and a different search_query
    # Then _ytdlp_extract is not called (zero calls)
    # And the result is exactly "Error: YouTube search blocked by bot check — wait before retrying (search is rate-limited); other sources are unaffected."
    async def test_s3_cooldown_fails_fast_no_network(self, tools, monkeypatch):
        base = 1000.0
        tools._search_bot_check_at = base
        _freezing_clock(monkeypatch, base + youtube_manager.SEARCH_BOT_CHECK_COOLDOWN_SECONDS / 2)
        calls = _ytdlp_fake(monkeypatch, {})

        result = await tools.gather_candidates(sources="search", search_query="different query")

        assert calls == []
        assert result == EXPECTED_ERROR

    # @unit
    # Scenario: T0-1.S4 backoff: after the cooldown elapses the search retries (calls _ytdlp_extract) and re-records a persisting bot_check
    # Given the search bot-check cooldown has elapsed (the injected _now clock is past tools._search_bot_check_at + SEARCH_BOT_CHECK_COOLDOWN_SECONDS)
    # And the YouTube search endpoint is still bot-checking
    # When the agent calls gather_candidates with sources="search"
    # Then _ytdlp_extract is called again (retry)
    # And the result is exactly "Error: YouTube search blocked by bot check — wait before retrying (search is rate-limited); other sources are unaffected."
    # And the cooldown is re-recorded (tools._search_bot_check_at equals the current injected _now clock value)
    async def test_s4_after_cooldown_retries_and_rerecords(self, tools, monkeypatch):
        base = 1000.0
        now = base + youtube_manager.SEARCH_BOT_CHECK_COOLDOWN_SECONDS + 1.0
        tools._search_bot_check_at = base
        _freezing_clock(monkeypatch, now)
        calls = _ytdlp_fake(monkeypatch, {"ytsearch20:rust async": ExtractorError(BOT_CHECK)})

        result = await tools.gather_candidates(sources="search", search_query="rust async")

        assert calls == ["ytsearch20:rust async"]
        assert result == EXPECTED_ERROR
        assert tools._search_bot_check_at == now

    # @unit
    # Scenario: T0-1.S5 regression guard: a healthy search (no bot check) still returns candidates and records no cooldown
    # Given a healthy search (the flat ytsearch fetch returns entries and every per-video resolution returns a dict with an id and a title)
    # When the agent calls gather_candidates with sources="search" and search_query="python tutorial"
    # Then the result starts with "=== Candidates (" and lists the candidate titles
    # And the result does not contain the bot-check error message
    # And no cooldown is recorded (tools._search_bot_check_at is None)
    async def test_s5_healthy_search_records_no_cooldown(self, tools, monkeypatch):
        _ytdlp_fake(
            monkeypatch,
            {
                "ytsearch20:python tutorial": {"entries": [{"id": "vid-a"}]},
                WATCH + "vid-a": _entry("vid-a"),
            },
        )

        result = await tools.gather_candidates(sources="search", search_query="python tutorial")

        assert result.startswith("=== Candidates (")
        assert "Search title vid-a" in result
        assert "YouTube search blocked by bot check" not in result
        assert tools._search_bot_check_at is None
