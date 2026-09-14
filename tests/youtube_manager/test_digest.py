"""T1 digest payload: taste-driven candidates (T1-1), failure handling (T1-7), id list (T1-8), first-run guidance (T1-9)."""

import youtube_manager
from youtube_manager import NOTE_TASTE, ReauthNeeded

from .conftest import sample_taste_profile

TOPICS = ["rust async", "postgres"]


def _entry(video_id, **overrides):
    entry = {
        "id": video_id,
        "title": f"Title {video_id}",
        "uploader": f"Channel {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 754,
        "view_count": 980,
        "upload_date": "20260910",
        "description": f"Desc {video_id}",
        "tags": ["tag"],
    }
    for key, value in overrides.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


def _ytdlp_fake(monkeypatch, by_url, raise_for=None):
    """Patch _ytdlp_extract: serve entries per URL; raise for URLs in raise_for."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        if raise_for is not None and url in raise_for:
            raise raise_for[url]
        return {"entries": by_url.get(url, [])}

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


def _clear_oauth(tools):
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


def _api_fake(monkeypatch, video_ids, raise_on: str | None = None):
    """Route _data_api_request on the watch_later path; optionally raise ReauthNeeded on a method."""
    calls: list[str] = []
    details = {
        vid: {
            "id": vid,
            "snippet": {
                "title": f"Detail title {vid}",
                "channelId": f"ch-{vid}",
                "channelTitle": f"Detail channel {vid}",
                "description": f"Detail description {vid}",
                "tags": ["wl-tag"],
                "publishedAt": "2026-09-01T12:00:00Z",
            },
            "contentDetails": {"duration": "PT2M35S"},
        }
        for vid in video_ids
    }

    def fake(valves, method, params):
        calls.append(method)
        if raise_on is not None and method == raise_on:
            raise ReauthNeeded("Google credential rejected by the Data API")
        if method == "channels.list":
            return {"items": [{"id": "me", "snippet": {"relatedPlaylists": {"watchLater": "WL-1"}}}]}
        if method == "playlistItems.list":
            return {"items": [{"contentDetails": {"videoId": vid}} for vid in video_ids]}
        if method == "videos.list":
            return {"items": [details[i] for i in params["ids"].split(",")]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


class TestDigest:
    """digest() payload assembly."""

    # @unit
    # Scenario: T1-1 taste-driven digest
    #   Given a taste-profile doc with topics ["rust async", "postgres"] and the search seam returns entries per topic
    #   When the tool runs digest
    #   Then each topic's video ids appear in the candidates section
    #   And the payload contains the title, channel, duration, views and published date for each candidate
    #   And the Sources section reports a count per topic (a `search:<topic>` bucket per topic) plus a `watch_later` bucket
    async def test_taste_driven_candidates(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(TOPICS, [])
        ytdlp_calls = _ytdlp_fake(
            monkeypatch,
            {
                "ytsearch20:rust async": [
                    _entry("rust1", duration=3661, view_count=2_500_000),
                    _entry("rust2", view_count=15_200),
                ],
                "ytsearch20:postgres": [_entry("pg1"), _entry("pg2")],
            },
        )
        _api_fake(monkeypatch, ["wl1"])

        payload = await tools.digest()

        for video_id in ("rust1", "rust2", "pg1", "pg2"):
            assert f"Title {video_id}" in payload
            assert f"Channel {video_id}" in payload
            assert video_id in payload
        assert "Detail title wl1" in payload  # watch-later candidate enriched via the Data API
        assert "wl1" in payload
        assert "=== Candidates (5) ===" in payload
        assert "1:01:01" in payload  # 3661s duration
        assert "2.5M views" in payload  # 2_500_000 views
        assert "15K views" in payload  # 15_200 views
        assert "12:34" in payload  # 754s duration
        assert "980 views" in payload
        assert "2026-09-10" in payload  # published date (20260910 upload_date)
        # Sources section: a search:<topic> bucket per topic plus a watch_later bucket
        assert "search:rust async=2" in payload
        assert "search:postgres=2" in payload
        assert "watch_later=1" in payload
        assert ytdlp_calls == ["ytsearch20:rust async", "ytsearch20:postgres"]

    # @unit
    # Scenario: T1-8 candidate id list
    #   Given N distinct candidates
    #   When digest renders the payload
    #   Then a "Candidate IDs:" line lists exactly the N video ids
    async def test_candidate_id_list(self, tools, monkeypatch, fake_store):
        _clear_oauth(tools)  # watch_later off -> candidates come from the topic searches only
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(TOPICS, [])
        _api_fake(monkeypatch, [])  # inert: OAuth cleared, no API calls expected
        _ytdlp_fake(
            monkeypatch,
            {
                "ytsearch20:rust async": [_entry("r1"), _entry("r2")],
                "ytsearch20:postgres": [_entry("p1")],
            },
        )

        payload = await tools.digest()

        ids_line = next(line for line in payload.splitlines() if line.startswith("Candidate IDs:"))
        assert ids_line == "Candidate IDs: r1, r2, p1"

    # @unit
    # Scenario: T1-7 failure handling
    #   Given the "rust async" topic search fails with a bot-check message but the "postgres" topic succeeds
    #   When digest runs
    #   Then candidates from the postgres topic are still returned
    #   And the payload contains a "source rust async failed: bot_check" note
    #   And the result is NOT a REAUTH_NEEDED string
    #   And when watch_later (OAuth set) raises an OAuth invalid_grant
    #   Then the result starts with "REAUTH_NEEDED"
    #   And no exception propagates
    async def test_partial_failure_note(self, tools, monkeypatch, fake_store):
        _clear_oauth(tools)
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(TOPICS, [])
        _api_fake(monkeypatch, [])  # inert: OAuth cleared, no API calls expected
        _ytdlp_fake(
            monkeypatch,
            {"ytsearch20:postgres": [_entry("pg1")]},
            raise_for={"ytsearch20:rust async": Exception("Sign in to confirm you're not a bot")},
        )

        payload = await tools.digest()  # no exception propagates

        assert "pg1" in payload  # candidates from the postgres topic are still returned
        assert "source rust async failed: bot_check" in payload
        assert not payload.startswith("REAUTH_NEEDED")  # an anonymous search failure never reauths

    # Scenario T1-7 (watch_later variant): OAuth invalid_grant on the watch_later source
    async def test_watch_later_reauth(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(["rust async"], [])
        _ytdlp_fake(monkeypatch, {"ytsearch20:rust async": [_entry("rust1")]})
        _api_fake(monkeypatch, ["wl1"], raise_on="channels.list")

        payload = await tools.digest()  # no exception propagates

        assert payload.startswith("REAUTH_NEEDED")  # the only feed-path reauth
        assert "watch_later failed: reauth" in payload
        assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload

    # @unit
    # Scenario: T1-9 no taste profile
    #   Given the state store has no taste-profile document
    #   When digest runs
    #   Then the payload is first-run guidance with the contract string "No taste profile yet" + starter template (per the state-doc contract), explaining how to set up the taste profile
    #   And it suggests calling save_taste_profile
    #   And no search seam is called
    #   And the feedback stats section is empty (no rows)
    #   And when OAuth is set and watch_later has items
    #   Then the guidance payload also contains the watch-later candidates (watch_later only — no ytsearch runs)
    #   And when the state store read raises instead of returning None
    #   Then it is treated as absent — same guidance, no crash
    #   And no exception propagates
    async def test_no_taste_profile_first_run(self, tools, monkeypatch, fake_store):
        _clear_oauth(tools)
        _api_fake(monkeypatch, [])  # inert: OAuth cleared, no API calls expected
        ytdlp_calls = _ytdlp_fake(monkeypatch, {})

        payload = await tools.digest()  # no exception propagates

        assert "No taste profile yet" in payload
        assert "Starter template:" in payload
        assert "- rust async" in payload  # starter template topics
        assert "- cat videos" in payload  # starter template avoid list
        assert "save_taste_profile" in payload  # suggests calling save_taste_profile
        assert "no feedback rows yet" in payload  # feedback stats section empty (no rows)
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        assert ytdlp_calls == []  # no search seam is called

    # Scenario T1-9 (decision 6): OAuth set + watch_later has items -> guidance still lists them
    async def test_first_run_includes_watch_later(self, tools, monkeypatch, fake_store):
        ytdlp_calls = _ytdlp_fake(monkeypatch, {})
        _api_fake(monkeypatch, ["wl1"])

        payload = await tools.digest()  # no exception propagates

        assert "No taste profile yet" in payload
        assert "Detail title wl1" in payload  # watch-later candidates included
        assert "=== Candidates (1) ===" in payload
        assert "watch_later=1" in payload
        assert ytdlp_calls == []  # watch_later only — no ytsearch runs

    # Scenario T1-9 (store read failure variant)
    async def test_store_read_failure_treated_as_absent(self, tools, monkeypatch, fake_store):
        ytdlp_calls = _ytdlp_fake(monkeypatch, {})
        _api_fake(monkeypatch, ["wl1"])

        payload_absent = await tools.digest()
        fake_store.raise_on_read = True
        payload_raising = await tools.digest()  # no exception propagates

        assert payload_raising == payload_absent  # treated as absent — same guidance, no crash
        assert ytdlp_calls == []
