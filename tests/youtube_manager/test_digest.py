"""T1 digest payload: raw profile verbatim (T1-1), watch_later reauth (T1-7), id list (T1-8), first-run guidance (T1-9)."""

import youtube_manager
from youtube_manager import NOTE_TASTE, Candidate, FeedbackStats, ReauthNeeded, render_digest

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

    def fake(valves, method, params, user_id=None):
        calls.append(method)
        if raise_on is not None and method == raise_on:
            raise ReauthNeeded("Google credential rejected by the Data API")
        if method == "channels.list":
            raise AssertionError("channels.list must never be called on the watch_later path")
        if method == "playlists.list":
            return {"items": [{"id": "PLWL", "snippet": {"title": "Watch Later"}}]}
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
    # Scenario: T1-1 raw profile verbatim in the digest prompt
    #   Given a taste-profile note containing a multi-section markdown profile (Topics + Context + Avoid)
    #   When digest() is run with OAuth unset (watch_later/subscriptions skipped, search removed)
    #   Then the raw profile text is present verbatim in the digest payload prompt
    #   And no parsed topic string is re-emitted as a candidate source label
    async def test_raw_profile_verbatim(self, tools, monkeypatch, fake_store):
        profile = (
            "# Taste profile\n"
            "\n"
            "## Topics\n"
            "- rust async\n"
            "- postgres\n"
            "\n"
            "## Context\n"
            "- I only watch deep dives\n"
            "\n"
            "## Avoid\n"
            "- cat videos"
        )
        fake_store.docs[NOTE_TASTE] = profile
        _clear_oauth(tools)  # watch_later/subscriptions skipped; search removed from the digest
        _api_fake(monkeypatch, [])  # inert: OAuth unset, no Data API calls
        ytdlp_calls = _ytdlp_fake(monkeypatch, {})  # no search seam is called

        payload = await tools.digest()

        assert profile in payload  # the raw profile text is present verbatim in the prompt
        assert "search:" not in payload  # no parsed topic string is re-emitted as a candidate source label
        assert "=== Candidates (0) ===" in payload  # watch_later/subscriptions skipped, search removed
        assert ytdlp_calls == []  # no ytsearch runs

    # @unit
    # Scenario: T1-2 no per-topic search fan-out
    #   Given the same profile with bullet topics ("rust async", "postgres")
    #   When digest() is run
    #   Then no candidate source is labeled "search:<topic>"
    #   And no ytsearch20:<profile-topic> call is captured in the ytdlp recorder
    async def test_no_topic_search_fanout(self, tools, monkeypatch, fake_store):
        _clear_oauth(tools)
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(["rust async", "postgres"], [])
        ytdlp_calls = _ytdlp_fake(monkeypatch, {})  # no search seam; nothing to serve
        _api_fake(monkeypatch, [])  # inert: OAuth unset, no Data API calls

        payload = await tools.digest()

        assert "search:" not in payload  # no candidate source is labeled "search:<topic>"
        assert ytdlp_calls == []  # no ytsearch20:<profile-topic> call is captured

    # @unit
    # Scenario: T1-8 candidate id list (post-B1: watch_later/subscriptions only, no search)
    #   Given OAuth unset so watch_later/subscriptions are skipped and per-topic search is removed
    #   When digest renders the payload
    #   Then a "Candidate IDs:" line is empty — no candidates
    async def test_candidate_id_list(self, tools, monkeypatch, fake_store):
        _clear_oauth(tools)  # watch_later/subscriptions skipped; search removed
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(TOPICS, [])
        _api_fake(monkeypatch, [])  # inert: OAuth cleared, no API calls expected
        _ytdlp_fake(monkeypatch, {})  # no search seam; nothing to serve

        payload = await tools.digest()

        ids_line = next(line for line in payload.splitlines() if line.startswith("Candidate IDs:"))
        assert ids_line == "Candidate IDs: (none)"

    # Scenario T1-7 (watch_later variant): OAuth invalid_grant on the watch_later source
    # T8-5 S1 · @unit — all-stale facet: both gated sources stale (watch_later ReauthNeeded;
    # subscriptions stale via the file-local fake) → reauth block followed by the digest payload
    # Scenario: T8-5 S1 all OAuth sources stale returns the reauth block followed by the digest payload
    #   Given watch_later and subscriptions both fail with ReauthNeeded (OAuth configured)
    #   When digest is called
    #   Then the return starts with "REAUTH_NEEDED"
    #     And it contains each per-source "<source> failed: reauth" line
    #     And it contains "Fix: run start_auth, open the URL, then finish_auth with the new code."
    #     And it contains the digest payload (the "=== Candidates (" section is present — the payload is no longer discarded)
    async def test_watch_later_reauth(self, tools, monkeypatch, fake_store):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(["rust async"], [])
        _ytdlp_fake(monkeypatch, {"ytsearch20:rust async": [_entry("rust1")]})
        _api_fake(monkeypatch, ["wl1"], raise_on="playlistItems.list")

        payload = await tools.digest()  # no exception propagates

        assert payload.startswith("REAUTH_NEEDED")  # the only feed-path reauth
        assert "watch_later failed: reauth" in payload
        assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload
        assert "=== Candidates (" in payload  # T8-5 S1: the digest payload is no longer discarded

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


HINT = "Next: review Sources above; if any source is skipped, run check_setup, then start_auth and finish_auth."


class TestDigestZeroCandidateHint:
    """T9-4 M2: stable zero-candidate next-step hint in render_digest only."""

    # @unit
    # Scenario: T9-4 S1 digest zero candidates emits stable next-step hint
    #   Given the digest has zero candidates
    #   When render_digest renders the digest payload
    #   Then the payload contains "=== Candidates (0) ==="
    #     And it contains "Candidate IDs: (none)"
    #     And the line immediately after "Candidate IDs: (none)" is exactly "Next: review Sources above; if any source is skipped, run check_setup, then start_auth and finish_auth."
    def test_render_digest_zero_candidates_emits_hint(self):
        payload = render_digest([], None, FeedbackStats({}, {}, []), {})
        lines = payload.splitlines()
        assert "=== Candidates (0) ===" in payload
        assert "Candidate IDs: (none)" in payload
        idx = lines.index("Candidate IDs: (none)")
        assert lines[idx + 1] == HINT  # immediately after, no extra blank line between them

    # @unit
    # Scenario: T9-4 S2 digest positive candidates do not emit the hint
    #   Given the digest has one candidate
    #   When render_digest renders the digest payload
    #   Then the payload contains "=== Candidates (1) ==="
    #     And the payload does not contain "Next: review Sources above"
    #     And the candidates section keeps the existing positive-candidate shape
    def test_render_digest_positive_candidates_has_no_hint(self):
        cand = Candidate(
            video_id="wl1",
            title="Detail title wl1",
            channel_name="Detail channel wl1",
            channel_id="ch-wl1",
            duration_sec=155,
            views=980,
            published="2026-09-01",
            description="Detail description wl1",
            tags=["wl-tag"],
            sources=["watch_later"],
        )
        payload = render_digest([cand], None, FeedbackStats({}, {}, []), {"watch_later": 1})
        lines = payload.splitlines()
        assert "=== Candidates (1) ===" in payload
        assert HINT not in payload
        idx = lines.index("=== Candidates (1) ===")
        assert lines[idx + 1] == "[1] Detail title wl1 - Detail channel wl1 (2:35, 980 views, 2026-09-01)"
        assert lines[idx + 2] == "Candidate IDs: wl1"
        assert lines[-1] == "Candidate IDs: wl1"  # candidates section is last — no hint appended

    # @unit
    # Scenario: T9-4 S3 gather_candidates zero candidates remain unchanged
    #   Given gather_candidates returns zero candidates
    #   When gather_candidates renders the candidates payload
    #   Then the payload contains "=== Candidates (0) ==="
    #     And the payload does not contain "Next: review Sources above"
    async def test_gather_zero_candidates_has_no_hint(self, tools, monkeypatch):
        _clear_oauth(tools)  # OAuth unset: watch_later skipped with a note
        _api_fake(monkeypatch, [])  # inert: no Data API calls expected
        _ytdlp_fake(monkeypatch, {})  # no search seam; nothing to serve
        payload = await tools.gather_candidates(sources="watch_later")
        assert "=== Candidates (0) ===" in payload
        assert HINT not in payload
