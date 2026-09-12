"""T3 watch-later playlist management: add_to_playlist (T3-1…T3-8)."""

from datetime import datetime

import pytest

import youtube_manager
from youtube_manager import NOTE_STATE, QuotaError, ReauthNeeded, parse_digest_state, serialize_digest_state

PLAYLIST_ID = "PL-WATCH-LATER"
VIDEO_ID = "vid001"
TITLE = "Brand New Video"


def _channels(with_key: bool = True, items: bool = True) -> dict:
    if not items:
        return {"items": []}
    related = {"watchLater": PLAYLIST_ID} if with_key else {}
    return {"items": [{"contentDetails": {"relatedPlaylists": related}}]}


def _page(video_ids: list[str], token: str = "") -> dict:
    page: dict = {"items": [{"contentDetails": {"videoId": vid}} for vid in video_ids]}
    if token:
        page["nextPageToken"] = token
    return page


def _api_fake(monkeypatch, channels: dict, pages: list[dict], insert: dict, raise_for: dict | None = None):
    """Route _data_api_request by method; serve membership pages in order; record calls."""
    calls: list[tuple[str, dict]] = []
    page_index = {"n": 0}

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if raise_for is not None and method in raise_for:
            raise raise_for[method]
        if method == "channels.list":
            return channels
        if method == "playlistItems.list":
            page = pages[page_index["n"]]
            page_index["n"] += 1
            return page
        if method == "playlistItems.insert":
            return insert
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr(youtube_manager, "_data_api_request", fake)
    return calls


def _seed_state(store, video_id: str, added_at: str, title: str) -> str:
    doc = serialize_digest_state({"tool_added": {video_id: {"added_at": added_at, "title": title}}})
    store.docs[NOTE_STATE] = doc
    return doc


def _no_insert(calls) -> None:
    assert not any(method == "playlistItems.insert" for method, _ in calls)


class TestAddToPlaylist:
    """add_to_playlist: idempotent Watch Later add + digest-state record."""

    # @unit
    # Scenario: T3-1 add and record
    #   Given the Data API seam resolves the Watch Later playlist id from channels.list
    #   And the playlistItems.list seam shows the playlist does NOT contain the video
    #   And the playlistItems.insert seam returns the item with a snippet title
    #   And digest-state already tracks one other tool-added entry
    #   When the tool runs add_to_playlist with the video_id
    #   Then the result starts with "OK" and names the video and "Watch Later"
    #   And the insert was called with that playlist id and video id
    #   And digest-state is written with tool_added[video_id] = {added_at: today, title: from the insert response}
    #   And the pre-existing tool-added entry is preserved
    # (second row: Behaviour contract - insert response without a snippet title records "" and the OK line names the id)
    @pytest.mark.parametrize(
        ("insert", "name"),
        [
            ({"snippet": {"title": TITLE}}, TITLE),
            ({}, VIDEO_ID),
        ],
        ids=["with_title", "without_title"],
    )
    async def test_insert_and_record(self, tools, monkeypatch, fake_store, insert, name):
        calls = _api_fake(monkeypatch, channels=_channels(), pages=[_page(["vid999"])], insert=insert)
        _seed_state(fake_store, "old001", "2026-09-01", "Old Tool Added")

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f"OK — added {name} to Watch Later ({VIDEO_ID})"
        insert_params = next(params for method, params in calls if method == "playlistItems.insert")
        assert insert_params["part"] == "snippet"
        assert insert_params["resource"] == {"snippet": {"playlistId": PLAYLIST_ID, "videoId": VIDEO_ID}}
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        expected_title = (insert.get("snippet") or {}).get("title") or ""
        assert state["tool_added"][VIDEO_ID] == {
            "added_at": datetime.now().date().isoformat(),
            "title": expected_title,
        }
        assert state["tool_added"]["old001"] == {"added_at": "2026-09-01", "title": "Old Tool Added"}

    # @unit
    # Scenario: T3-2 idempotent tracked
    #   Given the playlist already contains the video and digest-state tracks it in tool_added
    #   When add_to_playlist runs again for the same video_id
    #   Then the result starts with "OK" and says it is already in Watch Later and tracked
    #   And the insert is NOT called
    #   And digest-state is NOT rewritten (the original added_at is preserved)
    async def test_idempotent_tracked(self, tools, monkeypatch, fake_store):
        calls = _api_fake(monkeypatch, channels=_channels(), pages=[_page([VIDEO_ID])], insert={})
        original = _seed_state(fake_store, VIDEO_ID, "2026-09-01", TITLE)
        writes: list[tuple[str, str]] = []
        real_write = fake_store.write

        def spy_write(title, md):
            writes.append((title, md))
            real_write(title, md)

        monkeypatch.setattr(fake_store, "write", spy_write)

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f"OK — {VIDEO_ID} already in Watch Later (tracked; no change)"
        _no_insert(calls)
        assert writes == []
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-3 already present untracked
    #   Given the playlist already contains the video and digest-state does NOT track it
    #   When add_to_playlist runs
    #   Then the result starts with "OK" and says it is already in Watch Later and not tool-managed
    #   And the insert is NOT called
    #   And digest-state is NOT written with this video (prune must never treat it as tool-added)
    async def test_already_present_untracked(self, tools, monkeypatch, fake_store):
        calls = _api_fake(monkeypatch, channels=_channels(), pages=[_page([VIDEO_ID])], insert={})
        original = _seed_state(fake_store, "other001", "2026-09-01", "Other Tool Video")

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result == f"OK — {VIDEO_ID} already in Watch Later (not tool-managed; left untracked)"
        _no_insert(calls)
        assert fake_store.docs[NOTE_STATE] == original
        assert VIDEO_ID not in parse_digest_state(original)["tool_added"]

    # @unit
    # Scenario: T3-4 paginated membership
    #   Given playlistItems.list returns the video only on the second page (nextPageToken chain of 2)
    #   When add_to_playlist runs
    #   Then the video is detected as already present (insert NOT called)
    #   And both pages were fetched via the pagination token
    async def test_membership_paginates(self, tools, monkeypatch, fake_store):
        pages = [_page(["vid002"], token="tok2"), _page([VIDEO_ID])]
        calls = _api_fake(monkeypatch, channels=_channels(), pages=pages, insert={})

        result = await tools.add_to_playlist(VIDEO_ID)

        assert "already in Watch Later" in result
        list_params = [params for method, params in calls if method == "playlistItems.list"]
        base = {"part": "contentDetails", "playlistId": PLAYLIST_ID, "maxResults": 5000}
        assert list_params[0] == base
        assert list_params[1] == {**base, "pageToken": "tok2"}
        _no_insert(calls)

    # @unit
    # Scenario: T3-5 reauth
    #   Given the Data API seam raises ReauthNeeded (on channels.list or the membership listing)
    #   When add_to_playlist runs
    #   Then the result starts with "REAUTH_NEEDED"
    #   And it contains the start_auth re-onboarding instruction
    #   And no exception propagates
    #   And digest-state is NOT modified
    @pytest.mark.parametrize(
        "raise_method", ["channels.list", "playlistItems.list"], ids=["on_channels_list", "on_membership_listing"]
    )
    async def test_reauth(self, tools, monkeypatch, fake_store, raise_method):
        calls = _api_fake(
            monkeypatch,
            channels=_channels(),
            pages=[_page(["vid999"])],
            insert={},
            raise_for={raise_method: ReauthNeeded("Google credential rejected by the Data API")},
        )
        original = _seed_state(fake_store, "old001", "2026-09-01", "Old Tool Added")

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result.startswith("REAUTH_NEEDED")
        assert "Google credential rejected by the Data API" in result
        assert "run start_auth" in result
        assert "finish_auth" in result
        _no_insert(calls)
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-6 validation errors
    #   Given the cases:
    #     | case       | setup                                    | expected substring   | data api calls |
    #     | bad_valve  | digest_playlist = "custom"               | "watch_later"        | none           |
    #     | empty_id   | video_id = ""                            | "video_id"           | none           |
    #     | no_channel | channels.list returns no items           | "Watch Later"        | 1 (resolve)    |
    #   When add_to_playlist runs for each case
    #   Then the result starts with "Error:" and contains the expected text
    #   And no insert happens and digest-state is NOT modified
    # (key_missing row: Behaviour contract - items present but the watchLater key is missing)
    @pytest.mark.parametrize(
        ("case", "video_id", "expect"),
        [
            ("bad_valve", VIDEO_ID, "watch_later"),
            ("empty_id", "", "video_id"),
            ("no_channel", VIDEO_ID, "Watch Later"),
            ("key_missing", VIDEO_ID, "Watch Later"),
        ],
        ids=["bad_valve", "empty_id", "no_channel", "key_missing"],
    )
    async def test_validation_and_resolution_errors(self, tools, monkeypatch, fake_store, case, video_id, expect):
        if case == "bad_valve":
            tools.valves.digest_playlist = "custom"
        channels = _channels(items=False) if case == "no_channel" else _channels(with_key=case != "key_missing")
        calls = _api_fake(monkeypatch, channels=channels, pages=[_page([VIDEO_ID])], insert={})
        original = _seed_state(fake_store, "old001", "2026-09-01", "Old Tool Added")

        result = await tools.add_to_playlist(video_id)

        assert result.startswith("Error:")
        assert expect in result
        if case in ("bad_valve", "empty_id"):
            assert calls == []
        else:
            assert [method for method, _ in calls] == ["channels.list"]
        _no_insert(calls)
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-7 io errors
    #   Given the Data API seam raises one of: QuotaError (quotaExceeded) / a generic HTTP failure
    #   When add_to_playlist runs
    #   Then the result starts with "YouTube Error:" and contains the failure detail
    #   And no exception propagates and digest-state is NOT modified
    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            (QuotaError("YouTube Data API quota exceeded"), "YouTube Data API quota exceeded"),
            (Exception("backend 500: upstream timeout"), "backend 500: upstream timeout"),
        ],
        ids=["quota_exceeded", "http_failure"],
    )
    async def test_io_errors(self, tools, monkeypatch, fake_store, error, detail):
        calls = _api_fake(
            monkeypatch,
            channels=_channels(),
            pages=[_page(["vid999"])],
            insert={},
            raise_for={"channels.list": error},
        )
        original = _seed_state(fake_store, "old001", "2026-09-01", "Old Tool Added")

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result.startswith("YouTube Error:")
        assert detail in result
        _no_insert(calls)
        assert fake_store.docs[NOTE_STATE] == original

    # @unit
    # Scenario: T3-8 state failures
    #   Given the insert succeeds and the state store misbehaves in one of the cases:
    #     | case         | store behaviour        | expected                                       |
    #     | read_raises  | read raises            | treated as absent; entry still recorded+written |
    #     | write_raises | write raises           | result still OK + warning "state record failed" |
    #   When add_to_playlist runs
    #   Then no exception propagates in either case
    #   And the add itself is reported OK in both cases
    @pytest.mark.parametrize("case", ["read_raises", "write_raises"], ids=["read_raises", "write_raises"])
    async def test_state_store_failures(self, tools, monkeypatch, fake_store, case):
        if case == "write_raises":

            def write_boom(title, md):
                raise RuntimeError("state write failed")

            monkeypatch.setattr(fake_store, "write", write_boom)
        else:
            fake_store.raise_on_read = True
        _api_fake(monkeypatch, channels=_channels(), pages=[_page(["vid999"])], insert={"snippet": {"title": TITLE}})

        result = await tools.add_to_playlist(VIDEO_ID)

        assert result.startswith("OK")
        if case == "read_raises":
            assert "state record failed" not in result
            state = parse_digest_state(fake_store.docs[NOTE_STATE])
            assert state["tool_added"][VIDEO_ID]["title"] == TITLE
        else:
            assert "state record failed: state write failed" in result
            assert NOTE_STATE not in fake_store.docs
