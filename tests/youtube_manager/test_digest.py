"""T1 digest payload: suggested videos (T1-1), failure handling (T1-7), id list (T1-8), no-state (T1-9)."""

import pytest

import youtube_manager
from youtube_manager import QuotaError, ReauthNeeded


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


class TestDigest:
    """digest() payload assembly."""

    # @unit
    # Scenario: T1-1 suggested videos
    #   Given the yt-dlp seam returns N home-feed entries for :ytrec and M subscription entries for :ytsubs
    #   When the tool runs digest
    #   Then every entry's video id appears in the candidates section
    #   And the payload contains the title, channel, duration, views and published date for each candidate
    async def test_suggested_videos_present(self, tools, monkeypatch, fake_store):
        _ytdlp_fake(
            monkeypatch,
            {
                ":ytrec": [_entry("rec1", duration=3661, view_count=2_500_000), _entry("rec2", view_count=15_200)],
                ":ytsubs": [_entry("sub1"), _entry("sub2")],
            },
        )

        payload = await tools.digest()

        for video_id in ("rec1", "rec2", "sub1", "sub2"):
            assert f"Title {video_id}" in payload
            assert f"Channel {video_id}" in payload
            assert video_id in payload
        assert "=== Candidates (4) ===" in payload
        assert "1:01:01" in payload  # 3661s duration
        assert "2.5M views" in payload  # 2_500_000 views
        assert "15K views" in payload  # 15_200 views
        assert "12:34" in payload  # 754s duration
        assert "980 views" in payload
        assert "2026-09-10" in payload  # published date (20260910 upload_date)

    # @unit
    # Scenario: T1-8 candidate id list
    #   Given N distinct candidates
    #   When digest renders the payload
    #   Then a "Candidate IDs:" line lists exactly the N video ids
    async def test_candidate_id_list(self, tools, monkeypatch, fake_store):
        _ytdlp_fake(
            monkeypatch,
            {
                ":ytrec": [_entry("rec1"), _entry("rec2")],
                ":ytsubs": [_entry("sub1")],
            },
        )

        payload = await tools.digest()

        ids_line = next(line for line in payload.splitlines() if line.startswith("Candidate IDs:"))
        assert ids_line == "Candidate IDs: rec1, rec2, sub1"

    # @unit
    # Scenario: T1-7 failure handling
    #   Given the recommended feed fails with a bot-check message but subscriptions succeeds
    #   When digest runs
    #   Then candidates from subscriptions are still returned
    #   And the payload contains a "recommended failed: bot_check" note
    #   And when ALL feeds fail with reauth-class messages
    #   Then the result starts with "REAUTH_NEEDED"
    #   And no exception propagates
    async def test_partial_failure_note(self, tools, monkeypatch, fake_store):
        _ytdlp_fake(
            monkeypatch,
            {":ytsubs": [_entry("sub1")]},
            raise_for={":ytrec": Exception("Sign in to confirm you're not a bot")},
        )

        payload = await tools.digest()

        assert "sub1" in payload  # subscriptions candidates still returned
        assert "recommended failed: bot_check" in payload
        assert not payload.startswith("REAUTH_NEEDED")  # a source succeeded

    # Scenario T1-7 (all-feeds variant): OAuth reauth/quota/transient classes across every feed
    # (session reauth purged - decision 3: login/2FA messages classify as transient, not reauth)
    @pytest.mark.parametrize(
        ("fail_exc", "expect_prefix", "expect_note"),
        [
            (ReauthNeeded("Google credential rejected by the Data API"), "REAUTH_NEEDED", "recommended failed: reauth"),
            (Exception("Sign in to continue"), "", "recommended failed: transient"),
            (Exception("Sign in to confirm you're not a bot"), "REAUTH_NEEDED", "recommended failed: bot_check"),
            (QuotaError("YouTube Data API quota exceeded"), "", "recommended failed: quota"),
            (Exception("network timeout"), "", "recommended failed: transient"),
        ],
        ids=["reauth_exception", "login_message_transient", "bot_check", "quota", "transient"],
    )
    async def test_all_fail_reauth(self, tools, monkeypatch, fake_store, fail_exc, expect_prefix, expect_note):
        raise_for = {":ytrec": fail_exc, ":ytsubs": fail_exc}
        _ytdlp_fake(monkeypatch, {}, raise_for=raise_for)

        payload = await tools.digest()  # no exception propagates

        reason = expect_note.split("failed: ")[1]
        assert payload.startswith(expect_prefix)
        assert expect_note in payload
        assert f"subscriptions failed: {reason}" in payload
        if expect_prefix == "REAUTH_NEEDED":
            if reason == "bot_check":
                assert "Fix: update yt-dlp and retry (bot-check on anonymous access)." in payload
            else:
                assert "Fix: run start_auth, open the URL, then finish_auth with the new code." in payload
        else:
            assert "=== Candidates (0) ===" in payload
            assert "Candidate IDs: (none)" in payload

    # @unit
    # Scenario: T1-9 no state
    #   Given the state store has no documents at all
    #   When digest runs
    #   Then the payload contains "No taste profile yet" and a starter template
    #   And the feedback stats section is empty (no rows)
    #   And no exception propagates
    async def test_no_state_documents(self, tools, monkeypatch, fake_store):
        _ytdlp_fake(
            monkeypatch,
            {
                # bare1 lacks duration/views/published -> rendered as unknown
                ":ytrec": [_entry("bare1", duration=None, view_count=None, upload_date=None)],
                ":ytsubs": [_entry("sub1")],
            },
        )

        payload = await tools.digest()  # no exception propagates

        assert "No taste profile yet" in payload
        assert "Starter template:" in payload
        assert "- liked channels:" in payload
        assert "no feedback rows yet" in payload  # feedback stats section empty (no rows)
        assert "duration unknown" in payload
        assert "no view count" in payload
        assert "date unknown" in payload

    # @unit
    # Scenario: T1-9 no state (store read failure variant)
    #   Given the state store read raises instead of returning None
    #   When digest runs
    #   Then it is treated as absent - same payload, no crash
    async def test_store_read_failure_treated_as_absent(self, tools, monkeypatch, fake_store):
        by_url = {
            ":ytrec": [_entry("rec1")],
            ":ytsubs": [_entry("sub1")],
        }
        _ytdlp_fake(monkeypatch, by_url)

        fake_store.raise_on_read = False
        payload_absent = await tools.digest()
        fake_store.raise_on_read = True
        payload_raising = await tools.digest()  # no exception propagates

        assert payload_raising == payload_absent  # same payload as the absent case
