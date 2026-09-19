"""T3 add_to_playlist resilience: reauth (T3-5), validation (T3-6), I/O errors (T3-7), state failures (T3-8)."""

import pytest

from youtube_manager import NOTE_STATE, QuotaError, ReauthNeeded, parse_digest_state

from .conftest import api_fake, listing_page, playlist_row, seed_state

VIDEO_ID = "vid001"
TITLE_FROM_API = "Brand New Video"
PL_NEW = "PL-NEW"
PL_LISTED = "PL-LISTED"
PL_CACHED = "PL-CACHED"


def _valve(tools) -> str:
    return tools.valves.digest_playlist_title


def _methods(calls) -> list[str]:
    return [method for method, _ in calls]


class TestAddToPlaylistResilience:
    """add_to_playlist: failure handling — never raises, honest errors, state preserved."""

    # @unit
    # Scenario: T3-5 reauth
    #   Given the Data API seam raises ReauthNeeded (on any of playlists.list, playlists.insert, the membership listing, or the item insert)
    #   When add_to_playlist runs
    #   Then the result starts with "REAUTH_NEEDED"
    #   And it contains the start_auth re-onboarding instruction
    #   And no exception propagates
    #   And digest-state is NOT modified
    @pytest.mark.parametrize(
        "case", ["on_playlists_list", "on_playlists_insert", "on_membership_listing", "on_item_insert"]
    )
    async def test_reauth(self, tools, monkeypatch, fake_store, case):
        if case in ("on_membership_listing", "on_item_insert"):
            seed_state(fake_store, {VIDEO_ID: ("2026-09-01", TITLE_FROM_API)}, playlist_id=PL_CACHED)
            original = dict(fake_store.docs)
            pages = {PL_CACHED: [listing_page([])]}
            playlist_pages = None
            create_reply = None
        else:
            original = dict(fake_store.docs)
            pages = {PL_NEW: [listing_page([])]}
            playlist_pages = [{"items": []}]
            create_reply = {"id": PL_NEW} if case == "on_playlists_insert" else None
        method = {
            "on_playlists_list": "playlists.list",
            "on_playlists_insert": "playlists.insert",
            "on_membership_listing": "playlistItems.list",
            "on_item_insert": "playlistItems.insert",
        }[case]
        calls = api_fake(
            monkeypatch,
            pages=pages,
            playlist_pages=playlist_pages,
            create_reply=create_reply,
            insert_reply={"snippet": {"title": TITLE_FROM_API}},
            raise_for={method: ReauthNeeded("Google credential rejected by the Data API")},
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result.startswith("REAUTH_NEEDED")
        assert "Google credential rejected by the Data API" in result
        assert "run start_auth" in result
        assert "finish_auth" in result
        assert method in _methods(calls)
        assert fake_store.docs == original

    # @unit
    # Scenario: T3-6 validation errors
    #   Given the cases:
    #     | case       | setup                                   | expected substring    | data api calls |
    #     | no_title   | digest_playlist_title = "" (whitespace) | "digest_playlist_title" | none           |
    #     | empty_id   | video_id = ""                           | "video_id"            | none           |
    #   When add_to_playlist runs for each case
    #   Then the result starts with "Error:" and contains the expected text
    #   And no insert happens and digest-state is NOT modified
    @pytest.mark.parametrize(
        ("case", "video_id", "expect"),
        [
            ("no_title", VIDEO_ID, "digest_playlist_title"),
            ("empty_id", "", "video_id"),
        ],
    )
    async def test_validation_errors(self, tools, monkeypatch, fake_store, case, video_id, expect):
        if case == "no_title":
            tools.valves.digest_playlist_title = "   "
        calls = api_fake(monkeypatch, pages={})
        original = dict(fake_store.docs)

        result = await tools.add_to_playlist(video_id)

        assert result.startswith("Error:")
        assert expect in result
        assert calls == []
        assert fake_store.docs == original

    # @unit
    # Scenario: T3-7 io errors + T3-1 provider-vs-local labeling (B2 cleaned reasons)
    #   Given the Data API seam fails in one of the cases:
    #     | case           | setup                                                        | expected result                       |
    #     | quota          | QuotaError on the membership listing (provider)              | "YouTube Error: quota reached"        |
    #     | create_fails   | generic failure on playlists.insert (local/code)             | "Local Error: unexpected error"       |
    #     | stale_cached   | generic failure (404) on the item insert with a cached playlist_id (local/code) | "Local Error: unexpected error"       |
    #     | generic_insert | generic failure on the item insert (local/code)              | "Local Error: unexpected error"       |
    #   When add_to_playlist runs
    #   Then the result is exactly the cleaned-reason line (stable label prefix + cleaned reason)
    #   And no exception propagates and digest-state is NOT modified
    @pytest.mark.parametrize(
        ("case", "expected_result"),
        [
            ("quota", "YouTube Error: quota reached"),
            ("create_fails", "Local Error: unexpected error"),
            ("stale_cached", "Local Error: unexpected error"),
            ("generic_insert", "Local Error: unexpected error"),
        ],
    )
    async def test_io_errors(self, tools, monkeypatch, fake_store, case, expected_result):
        if case == "create_fails":
            original = dict(fake_store.docs)
            pages = {PL_NEW: [listing_page([])]}
            playlist_pages = [{"items": []}]
            create_reply = {"id": PL_NEW}
            raise_method = "playlists.insert"
            error = RuntimeError("backend 500: upstream timeout")
        else:
            seed_state(fake_store, {}, playlist_id=PL_CACHED)
            original = dict(fake_store.docs)
            pages = {PL_CACHED: [listing_page([])]}
            playlist_pages = None
            create_reply = None
            raise_method = "playlistItems.list" if case == "quota" else "playlistItems.insert"
            detail = (
                "YouTube Data API quota exceeded"
                if case == "quota"
                else ("404 Not Found" if case == "stale_cached" else "backend 500: upstream timeout")
            )
            error = QuotaError(detail) if case == "quota" else RuntimeError(detail)
        calls = api_fake(
            monkeypatch,
            pages=pages,
            playlist_pages=playlist_pages,
            create_reply=create_reply,
            insert_reply={"snippet": {"title": TITLE_FROM_API}},
            raise_for={raise_method: error},
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == expected_result
        assert raise_method in _methods(calls)
        assert fake_store.docs == original

    # @unit
    # Scenario: T3-8 state failures
    #   Given the insert succeeds and the state store misbehaves in one of the cases:
    #     | case         | store behaviour        | expected                                       |
    #     | read_raises  | read raises            | treated as absent; entry still recorded+written |
    #     | write_raises | write raises           | result still OK + warning "state record failed" |
    #   When add_to_playlist runs
    #   Then no exception propagates in either case
    #   And the add itself is reported OK in both cases
    @pytest.mark.parametrize("case", ["read_raises", "write_raises"])
    async def test_state_store_failures(self, tools, monkeypatch, fake_store, case):
        if case == "read_raises":
            fake_store.raise_on_read = True
        else:
            fake_store.raise_on_write = True
        api_fake(
            monkeypatch,
            pages={PL_LISTED: [listing_page([])]},
            playlist_pages=[{"items": [playlist_row(PL_LISTED, _valve(tools))]}],
            insert_reply={"snippet": {"title": TITLE_FROM_API}},
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result.startswith("OK")
        if case == "read_raises":
            assert "state record failed" not in result
            state = parse_digest_state(fake_store.docs[NOTE_STATE])
            assert state["playlist_id"] == PL_LISTED
            assert state["tool_added"][VIDEO_ID]["title"] == TITLE_FROM_API
        else:
            assert result.count("state record failed") == 1
            assert NOTE_STATE not in fake_store.docs
