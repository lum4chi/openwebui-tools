"""T0-1 S5 unit mirror (acceptance run with canned seams) + main() exit-code contract (S6 mirror).

S5 pins the 5-step acceptance run and the instrumentation log for BOTH response shapes
(raw bytes per the real API path; dict per the api_fake convention). The main() tests pin
the thin live-runner orchestration: exit 0 iff all steps PASS, else 1; missing .env -> 1.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

import youtube_manager as ym

from .conftest import (
    api_fake,
    guard_urlopen,
    item_row,
    listing_page,
    playlist_item,
    playlist_row,
    sub_channel,
    uploads_channel_reply,
    video_detail,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _REPO_ROOT / "dev" / "youtube_live.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("dev_youtube_live_run", _HARNESS)
    if spec is None or spec.loader is None:
        raise AssertionError("harness spec/loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hl = _load_harness()


def _canned() -> dict:
    channels_by_id: dict = {
        None: {"items": [{"id": "chan-self", "snippet": {"title": "Self Channel"}}]},
        "ch1": uploads_channel_reply("up1"),
        "ch2": uploads_channel_reply("up2"),
    }
    return dict(
        pages={
            "PLWL": [
                listing_page([]),
                listing_page([item_row("it-wl-1", "vid-wl-1"), item_row("it-wl-2", "vid-wl-2")]),
            ],
            "up1": [listing_page([playlist_item("vid-up1", "Up video 1", "Channel 1", "2026-01-01T00:00:00Z")])],
            "up2": [listing_page([playlist_item("vid-up2", "Up video 2", "Channel 2", "2026-01-02T00:00:00Z")])],
        },
        playlist_pages=[
            listing_page([playlist_row("PLWL", "Watch Later")]),
            listing_page([playlist_row("PL1", "Playlist One"), playlist_row("PL2", "Playlist Two")]),
            listing_page([playlist_row("PLWL", "Watch Later")]),
        ],
        subscription_pages=[
            {"items": []},
            {"items": [sub_channel("ch1", "Channel 1"), sub_channel("ch2", "Channel 2")]},
        ],
        channels_by_id=channels_by_id,
        videos={
            vid: video_detail(vid, duration="PT1M30S", title=f"Video {vid}")
            for vid in ("vid-wl-1", "vid-wl-2", "vid-up1", "vid-up2")
        },
    )


def _patch_seams(monkeypatch, shape="dict", empty_identity=False) -> None:
    canned = _canned()
    if empty_identity:
        canned["channels_by_id"][None] = {"items": []}
    api_fake(monkeypatch, **canned)
    if shape == "bytes":
        delegate = ym._data_api_execute

        def bytes_shape(valves, method, params, user_id=None):
            return json.dumps(delegate(valves, method, params, user_id)).encode("utf-8")

        monkeypatch.setattr("youtube_manager._data_api_execute", bytes_shape)
    monkeypatch.setattr("youtube_manager._oauth_token", lambda valves, code=None, user_id=None: {"access_token": "tok"})
    guard_urlopen(monkeypatch)


def _env_text(data_dir: Path) -> str:
    return (
        "YTM_GOOGLE_CLIENT_ID=client-id\n"
        "YTM_GOOGLE_CLIENT_SECRET=client-secret\n"
        "YTM_USER_ID=u1\n"
        f"YTM_DATA_DIR={data_dir}\n"
    )


def _seed_token(data_dir: Path, user_id: str = "u1", token: str = "fresh-token") -> Path:
    """Pre-create the post-run_auth token file so run_auth's reuse guard skips the browser flow."""
    token_path = data_dir / user_id / f"{ym.CREDENTIAL_TITLE}.md"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token)
    return token_path


class TestAcceptanceRun:
    # @unit
    # Scenario: T0-1-S5 (unit, mocked seams, no network): acceptance run with canned responses
    #   Given a harness run against mocked seams (youtube_manager._data_api_execute / _oauth_token fakes,
    #     guard_urlopen active) with canned responses (2 playlists, non-empty WL, non-empty feeds) and the
    #     token file already present (post-run_auth: the browser flow was faked; the token sits in
    #     <DATA_DIR>/u1/google-refresh-token.md)
    #   When run_acceptance executes the 5 steps
    #   Then identity resolves the canned account, check_setup is READY, list_playlists enumerates,
    #     watch_later returns items, subscriptions return candidates
    #   And the instrumentation log records per call {method, params, user_id, items} for BOTH
    #      response shapes (raw bytes per the real API path; dict per the api_fake convention —
    #      parametrize), including the WL raw item count and per-feed counts
    @pytest.mark.parametrize("shape", ["dict", "bytes"])
    async def test_all_five_steps_pass_with_evidence(self, tools, monkeypatch, shape):
        _patch_seams(monkeypatch, shape)
        _seed_token(Path(os.environ["DATA_DIR"]))
        log = hl.instrument()

        results = await hl.run_acceptance(tools, {"YTM_USER_ID": "u1"}, log)

        names = [name for name, _, _, _ in results]
        assert names == ["identity", "check_setup", "list_playlists", "watch_later", "subscriptions"]
        assert all(ok for _, ok, _, _ in results)
        assert "chan-self" in results[0][2]
        assert all(ts for _, _, _, ts in results)  # T1-5 re-pin: every step result carries a completion ts
        assert log
        for entry in log:
            assert set(entry) == {"method", "params", "user_id", "items", "ts"}  # T1-5 re-pin: + call-time ts
            assert entry["ts"]
        title = tools.valves.watch_later_playlist_title
        assert hl._wl_raw_items(log, title) == 2
        assert hl._feed_counts(log, title) == {"up1": 1, "up2": 1}


class TestTimestampedReport:
    # @unit
    # Scenario T1-5-S1 (unit): the run output carries a run-start, per-api-line and per-step timestamp
    #   # trace: user (b) adopted request — "harness output must carry a run-start timestamp + per-api-line + per-step timestamps so time gaps are assessable in future runs"
    #   Given a canned 5-step harness run with an injected fixed clock
    #   When the report is rendered
    #   Then the first output line is a run-start line carrying the clock timestamp
    #   And every api line carries a timestamp
    #   And every step result line carries a timestamp
    async def test_report_carries_run_start_and_per_line_timestamps(self, tools, monkeypatch):
        _patch_seams(monkeypatch, "dict")
        ts = "2026-09-30T12:00:00"
        monkeypatch.setattr(hl, "_clock", lambda: ts)
        log = hl.instrument()

        results = await hl.run_acceptance(tools, {"YTM_USER_ID": "u1"}, log)
        lines = hl._render_report(results, log, ts).splitlines()

        assert lines[0] == f"live-run started {ts}"
        step_lines = lines[1:6]
        api_lines = lines[6:]
        assert len(step_lines) == 5
        assert all(line.startswith(f"[{ts}] ") for line in step_lines)
        assert api_lines and all(line.startswith(f"[{ts}] api: ") for line in api_lines)


class TestMain:
    """main() exit-code contract (S6 mirror): 0 iff all steps PASS, 1 otherwise / on env error."""

    def test_missing_env_returns_1(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)

        assert hl.main() == 1

        assert "env.template" in capsys.readouterr().out

    def test_all_pass_returns_0(self, monkeypatch, tmp_path):
        data_dir = tmp_path / "data-live"
        (tmp_path / ".env").write_text(_env_text(data_dir))
        _seed_token(data_dir)
        monkeypatch.chdir(tmp_path)
        _patch_seams(monkeypatch, "dict")

        assert hl.main() == 0

    def test_identity_fail_returns_1(self, monkeypatch, tmp_path):
        data_dir = tmp_path / "data-live"
        (tmp_path / ".env").write_text(_env_text(data_dir))
        _seed_token(data_dir)
        monkeypatch.chdir(tmp_path)
        _patch_seams(monkeypatch, "dict", empty_identity=True)

        assert hl.main() == 1


class TestStepListPlaylists:
    """_step_list_playlists FAIL branch: a non-header reply (e.g. reauth) is a hard FAIL."""

    async def test_non_header_reply_returns_fail(self):
        class _StubTools:
            async def list_playlists(self) -> str:
                return "REAUTH_NEEDED: please re-link your Google account"

        name, ok, detail = await hl._step_list_playlists(_StubTools(), "u1")

        assert (name, ok) == ("list_playlists", False)
        assert "REAUTH_NEEDED" in detail
