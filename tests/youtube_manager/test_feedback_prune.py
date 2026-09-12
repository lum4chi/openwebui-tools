"""T4 feedback logging + prune policy: record_feedback (T4-1…T4-2), prune happy paths (T4-3…T4-7)."""

from datetime import datetime, timedelta

import pytest

from youtube_manager import NOTE_FEEDBACK, NOTE_STATE, parse_digest_state

from .conftest import api_fake, channels_reply, item_row, listing_page, sample_feedback_log, seed_state

HEADER = "| date | video_id | decision | title | source | reason |"
REASON = "too long"


def days_ago(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


class TestRecordFeedback:
    """record_feedback: validated append to the feedback-log document."""

    # @unit
    # Scenario: T4-1 append row
    #   Given the feedback-log is one of: absent / contains prior valid rows / its read raises
    #   And the decision is valid ("watched") and video_id is non-empty
    #   When record_feedback runs with a reason
    #   Then the result starts with "OK" and names the decision and video_id
    #   And the written document carries the contract header plus a new last row: today, video_id, watched, empty title, source "digest", the reason
    #   And any prior rows are preserved in order
    #   And the read-raise case behaves exactly like the absent case (no crash)
    # (write_raises row: Behaviour contract - the append IS the operation, so a failed write is an Error
    #  carrying the "state record failed" convention)
    @pytest.mark.parametrize("case", ["absent", "prior_rows", "read_raises", "write_raises"])
    async def test_append_row(self, tools, fake_store, monkeypatch, case):
        today = datetime.now().date().isoformat()
        if case == "prior_rows":
            fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
                [("2026-09-01", "vid001", "skipped", "Old Video", "digest", "boring")]
            )
        elif case == "read_raises":
            fake_store.raise_on_read = True
        elif case == "write_raises":

            def write_boom(title, md):
                raise RuntimeError("notes backend down")

            monkeypatch.setattr(fake_store, "write", write_boom)

        result = await tools.record_feedback("vid010", "watched", reason=REASON)

        if case == "write_raises":
            assert result == "Error: state record failed: notes backend down"
            assert NOTE_FEEDBACK not in fake_store.docs
            return
        assert result == "OK — recorded watched for vid010"
        lines = fake_store.docs[NOTE_FEEDBACK].strip().splitlines()
        assert lines[0] == HEADER
        assert lines[-1] == f"| {today} | vid010 | watched |  | digest | {REASON} |"
        if case == "prior_rows":
            assert len(lines) == 3
            assert lines[1] == "| 2026-09-01 | vid001 | skipped | Old Video | digest | boring |"
        else:
            assert len(lines) == 2

    # @unit
    # Scenario: T4-2 validation
    #   Given decision is "loved" or "WATCHED" (no case normalization) or video_id is ""
    #   When record_feedback runs
    #   Then the result starts with "Error:" and names the three valid decisions (or video_id respectively)
    #   And the state store is never read or written
    @pytest.mark.parametrize(
        ("video_id", "decision", "expect"),
        [
            ("vid010", "loved", "Error: decision must be one of: watched, listened, skipped"),
            ("vid010", "WATCHED", "Error: decision must be one of: watched, listened, skipped"),
            ("", "watched", "Error: video_id is required"),
        ],
        ids=["unknown_decision", "case_sensitive", "empty_video_id"],
    )
    async def test_validation(self, tools, fake_store, monkeypatch, video_id, decision, expect):
        reads = []
        real_read = fake_store.read

        def spy_read(title):
            reads.append(title)
            return real_read(title)

        monkeypatch.setattr(fake_store, "read", spy_read)

        result = await tools.record_feedback(video_id, decision)

        assert result == expect
        assert reads == []
        assert fake_store.docs == {}


class TestPrune:
    """prune_playlist: removal policy, report, and digest-state update (happy paths)."""

    # @unit
    # Scenario: T4-3 feedback driven
    #   Given digest-state tracks items A and B (added_at dates) and the playlist contains A, B and a user item U
    #   And the feedback-log has a "watched" row for A dated on/after A's added_at and none for B
    #   When prune_playlist runs
    #   Then playlistItems.delete is called exactly once, for A's playlist item id
    #   And B and U are untouched
    #   And digest-state no longer tracks A but still tracks B
    #   And the report lists A with the decision and date as its reason
    # (paginated row: completeness - the Behaviour contract's "follow nextPageToken" listing
    #  requirement; mirrors the T3-4 pagination scenario, not part of the T4-3 table)
    @pytest.mark.parametrize("layout", ["single_page", "paginated"])
    async def test_feedback_driven(self, tools, monkeypatch, fake_store, layout):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidA": (days_ago(10), "Video A"), "vidB": (days_ago(20), "Video B")})
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log([(today, "vidA", "watched", "", "digest", REASON)])
        if layout == "single_page":
            pages = [listing_page([item_row("plA", "vidA"), item_row("plB", "vidB"), item_row("plU", "vidU")])]
        else:
            pages = [
                listing_page([item_row("plA", "vidA"), item_row("plU", "vidU")], token="tok2"),
                listing_page([item_row("plB", "vidB")]),
            ]
        calls = api_fake(monkeypatch, channels_reply(), pages)

        result = await tools.prune_playlist()

        assert result == f"OK — pruned 1 item(s)\n- vidA — Video A: watched {today}"
        assert [params for method, params in calls if method == "playlistItems.delete"] == [{"id": "plA"}]
        if layout == "paginated":
            list_params = [params for method, params in calls if method == "playlistItems.list"]
            assert list_params[1]["pageToken"] == "tok2"
        state = parse_digest_state(fake_store.docs[NOTE_STATE])
        assert "vidA" not in state["tool_added"]
        assert state["tool_added"]["vidB"] == {"added_at": days_ago(20), "title": "Video B"}

    # @unit
    # Scenario: T4-4 item cap
    #   Given digest-state tracks 5 tool-added items with distinct added_at dates, no feedback rows, digest_max_items = 3
    #   And one of the oldest items ALSO exceeds the age cap
    #   When prune_playlist runs
    #   Then the 2 oldest tool-added items are deleted and the 3 newest are kept
    #   And the dual-violating item is deleted exactly once with a single reason in the report
    #   And the report names each removed item with the item-cap reason
    async def test_item_cap(self, tools, monkeypatch, fake_store):
        tools.valves.digest_max_items = 3
        added = {
            "vid1": days_ago(5),
            "vid2": days_ago(10),
            "vid3": days_ago(15),
            "vid4": days_ago(20),
            "vid5": days_ago(40),
        }
        seed_state(fake_store, {vid: (at, f"Video {vid}") for vid, at in added.items()})
        rows = [
            item_row(f"pl{i}", vid)
            for i, vid in enumerate(sorted(added, key=lambda v: added[v], reverse=True), start=1)
        ]
        calls = api_fake(monkeypatch, channels_reply(), [listing_page(rows)])

        result = await tools.prune_playlist()

        cap_reason = "over digest_max_items (newest 3 kept)"
        assert result == (
            f"OK — pruned 2 item(s)\n- vid4 — Video vid4: {cap_reason}\n- vid5 — Video vid5: {cap_reason}"
        )
        assert "older than digest_max_age_days" not in result
        assert [p["id"] for m, p in calls if m == "playlistItems.delete"] == ["pl4", "pl5"]
        kept = parse_digest_state(fake_store.docs[NOTE_STATE])["tool_added"]
        assert set(kept) == {"vid1", "vid2", "vid3"}

    # @unit
    # Scenario: T4-5 age cap
    #   Given tool-added items dated 45 days ago and 10 days ago, digest_max_age_days = 30, no feedback rows, item cap not reached
    #   When prune_playlist runs
    #   Then only the 45-day item is deleted
    #   And the report names it with the age reason
    async def test_age_cap(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {"vid1": (days_ago(45), "Video 1"), "vid2": (days_ago(10), "Video 2")})
        calls = api_fake(
            monkeypatch, channels_reply(), [listing_page([item_row("pl1", "vid1"), item_row("pl2", "vid2")])]
        )

        result = await tools.prune_playlist()

        assert result == "OK — pruned 1 item(s)\n- vid1 — Video 1: older than digest_max_age_days (45 days)"
        assert [p["id"] for m, p in calls if m == "playlistItems.delete"] == ["pl1"]
        assert set(parse_digest_state(fake_store.docs[NOTE_STATE])["tool_added"]) == {"vid2"}

    # @unit
    # Scenario: T4-6 user safety
    #   Given the playlist holds many user-saved items (untracked in digest-state), some with feedback rows,
    #   And the tool-added items are within both caps with no qualifying feedback
    #   When prune_playlist runs
    #   Then playlistItems.delete is NEVER called
    #   And digest-state is unchanged
    #   And the result reports nothing pruned
    async def test_user_items_never_touched(self, tools, monkeypatch, fake_store):
        today = datetime.now().date().isoformat()
        seed_state(fake_store, {"vidA": (days_ago(5), "Video A")})
        doc = fake_store.docs[NOTE_STATE]
        fake_store.docs[NOTE_FEEDBACK] = sample_feedback_log(
            [(today, "vidU1", "watched", "", "digest", ""), (today, "vidU2", "skipped", "", "digest", "")]
        )
        rows = [item_row(f"plU{i}", f"vidU{i}") for i in (1, 2, 3)] + [item_row("plA", "vidA")]
        calls = api_fake(monkeypatch, channels_reply(), [listing_page(rows)])

        result = await tools.prune_playlist()

        assert result == "OK — nothing to prune (1 tracked item(s) kept)"
        assert [m for m, _ in calls] == ["channels.list", "playlistItems.list"]
        assert fake_store.docs[NOTE_STATE] == doc

    # @unit
    # Scenario: T4-7 stale cleanup
    #   Given digest-state tracks C but the playlist no longer contains C (the user removed it manually)
    #   And all remaining tracked items are within caps with no qualifying feedback
    #   When prune_playlist runs
    #   Then no delete is attempted for C
    #   And the written digest-state no longer tracks C
    #   And the report notes the state cleanup
    async def test_stale_state_cleaned(self, tools, monkeypatch, fake_store):
        seed_state(fake_store, {"vidC": (days_ago(5), "Video C"), "vidD": (days_ago(10), "Video D")})
        calls = api_fake(monkeypatch, channels_reply(), [listing_page([item_row("plD", "vidD")])])

        result = await tools.prune_playlist()

        assert result == "OK — nothing to prune (1 tracked item(s) kept)\nstate cleaned: 1 stale entry removed"
        assert [m for m, _ in calls] == ["channels.list", "playlistItems.list"]
        assert set(parse_digest_state(fake_store.docs[NOTE_STATE])["tool_added"]) == {"vidD"}
