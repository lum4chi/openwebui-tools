"""T4 prune resilience: partial failure (T4-10), state write failure (T4-11), default playlists never touched (T4-12)."""

from datetime import datetime, timedelta

import pytest

from youtube_manager import NOTE_FEEDBACK, NOTE_STATE, QuotaError, _decode_api_response, parse_digest_state

from .conftest import (
    DIGEST_PLAYLIST_ID,
    api_fake,
    channels_reply,
    item_row,
    listing_page,
    sample_feedback_log,
    seed_state,
)

PL = DIGEST_PLAYLIST_ID
W = "WL-DEFAULT"
VID_A = "vidA"
NEW_VID = "vid010"
REASON = "pruned out"


def days_ago(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


class TestPruneResilience:
    """prune_playlist: failure handling (T4-10, T4-11)."""

    # @unit [AC-B2]
    # Scenario: T7-2 partial prune failure keeps the partial removal line
    #   Given two items qualify for removal and the first delete succeeds but the second raises
    #   When prune_playlist runs
    #   Then the first line is exactly "Error: {clean_reason}"
    #   And the second line is exactly "partial: 1 item(s) removed before failure"
    #   And the result does not start with "Local Error:" or "YouTube Error:"
    #   And no further delete is attempted after the failure
    #   And digest-state is updated only for the successfully removed item
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (RuntimeError("backend 500"), "Error: unexpected error\npartial: 1 item(s) removed before failure"),
            (
                QuotaError("YouTube Data API quota exceeded"),
                "Error: quota reached\npartial: 1 item(s) removed before failure",
            ),
        ],
        ids=["local_code_error", "provider_quota_error"],
    )
    async def test_partial_failure(self, tools, monkeypatch, fake_store, error, expected):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidB": (days_ago(5), "Video B"), "vidA": (days_ago(10), "Video A")}, playlist_id=PL)
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
            [(today, "vidA", "watched", "", "digest", REASON), (today, "vidB", "skipped", "", "digest", REASON)]
        )
        rows = [item_row("plB", "vidB"), item_row("plA", "vidA")]
        calls = api_fake(monkeypatch, {PL: [listing_page(rows)]}, deletes=[None, error])

        result = await tools.prune_playlist()

        assert result == expected
        assert [m for m, _ in calls].count("playlistItems.delete") == 2
        assert [p["id"] for m, p in calls if m == "playlistItems.delete"] == ["plB", "plA"]
        state = parse_digest_state(fake_store.docs[NOTE_STATE])["tool_added"]
        assert "vidB" not in state
        assert state["vidA"] == {"added_at": days_ago(10), "title": "Video A"}

    # @unit
    # Scenario: T4-11 state write failure
    #   Given the deletions succeed but the digest-state write raises
    #   When prune_playlist runs
    #   Then the result still reports the removals OK
    #   And it contains a warning line about the state record
    #   And no exception propagates
    async def test_state_write_failure(self, tools, monkeypatch, fake_store):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidA": (days_ago(10), "Video A")}, playlist_id=PL)
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log([(today, "vidA", "watched", "", "digest", REASON)])
        original = fake_store.docs[NOTE_STATE]

        def write_boom(title, md):
            raise RuntimeError("state write failed")

        monkeypatch.setattr(fake_store, "write", write_boom)
        api_fake(monkeypatch, {PL: [listing_page([item_row("plA", "vidA")])]})

        result = await tools.prune_playlist()

        assert (
            result == f"OK — pruned 1 item(s)\n- vidA — Video A: watched {today}\nstate record failed: unexpected error"
        )
        assert fake_store.docs[NOTE_STATE] == original


class TestDefaultPlaylistsNeverTouched:
    """T4-12: the default Watch Later / Watch History are never resolved, listed, or touched."""

    # @unit
    # Scenario: T4-12 default playlists untouched
    #   Given the custom digest playlist (valve title, id P) exists in the API mock
    #   And the default Watch Later playlist (id W, as the user's channel contentDetails would expose it) holds user-saved items
    #   And digest-state has playlist_id = P and tracks tool-added item A (present in P)
    #   When one of the cases runs:
    #     | case  | method                                  |
    #     | add   | add_to_playlist for a new video_id      |
    #     | prune | prune_playlist (A qualifies for removal) |
    #   Then every playlistItems.insert / playlistItems.delete call names playlist id P only
    #   And channels.list is never called by the method under test
    #   And no call references the default Watch Later id W (its videos are never insert or delete candidates)
    #   And no playlist other than the valve-title resolve-or-create is created or deleted
    @pytest.mark.parametrize("case", ["add", "prune"])
    async def test_never_touched(self, tools, monkeypatch, fake_store, case):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {VID_A: (days_ago(10), "Video A")}, playlist_id=PL)
        wl_items = [item_row("plW1", "w1"), item_row("plW2", "w2")]
        if case == "prune":
            fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log([(today, VID_A, "watched", "", "digest", REASON)])
            pages = {PL: [listing_page([item_row("plA", VID_A)])], W: [listing_page(wl_items)]}
            calls = api_fake(monkeypatch, pages, channels=channels_reply(W))
            result = await tools.prune_playlist()
        else:
            pages = {PL: [listing_page([])], W: [listing_page(wl_items)]}
            calls = api_fake(
                monkeypatch, pages, channels=channels_reply(W), insert_reply={"snippet": {"title": "Brand New Video"}}
            )
            result = await tools.add_to_playlist(NEW_VID)

        assert result.startswith("OK")
        methods = [method for method, _ in calls]
        assert "channels.list" not in methods
        assert "playlists.list" not in methods
        assert "playlists.insert" not in methods
        for method, params in calls:
            blob = str(params)
            for needle in (W, "w1", "w2", "plW1", "plW2"):
                assert needle not in blob
            if method == "playlistItems.insert":
                assert params["body"] == {
                    "snippet": {"playlistId": PL, "resourceId": {"kind": "youtube#video", "videoId": NEW_VID}}
                }
        if case == "add":
            assert methods == ["playlistItems.list", "playlistItems.insert"]
            assert "playlistItems.delete" not in methods
        else:
            assert [p["id"] for m, p in calls if m == "playlistItems.delete"] == ["plA"]
            assert "playlistItems.insert" not in methods


class TestPruneApiDecodeGuard:
    """B3: prune_playlist guards a transient empty/non-JSON Data API response behind a clean retryable error."""

    # @unit
    # Scenario: T2-1 no prior state -> clean early return
    #   Given no prior digest-state (no tracked items)
    #   When prune_playlist runs
    #   Then it returns "OK — nothing to prune (no tracked items)"
    #   And no Data API call is made
    async def test_no_prior_state_clean_early_return(self, tools, monkeypatch, fake_store):
        def boom(valves, method, params):
            raise AssertionError("no Data API call expected in the empty-state early return")

        monkeypatch.setattr("youtube_manager._data_api_execute", boom)

        result = await tools.prune_playlist()

        assert result == "OK — nothing to prune (no tracked items)"

    # @unit
    # Scenario: T2-2 transient empty Data API response -> clean retryable error
    #   Given prior state with one tracked item and a resolved playlist id
    #   And the Data API transport returns a transient empty/blank body
    #   When prune_playlist runs
    #   Then it returns "Error: invalid API response"
    #   And the message does NOT surface the raw "Expecting value" JSON decode detail
    async def test_transient_empty_api_clean_error(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {VID_A: (days_ago(10), "Video A")}, playlist_id=PL)
        monkeypatch.setattr("youtube_manager._data_api_execute", lambda valves, method, params: b"")

        result = await tools.prune_playlist()

        assert result == "Error: invalid API response"
        assert "Expecting value" not in result

    # @unit
    # Scenario: T2-3 _decode_api_response guard (direct unit)
    #   Given a raw Data API payload
    #   When _decode_api_response runs
    #   Then empty bytes, whitespace bytes, and non-JSON bytes raise ValueError("empty or non-JSON ...")
    #   And valid JSON bytes parse to the expected dict
    @pytest.mark.parametrize(
        ("raw", "expect"),
        [
            (b"", ValueError),
            (b"   \n\t  ", ValueError),
            (b"not json at all", ValueError),
            (b'{"a": 1}', {"a": 1}),
        ],
        ids=["empty", "whitespace", "non_json", "valid_json"],
    )
    def test_decode_api_response_guard(self, raw, expect):
        if expect is ValueError:
            with pytest.raises(ValueError, match="empty or non-JSON"):
                _decode_api_response(raw)
        else:
            assert _decode_api_response(raw) == expect
