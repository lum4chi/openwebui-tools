"""T3 custom digest playlist management: add_to_playlist (T3-1…T3-4, T3-9, T3-10)."""

from datetime import datetime

import pytest

from youtube_manager import NOTE_STATE, parse_digest_state

from .conftest import api_fake, item_row, listing_page, playlist_row, seed_state

VIDEO_ID = "vid001"
TITLE_FROM_API = "Brand New Video"
PL_NEW = "PL-NEW"
PL_LISTED = "PL-LISTED"
PL_CACHED = "PL-CACHED"
PL_OTHER = "PL-OTHER"


def _valve(tools) -> str:
    return tools.valves.digest_playlist_title


def _methods(calls) -> list[str]:
    return [method for method, _ in calls]


class TestAddToPlaylist:
    """add_to_playlist: idempotent custom digest playlist add + digest-state record."""

    # @unit
    # Scenario: T3-1 first add creates and records
    #   Given digest-state is absent (no playlist_id, no tool_added)
    #   And the playlists.list seam finds NO playlist with the valve title
    #   And the playlists.insert seam returns the created playlist id
    #   And the playlistItems.list seam shows the playlist does NOT contain the video
    #   And the playlistItems.insert seam returns the item with a snippet title
    #   When the tool runs add_to_playlist with the video_id
    #   Then the result starts with "OK" and names the video and the valve playlist title
    #   And playlists.insert (create) was called once with the valve title
    #   And the item insert was called with the created playlist id and the video id
    #   And digest-state is written with playlist_id = the created id
    #   And digest-state is written with tool_added[video_id] = {added_at: today, title: from the insert response}
    #   And no channels.list call is made
    # (without_title row: Behaviour contract - insert response without a snippet title records "" and the OK line names the id)
    @pytest.mark.parametrize(
        ("insert", "name"),
        [
            ({"snippet": {"title": TITLE_FROM_API}}, TITLE_FROM_API),
            ({}, VIDEO_ID),
        ],
        ids=["with_title", "without_title"],
    )
    async def test_first_add_creates_and_records(self, tools, monkeypatch, fake_store, insert, name):
        calls = api_fake(
            monkeypatch,
            pages={PL_NEW: [listing_page([])]},
            playlist_pages=[{"items": []}],
            create_reply={"id": PL_NEW},
            insert_reply=insert,
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        valve = _valve(tools)
        assert result == f'OK — added {name} to "{valve}" ({PL_NEW})'
        create_params = next(params for method, params in calls if method == "playlists.insert")
        assert create_params == {"part": "snippet", "resource": {"snippet": {"title": valve}}}
        insert_params = next(params for method, params in calls if method == "playlistItems.insert")
        assert insert_params["resource"] == {"snippet": {"playlistId": PL_NEW, "videoId": VIDEO_ID}}
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        assert state["playlist_id"] == PL_NEW
        assert state["tool_added"][VIDEO_ID] == {
            "added_at": datetime.now().date().isoformat(),
            "title": (insert.get("snippet") or {}).get("title") or "",
        }
        assert "channels.list" not in _methods(calls)

    # @unit
    # Scenario: T3-2 idempotent tracked
    #   Given the digest playlist (resolved id in state) already contains the video and digest-state tracks it in tool_added
    #   When add_to_playlist runs again for the same video_id
    #   Then the result starts with "OK" and says it is already in the digest playlist and tracked
    #   And the item insert is NOT called
    #   And digest-state is NOT rewritten (the original added_at is preserved)
    async def test_idempotent_tracked(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {VIDEO_ID: ("2026-09-01", TITLE_FROM_API)}, playlist_id=PL_CACHED)
        original = fake_store.docs[NOTE_STATE]
        calls = api_fake(monkeypatch, pages={PL_CACHED: [listing_page([item_row("it1", VIDEO_ID)])]})

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f'OK — {VIDEO_ID} already in "{_valve(tools)}" (tracked; no change)'
        assert _methods(calls) == ["playlistItems.list"]
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-3 already present untracked
    #   Given the digest playlist (resolved id in state) already contains the video and digest-state does NOT track it
    #   When add_to_playlist runs
    #   Then the result starts with "OK" and says it is already in the digest playlist and not tool-managed
    #   And the item insert is NOT called
    #   And digest-state is NOT written with this video (prune must never treat it as tool-added)
    async def test_already_present_untracked(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {"vid999": ("2026-09-01", "Other Tool Video")}, playlist_id=PL_CACHED)
        original = fake_store.docs[NOTE_STATE]
        calls = api_fake(monkeypatch, pages={PL_CACHED: [listing_page([item_row("it1", VIDEO_ID)])]})

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f'OK — {VIDEO_ID} already in "{_valve(tools)}" (not tool-managed; left untracked)'
        assert _methods(calls) == ["playlistItems.list"]
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        assert VIDEO_ID not in state["tool_added"]
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-4 paginated membership
    #   Given the digest playlist id is cached in digest-state
    #   And playlistItems.list returns the video only on the second page (nextPageToken chain of 2)
    #   When add_to_playlist runs
    #   Then the video is detected as already present (item insert NOT called)
    #   And both pages were fetched via the pagination token
    async def test_membership_paginates(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {}, playlist_id=PL_CACHED)
        pages = {
            PL_CACHED: [
                listing_page([item_row("it0", "vid000")], token="tok2"),
                listing_page([item_row("it1", VIDEO_ID)]),
            ]
        }
        calls = api_fake(monkeypatch, pages=pages)

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f'OK — {VIDEO_ID} already in "{_valve(tools)}" (not tool-managed; left untracked)'
        list_params = [params for method, params in calls if method == "playlistItems.list"]
        base = {"part": "contentDetails", "playlistId": PL_CACHED, "maxResults": 5000}
        assert list_params[0] == base
        assert list_params[1] == {**base, "pageToken": "tok2"}
        assert "playlistItems.insert" not in _methods(calls)

    # @unit
    # Scenario: T3-9 title match reuses existing playlist
    #   Given digest-state has no playlist_id
    #   And the playlists.list seam returns one playlist whose snippet.title equals the valve title
    #   And the playlistItems.list seam shows the video is NOT present
    #   And the playlistItems.insert seam returns the item
    #   When add_to_playlist runs
    #   Then playlists.insert (create) is NOT called
    #   And the membership check and the item insert use the listed playlist's id
    #   And the result starts with "OK" and names the video and the valve title
    #   And digest-state is written with playlist_id = the listed playlist's id
    # (paginated row: completeness - the Behaviour contract's "follow nextPageToken" on playlists.list;
    #  the valve-title playlist only appears on the second page)
    @pytest.mark.parametrize("layout", ["single_page", "paginated"])
    async def test_title_match_reuses_playlist(self, tools, monkeypatch, fake_store, layout):
        valve = _valve(tools)
        if layout == "single_page":
            playlist_pages = [{"items": [playlist_row(PL_LISTED, valve)]}]
        else:
            playlist_pages = [
                {"items": [playlist_row(PL_OTHER, "Other List")], "nextPageToken": "tok2"},
                {"items": [playlist_row(PL_LISTED, valve)]},
            ]
        calls = api_fake(
            monkeypatch,
            pages={PL_LISTED: [listing_page([])]},
            playlist_pages=playlist_pages,
            insert_reply={"snippet": {"title": TITLE_FROM_API}},
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f'OK — added {TITLE_FROM_API} to "{valve}" ({PL_LISTED})'
        assert "playlists.insert" not in _methods(calls)
        insert_params = next(params for method, params in calls if method == "playlistItems.insert")
        assert insert_params["resource"] == {"snippet": {"playlistId": PL_LISTED, "videoId": VIDEO_ID}}
        if layout == "paginated":
            list_params = [params for method, params in calls if method == "playlists.list"]
            assert list_params[1] == {"part": "snippet", "mine": True, "maxResults": 100, "pageToken": "tok2"}
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        assert state["playlist_id"] == PL_LISTED

    # @unit
    # Scenario: T3-10 cached id skips lookup
    #   Given digest-state has playlist_id = P and no prior tool_added entry for the video
    #   And the playlistItems.list seam shows the video is NOT present
    #   And the playlistItems.insert seam returns the item
    #   When add_to_playlist runs
    #   Then the add succeeds using playlist id P
    #   And playlists.list is NOT called and playlists.insert is NOT called
    #   And digest-state keeps playlist_id = P and gains tool_added[video_id]
    async def test_cached_id_skips_lookup(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {}, playlist_id=PL_CACHED)
        calls = api_fake(
            monkeypatch,
            pages={PL_CACHED: [listing_page([])]},
            insert_reply={"snippet": {"title": TITLE_FROM_API}},
        )

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f'OK — added {TITLE_FROM_API} to "{_valve(tools)}" ({PL_CACHED})'
        assert _methods(calls) == ["playlistItems.list", "playlistItems.insert"]
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        assert state["playlist_id"] == PL_CACHED
        assert state["tool_added"][VIDEO_ID] == {
            "added_at": datetime.now().date().isoformat(),
            "title": TITLE_FROM_API,
        }
