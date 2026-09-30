"""T1-5 probe units: the dev-only evidence probe (token reuse without re-auth, API-evidence-only output,
per-section failure isolation, exit codes). The probe reuses the harness's load_env/build_tools/token-path
seams, so every unit runs against the api_fake seam with guard_urlopen active (no network)."""

import importlib.util
import json
from pathlib import Path

import pytest

import youtube_manager as ym

from .conftest import api_fake, empty_channel_reply, guard_urlopen, item_row, listing_page, playlist_row, video_detail

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBE = _REPO_ROOT / "dev" / "youtube_live_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("dev_youtube_live_probe", _PROBE)
    if spec is None or spec.loader is None:
        raise AssertionError("probe spec/loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

CLIENT_ID = "probe-client-id"
CLIENT_SECRET = "probe-client-secret"
STORED_TOKEN = "stored-probe-token"
WL_TITLE = "AI evaluation"


def _write_env(tmp_path: Path, data_dir: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"YTM_GOOGLE_CLIENT_ID={CLIENT_ID}\n"
        f"YTM_GOOGLE_CLIENT_SECRET={CLIENT_SECRET}\n"
        "YTM_USER_ID=u1\n"
        f"YTM_DATA_DIR={data_dir}\n"
        f"YTM_WATCH_LATER_PLAYLIST_TITLE={WL_TITLE}\n"
    )
    return env_file


def _seed_token(data_dir: Path, user_id: str = "u1") -> None:
    token_path = data_dir / user_id / f"{ym.CREDENTIAL_TITLE}.md"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(STORED_TOKEN)


def _canned_probe_api(monkeypatch, raise_for: dict | None = None) -> None:
    """Canned probe seams: identity channel, the single videos.list body, a 2-page playlists.list sweep
    (WL row on page 2 — proves the sweep aggregates), one WL playlist item."""
    api_fake(
        monkeypatch,
        pages={"PLwl": [listing_page([item_row("it-wl-1", "vid-wl-1")])]},
        playlist_pages=[
            {"items": [playlist_row("PL1", "Playlist One")], "nextPageToken": "pg2"},
            {"items": [playlist_row("PLwl", WL_TITLE), playlist_row("PL2", "Playlist Two")]},
        ],
        channels={"items": [{"id": "ch-self", "snippet": {"title": "Self Channel"}}]},
        videos={"_4TryLfB_gM": video_detail("_4TryLfB_gM", duration="PT1M30S", title="Live video", views="42")},
        raise_for=raise_for,
    )


# @unit
# Scenario: T4-1-S7 (unit, probe half) — trace: "Remove them from the valve" (harness half)
#   Given the probe prints API evidence only
#   When its output is redaction-checked
#   Then the redaction tuple pins exactly (client id, client secret, stored token)
def _assert_redacted(out: str) -> None:
    for value in (CLIENT_ID, CLIENT_SECRET, STORED_TOKEN):
        assert value not in out


class TestProbeEvidence:
    # @unit
    # Scenario T1-5-S3 (unit): the probe prints API evidence only — never token or secret values
    #   # trace: dispatch task 1 — "The probe output = API evidence only — never token/secret values"
    #   Given the tool seams mocked to return canned responses (a videos.list body, playlist rows, one WL playlist item)
    #   And the probe's dummy env values (client id, client secret) and the stored token value in force
    #   When the probe main runs with captured stdout and the token file present
    #   Then the output contains the videos.list JSON, the WL playlist title and item count, and one id+title line per playlist
    #   And no token, client-secret or valve value appears in the output
    def test_probe_prints_evidence_only(self, monkeypatch, tmp_path, capsys):
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        _canned_probe_api(monkeypatch)
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 0
        video = video_detail("_4TryLfB_gM", duration="PT1M30S", title="Live video", views="42")
        videos_json = json.dumps({"items": [video]}, indent=2, sort_keys=True)
        assert out == (
            f"probe: identity channel_id=ch-self title=Self Channel\n"
            f"probe: videos.list\n"
            f"{videos_json}\n"
            f"probe: wl_playlist id=PLwl title={WL_TITLE}\n"
            f"probe: wl_playlist items=1 more_pages=False\n"
            f"probe: playlists\n"
            f"PL1 Playlist One\n"
            f"PLwl {WL_TITLE}\n"
            f"PL2 Playlist Two\n"
        )
        _assert_redacted(out)


class TestProbeTokenReuse:
    # @unit
    # Scenario T1-5-S4 (unit): the probe reuses the stored token — no re-auth when the token file exists
    #   # trace: dispatch task 1 — "reuses the stored token in .data-live/test_user/, no re-auth"
    #   Given a token file present in the user's data dir
    #   When the probe main runs
    #   Then no auth URL is printed and no input() is requested
    #   And the probe exits 0
    #   And with the token file absent the probe prints the no-stored-token line and exits 2 without any auth prompt
    def test_stored_token_reused_without_reauth(self, monkeypatch, tmp_path, capsys):
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        _canned_probe_api(monkeypatch)
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        def _no_input(prompt: str = "") -> str:
            raise AssertionError("input() must not be requested (no re-auth in the probe)")

        monkeypatch.setattr("builtins.input", _no_input)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 0
        assert "http" not in out
        assert "Paste" not in out
        _assert_redacted(out)

    def test_no_stored_token_prints_line_and_exits_2(self, monkeypatch, tmp_path, capsys):
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        def _no_input(prompt: str = "") -> str:
            raise AssertionError("input() must not be requested (no re-auth in the probe)")

        monkeypatch.setattr("builtins.input", _no_input)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 2
        assert out == "probe: no stored token — run the harness first\n"


class TestProbeSectionIsolation:
    # @unit
    # Scenario T1-5-S6 (unit): a failing probe section is reported without hiding the remaining evidence
    #   # trace: probe contract L1144 — "each independently try/excepted — one failure must not hide the other evidence" + L1149 exit rule
    #     ("Exit 0 iff all sections succeeded, else 2"); dispatch task 1 probe spec (i)-(iii) requires ALL evidence
    #     sections to print (recorded design decision; user has not vetoed — same provenance treatment as T1-4-S4/S5)
    #   Given the tool seams mocked with the videos.list section raising TypeError("Got an unexpected keyword argument ids")
    #   And the token file present, and the identity, wl_playlist and playlists sections returning canned responses
    #   When the probe main runs with captured stdout
    #   Then the line probe: videos.list FAILED class=TypeError detail=Got an unexpected keyword argument ids is printed
    #   And the wl_playlist and playlists sections are still printed with their evidence
    #   And no token or secret value appears in the output
    #   And the probe exits 2
    def test_failing_section_reported_and_run_continues(self, monkeypatch, tmp_path, capsys):
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        _canned_probe_api(monkeypatch, raise_for={"videos.list": TypeError("Got an unexpected keyword argument ids")})
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 2
        assert "probe: videos.list FAILED class=TypeError detail=Got an unexpected keyword argument ids\n" in out
        assert f"probe: wl_playlist id=PLwl title={WL_TITLE}\n" in out
        assert "probe: wl_playlist items=1 more_pages=False\n" in out
        assert "probe: playlists\n" in out
        assert "PL1 Playlist One\n" in out
        _assert_redacted(out)

    def test_sweep_failure_cascades_to_playlists_section(self, monkeypatch, tmp_path, capsys):
        # S6 coverage vehicle: the playlists.list sweep itself raises -> wl_playlist AND playlists both report
        # FAILED (the playlists section has no swept rows to render) while identity + videos.list still print.
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        _canned_probe_api(monkeypatch, raise_for={"playlists.list": RuntimeError("sweep boom")})
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 2
        assert "probe: identity channel_id=ch-self title=Self Channel\n" in out
        assert "probe: videos.list\n" in out
        assert "probe: wl_playlist FAILED class=RuntimeError detail=sweep boom\n" in out
        assert "probe: playlists FAILED class=RuntimeError detail=playlists sweep did not complete\n" in out
        _assert_redacted(out)

    def test_unresolved_wl_title_reports_failed(self, monkeypatch, tmp_path, capsys):
        # S6 coverage vehicle: the sweep succeeds but no row matches the valve title -> wl_playlist FAILED;
        # playlists still renders the swept rows (state was populated before the match failed).
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        api_fake(
            monkeypatch,
            pages={"PLwl": [listing_page([item_row("it-wl-1", "vid-wl-1")])]},
            playlist_pages=[{"items": [playlist_row("PL1", "Playlist One"), playlist_row("PL2", "Playlist Two")]}],
            channels={"items": [{"id": "ch-self", "snippet": {"title": "Self Channel"}}]},
            videos={"_4TryLfB_gM": video_detail("_4TryLfB_gM", duration="PT1M30S", title="Live video", views="42")},
        )
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 2
        assert (
            f"probe: wl_playlist FAILED class=RuntimeError detail=no playlist titled '{WL_TITLE}' among 2 rows\n" in out
        )
        assert "probe: playlists\n" in out
        assert "PL1 Playlist One\n" in out
        _assert_redacted(out)

    def test_unresolved_identity_reports_failed_and_run_continues(self, monkeypatch, tmp_path, capsys):
        # S6 coverage vehicle: channels.list resolves no channel -> probe_identity (None, None) -> the
        # contract-mandated identity None-raise, reported as FAILED while the remaining evidence
        # sections still print.
        data_dir = tmp_path / "data-live"
        env_file = _write_env(tmp_path, data_dir)
        _seed_token(data_dir)
        api_fake(
            monkeypatch,
            pages={"PLwl": [listing_page([item_row("it-wl-1", "vid-wl-1")])]},
            playlist_pages=[
                {"items": [playlist_row("PL1", "Playlist One")], "nextPageToken": "pg2"},
                {"items": [playlist_row("PLwl", WL_TITLE), playlist_row("PL2", "Playlist Two")]},
            ],
            channels=empty_channel_reply(),
            videos={"_4TryLfB_gM": video_detail("_4TryLfB_gM", duration="PT1M30S", title="Live video", views="42")},
        )
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        guard_urlopen(monkeypatch)

        rc = probe.main([str(env_file)])
        out = capsys.readouterr().out

        assert rc == 2
        assert (
            "probe: identity FAILED class=RuntimeError detail=no channel resolved: channels.list mine=true empty\n"
            in out
        )
        assert "probe: videos.list\n" in out
        assert f"probe: wl_playlist id=PLwl title={WL_TITLE}\n" in out
        _assert_redacted(out)


class TestProbeLoadHarness:
    def test_load_harness_guard_raises_on_unavailable_spec(self, monkeypatch):
        # Coverage vehicle for the _load_harness spec guard (100% requirement): a spec-less loader
        # surfaces as a named AssertionError, matching the harness-test load pattern.
        monkeypatch.setattr("importlib.util.spec_from_file_location", lambda *args, **kwargs: None)

        with pytest.raises(AssertionError, match="unavailable"):
            probe._load_harness()
