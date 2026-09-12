"""T0 state store (Notes / file fallback) + feedback-log + digest-state (T0-7..T0-10)."""

import pytest

from youtube_manager import (
    NOTE_FEEDBACK,
    NOTE_STATE,
    NOTE_TASTE,
    FeedbackEntry,
    _state_store,
    parse_digest_state,
    parse_feedback_log,
    serialize_digest_state,
    serialize_feedback_line,
)

from .conftest import FakeRequest, sample_feedback_log

TITLES = (NOTE_TASTE, NOTE_FEEDBACK, NOTE_STATE)


class TestStateStore:
    """read/write over Notes API (forwarded JWT) or file fallback."""

    # @unit
    # Scenario: T0-7 notes store
    #   Given a request carrying the caller's authorization header
    #   And the Notes API seam answers
    #   When the store reads then writes the "feedback-log" document
    #   Then it calls the Notes API with the caller's authorization header forwarded verbatim
    #   And the written markdown round-trips through read
    def test_notes_round_trip(self, fake_state):
        request = FakeRequest(
            headers={"authorization": "Bearer caller-jwt"},
            base_url="http://localhost:3000/",
        )
        store = _state_store(request)
        assert store.read(NOTE_FEEDBACK) is None  # empty store -> None
        md = sample_feedback_log([("2026-09-01", "vid1", "watched", "A", "recommended", "")])
        store.write(NOTE_FEEDBACK, md)
        assert store.read(NOTE_FEEDBACK) == md
        assert fake_state.calls, "Notes API seam was not called"
        for _method, url, auth, _payload in fake_state.calls:
            assert auth == "Bearer caller-jwt"
            assert url.startswith("http://localhost:3000")
            assert "notes" in url

    # @unit
    # Scenario: T0-8 file fallback
    #   Given no request (or no authorization header) and DATA_DIR set to a temp dir
    #   When the store reads and writes each state document
    #   Then it creates <title>.md files under DATA_DIR
    #   And the content round-trips
    #   And document names are exactly taste-profile / feedback-log / digest-state
    @pytest.mark.parametrize(
        ("req", "unset_env"),
        [
            (None, False),
            (FakeRequest(headers={}, base_url="http://x/"), False),
            (None, True),
        ],
        ids=["no_request", "no_auth_header", "no_data_dir_cwd_fallback"],
    )
    def test_file_fallback(self, req, unset_env, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        if unset_env:
            monkeypatch.delenv("DATA_DIR", raising=False)
            monkeypatch.chdir(tmp_path)
        else:
            monkeypatch.setenv("DATA_DIR", str(data_dir))
        store = _state_store(req)
        for title in TITLES:
            md = f"# {title}\nbody"
            store.write(title, md)
            path = data_dir / f"{title}.md"
            assert path.exists()
            assert path.read_text() == md
            assert store.read(title) == md


class TestFeedbackLog:
    # @unit
    # Scenario: T0-9 feedback log round trip
    #   Given a feedback-log markdown with N valid rows in the contract format
    #   When it is parsed
    #   Then N FeedbackEntry rows come back with date, video_id, decision, title, source, reason
    #   And rows with a bad decision or missing columns are skipped without error
    #   And serialize_feedback_line(parse(row)) reproduces the row
    def test_round_trip(self):
        rows = [
            ("2026-09-01", "vid1", "watched", "Video One", "recommended", "great"),
            ("2026-09-02", "vid2", "skipped", "Video Two", "subscriptions", "too long"),
        ]
        entries = parse_feedback_log(sample_feedback_log(rows))
        assert len(entries) == len(rows)
        for entry, row in zip(entries, rows, strict=True):
            assert isinstance(entry, FeedbackEntry)
            assert (entry.date, entry.video_id, entry.decision, entry.title, entry.source, entry.reason) == row
            assert (
                serialize_feedback_line(entry) == f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |"
            )

    def test_malformed_skipped(self):
        lines = [
            "| date | video_id | decision | title | source | reason |",
            "| 2026-09-01 | vid1 | watched | A | recommended | ok |",
            "",
            "2026-09-05|vid5|watched|E|recommended|unbordered csv row",
            "| 2026-09-02 | vid2 | maybe | B | recommended | bad decision |",
            "| 2026-09-03 | vid3 | listened |",
            "| 2026-09-04 | vid4 | skipped | D | search | fine |",
        ]
        entries = parse_feedback_log("\n".join(lines) + "\n")
        assert [e.video_id for e in entries] == ["vid1", "vid4"]


class TestDigestState:
    # @unit
    # Scenario: T0-10 digest state round trip
    #   Given a digest-state markdown with a fenced JSON block of tool_added entries
    #   When it is parsed
    #   Then the video ids, added_at dates and titles come back unchanged
    #   And serialize_digest_state(parse(md)) reproduces the fenced block
    #   And missing/invalid JSON yields an empty state without error
    def test_round_trip(self):
        state = {
            "tool_added": {
                "vid1": {"added_at": "2026-09-01", "title": "Video One"},
                "vid2": {"added_at": "2026-09-02", "title": "Video Two"},
            }
        }
        md = serialize_digest_state(state)
        assert parse_digest_state(md) == state
        assert serialize_digest_state(parse_digest_state(md)) == md

    @pytest.mark.parametrize(
        "md",
        ["", "no fenced block here", "```json\n{not valid json}\n```"],
        ids=["empty", "no_fenced_block", "invalid_json"],
    )
    def test_invalid_json_empty(self, md):
        assert parse_digest_state(md) == {}
