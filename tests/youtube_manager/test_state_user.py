"""T6-1: durable state keyed by the requesting user (data/<user_id>/<note>.md)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_manager import NOTE_FEEDBACK, NOTE_TASTE, _state_store

from .conftest import sample_taste_profile


class TestStateUserKeying:
    """Durable state files live under data/<user_id>/ (fallback: data/default/)."""

    # @unit
    # Scenario: T6-1-S1 state is keyed by the requesting user (unit)
    #   Given a Tools instance with DATA_DIR=tmp
    #   When save_taste_profile(md, __user__={"id": "user-abc-123"})
    #   Then the file tmp/data/user-abc-123/taste-profile.md exists with content md
    #   And a subsequent profile read for the same user returns md
    async def test_state_keyed_by_user(self, tools, tmp_path):
        md = sample_taste_profile(["quantum computing"], [])
        await tools.save_taste_profile(md, __user__={"id": "user-abc-123"})
        path = Path(os.environ["DATA_DIR"]) / "user-abc-123" / "taste-profile.md"
        assert path.exists()
        assert path.read_text() == md
        assert _state_store(None, "user-abc-123").read(NOTE_TASTE) == md

    # @workflow
    # Scenario: T6-1-S2 two users do not clobber each other (workflow)
    #   Given a Tools instance with DATA_DIR=tmp
    #   When user A saves profile PA and records feedback FA
    #   And user B saves profile PB and records feedback FB
    #   Then tmp/data/A-id/taste-profile.md == PA and tmp/data/B-id/taste-profile.md == PB
    #   And A's feedback-log contains only FA and B's feedback-log contains only FB
    async def test_two_users_isolated(self, tools, tmp_path):
        pa = sample_taste_profile(["topic-a"], [])
        pb = sample_taste_profile(["topic-b"], [])
        await tools.save_taste_profile(pa, __user__={"id": "A-id"})
        await tools.save_taste_profile(pb, __user__={"id": "B-id"})
        await tools.record_feedback("vid-a", "watched", reason="FA", __user__={"id": "A-id"})
        await tools.record_feedback("vid-b", "listened", reason="FB", __user__={"id": "B-id"})
        data_dir = Path(os.environ["DATA_DIR"])
        assert (data_dir / "A-id" / "taste-profile.md").read_text() == pa
        assert (data_dir / "B-id" / "taste-profile.md").read_text() == pb
        log_a = _state_store(None, "A-id").read(NOTE_FEEDBACK)
        log_b = _state_store(None, "B-id").read(NOTE_FEEDBACK)
        assert "vid-a" in log_a and "FA" in log_a
        assert "vid-b" not in log_a and "FB" not in log_a
        assert "vid-b" in log_b and "FB" in log_b
        assert "vid-a" not in log_b and "FA" not in log_b

    # @unit
    # Scenario: T6-1-S3 absent or anonymous users fall back to the shared "default" namespace (unit)
    #   Given a Tools instance with DATA_DIR=tmp
    #   When a state write runs with __user__=None, and with __user__={}, and with __user__={"id": ""}
    #   Then all three read and write tmp/data/default/<note>.md
    @pytest.mark.parametrize(
        "user",
        [None, {}, {"id": ""}],
        ids=["none", "empty_dict", "empty_id"],
    )
    async def test_anonymous_fallback_default(self, tools, user):
        md = sample_taste_profile(["shared"], [])
        await tools.save_taste_profile(md, __user__=user)
        path = Path(os.environ["DATA_DIR"]) / "default" / "taste-profile.md"
        assert path.read_text() == md
        assert _state_store(None, "default").read(NOTE_TASTE) == md

    # @unit
    # Scenario: T6-1-S4 malformed user ids are sanitized and can never escape the data dir (unit)
    #   Given a Tools instance with DATA_DIR=tmp
    #   When state writes run with __user__={"id": "../../evil"} and with __user__={"id": "a/b"}
    #   Then the files land at tmp/data/evil/<note>.md and tmp/data/ab/<note>.md
    #   And no file is created outside tmp/data
    @pytest.mark.parametrize(
        ("raw_id", "expected_dir"),
        [("../../evil", "evil"), ("a/b", "ab")],
        ids=["traversal", "slash"],
    )
    async def test_malformed_user_id_sanitized(self, tools, tmp_path, raw_id, expected_dir):
        md = sample_taste_profile(["x"], [])
        await tools.save_taste_profile(md, __user__={"id": raw_id})
        data_dir = Path(os.environ["DATA_DIR"])
        assert (data_dir / expected_dir / "taste-profile.md").read_text() == md
        assert [p.name for p in tmp_path.iterdir()] == ["data"]

    # @unit
    # Scenario: T6-1-S5 legacy instance-wide state is orphaned, not read, not moved (unit)
    #   Given tmp/data/taste-profile.md pre-seeded with legacy content L
    #   When save_taste_profile(md, __user__={"id": "u1"})
    #   Then tmp/data/u1/taste-profile.md == md
    #   And tmp/data/taste-profile.md still == L (untouched)
    #   And a digest/read for u1 does NOT see L
    async def test_legacy_state_orphaned(self, tools, tmp_path):
        data_dir = Path(os.environ["DATA_DIR"])
        data_dir.mkdir(parents=True, exist_ok=True)
        legacy = "# Taste profile\n- legacy"
        (data_dir / "taste-profile.md").write_text(legacy)
        md = sample_taste_profile(["fresh"], [])
        await tools.save_taste_profile(md, __user__={"id": "u1"})
        assert (data_dir / "u1" / "taste-profile.md").read_text() == md
        assert (data_dir / "taste-profile.md").read_text() == legacy
        assert _state_store(None, "u1").read(NOTE_TASTE) == md

    # @unit
    # Scenario: T6-1-S6 the refresh token is per-user and stays 0600 (unit)
    #   Given a Tools instance with OAuth valves configured
    #   When finish_auth completes with __user__={"id": "u1"}
    #   Then tmp/data/u1/google-refresh-token.md exists with mode 0600
    async def test_refresh_token_per_user_0600(self, tools):
        token = {"access_token": "tok", "refresh_token": "u1-refresh", "expires_in": 3600}
        with patch("youtube_manager._oauth_token", return_value=token):
            await tools.finish_auth("code123", __user__={"id": "u1"})
        cred = Path(os.environ["DATA_DIR"]) / "u1" / "google-refresh-token.md"
        assert cred.exists()
        assert (cred.stat().st_mode & 0o777) == 0o600
        assert cred.read_text() == "u1-refresh"
