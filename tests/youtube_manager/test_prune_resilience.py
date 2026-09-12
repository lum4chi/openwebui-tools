"""T4 prune resilience: no-op/guard (T4-8), reauth + boundary errors (T4-9), partial failure (T4-10), state write failure (T4-11)."""

from datetime import datetime, timedelta

import pytest

from youtube_manager import NOTE_FEEDBACK, NOTE_STATE, QuotaError, ReauthNeeded, parse_digest_state

from .conftest import api_fake, channels_reply, item_row, listing_page, sample_feedback_log, seed_state

REASON = "pruned out"


def days_ago(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


class TestPrune:
    """prune_playlist: guard, no-op, and failure handling."""

    # @unit
    # Scenario: T4-8 noop and guard
    #   Given one of the cases:
    #     | case           | setup                                | expected                                     |
    #     | no_state       | digest-state absent                  | OK "nothing to prune (no tracked items)"     |
    #     | state_raises   | digest-state read raises             | same as no_state                             |
    #     | bad_valve      | digest_playlist = "custom"           | Error naming "watch_later"                   |
    #   When prune_playlist runs
    #   Then no Data API call is made in any case and no exception propagates
    #   And no deletion is attempted and digest-state is NOT written
    # (resolve_missing row: completeness — the Error & return contract branch for an unresolvable
    #  Watch Later id; mirrors the T3-6 no_channel/key_missing rows, not part of the T4-8 table)
    @pytest.mark.parametrize("case", ["no_state", "state_raises", "bad_valve", "resolve_missing"])
    async def test_noop_and_valve_guard(self, tools, monkeypatch, fake_store, case):
        if case == "state_raises":
            fake_store.raise_on_read = True
        elif case == "bad_valve":
            tools.valves.digest_playlist = "custom"
        elif case == "resolve_missing":
            seed_state(fake_store, {"vidA": (days_ago(5), "Video A")})
        channels = {"items": []} if case == "resolve_missing" else channels_reply()
        calls = api_fake(monkeypatch, channels, [])

        result = await tools.prune_playlist()

        if case in ("no_state", "state_raises"):
            assert result == "OK — nothing to prune (no tracked items)"
            assert calls == []
            assert fake_store.docs == {}
        elif case == "bad_valve":
            assert result == "Error: only the watch_later playlist is managed in v1"
            assert calls == []
            assert fake_store.docs == {}
        else:
            assert result == "Error: could not resolve the Watch Later playlist id"
            assert [m for m, _ in calls] == ["channels.list"]
            assert NOTE_STATE in fake_store.docs
            assert parse_digest_state(fake_store.docs[NOTE_STATE])["tool_added"]

    # @unit
    # Scenario: T4-9 reauth
    #   Given the Data API seam raises ReauthNeeded (on playlist resolution, the item listing, or a delete)
    #   When prune_playlist runs
    #   Then the result starts with "REAUTH_NEEDED"
    #   And it contains the start_auth re-onboarding instruction
    #   And no exception propagates
    # (generic rows: completeness — the boundary generic Data API failure branch of the Error & return
    #  contract; mirrors the T3-7 io-error rows, not part of the T4-9 table)
    @pytest.mark.parametrize(
        ("case", "error"),
        [
            ("on_playlist_resolution", ReauthNeeded("Google credential rejected by the Data API")),
            ("on_item_listing", ReauthNeeded("Google credential rejected by the Data API")),
            ("on_delete", ReauthNeeded("Google credential rejected by the Data API")),
            ("generic_on_resolution", RuntimeError("backend 500: upstream timeout")),
            ("generic_on_listing", QuotaError("YouTube Data API quota exceeded")),
        ],
    )
    async def test_reauth(self, tools, monkeypatch, fake_store, case, error):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidA": (days_ago(10), "Video A")})
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log([(today, "vidA", "watched", "", "digest", REASON)])
        original = fake_store.docs[NOTE_STATE]
        method = {
            "on_playlist_resolution": "channels.list",
            "generic_on_resolution": "channels.list",
            "on_item_listing": "playlistItems.list",
            "generic_on_listing": "playlistItems.list",
            "on_delete": "playlistItems.delete",
        }[case]
        pages = [] if method == "channels.list" else [listing_page([item_row("plA", "vidA")])]
        calls = api_fake(monkeypatch, channels_reply(), pages, raise_for={method: error})

        result = await tools.prune_playlist()

        if case == "on_delete":
            assert [m for m, _ in calls] == ["channels.list", "playlistItems.list", "playlistItems.delete"]
        else:
            assert "playlistItems.delete" not in [m for m, _ in calls]
        assert fake_store.docs[NOTE_STATE] == original
        if isinstance(error, ReauthNeeded):
            assert result.startswith("REAUTH_NEEDED")
            assert "Google credential rejected by the Data API" in result
            assert "run start_auth" in result
            assert "finish_auth" in result
        else:
            assert result == f"YouTube Error: {error}"

    # @unit
    # Scenario: T4-10 partial failure
    #   Given two items qualify for removal and the first delete succeeds but the second raises
    #   When prune_playlist runs
    #   Then the result starts with "YouTube Error:" and contains a "partial:" line naming the 1 succeeded removal
    #   And no further delete is attempted after the failure
    #   And digest-state is updated only for the successfully removed item
    async def test_partial_failure(self, tools, monkeypatch, fake_store):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidB": (days_ago(5), "Video B"), "vidA": (days_ago(10), "Video A")})
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
            [(today, "vidA", "watched", "", "digest", REASON), (today, "vidB", "skipped", "", "digest", REASON)]
        )
        rows = [item_row("plB", "vidB"), item_row("plA", "vidA")]
        calls = api_fake(
            monkeypatch, channels_reply(), [listing_page(rows)], deletes=[None, RuntimeError("backend 500")]
        )

        result = await tools.prune_playlist()

        assert result == "YouTube Error: backend 500\npartial: 1 item(s) removed before failure"
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
        seed_state(fake_store, {"vidA": (days_ago(10), "Video A")})
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log([(today, "vidA", "watched", "", "digest", REASON)])
        original = fake_store.docs[NOTE_STATE]

        def write_boom(title, md):
            raise RuntimeError("state write failed")

        monkeypatch.setattr(fake_store, "write", write_boom)
        api_fake(monkeypatch, channels_reply(), [listing_page([item_row("plA", "vidA")])])

        result = await tools.prune_playlist()

        assert (
            result
            == f"OK — pruned 1 item(s)\n- vidA — Video A: watched {today}\nstate record failed: state write failed"
        )
        assert fake_store.docs[NOTE_STATE] == original
