"""T0-1 S1-S4 unit mirrors: the dev-only live harness (env template, env hygiene, production topology, __user__ injection)."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values

import youtube_manager as ym
from youtube_manager import CREDENTIAL_TITLE

from .conftest import api_fake, guard_urlopen

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _REPO_ROOT / "dev" / "youtube_live.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("dev_youtube_live_harness", _HARNESS)
    if spec is None or spec.loader is None:
        raise AssertionError("harness spec/loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hl = _load_harness()

TEMPLATE_SLOTS = [
    "YTM_GOOGLE_CLIENT_ID",
    "YTM_GOOGLE_CLIENT_SECRET",
    "YTM_USER_ID",
    "YTM_DATA_DIR",
]


class TestEnvTemplate:
    # @unit
    # Scenario: T0-1-S1 (unit): template carries exactly the initial-condition slots
    #   Given the committed env.template
    #   When it is parsed as dotenv
    #   Then it exposes exactly these env slots: YTM_GOOGLE_CLIENT_ID, YTM_GOOGLE_CLIENT_SECRET,
    #     YTM_USER_ID (all required) and YTM_DATA_DIR (optional, default .data-live)
    #   And no refresh-token slot exists (the credential is acquired by the harness's browser auth,
    #     never pasted from a token file)
    #   And no value in the template is a secret (placeholders are empty or the DATA_DIR default)
    def test_template_carries_exactly_the_initial_condition_slots(self):
        parsed = dotenv_values(str(_REPO_ROOT / "env.template"))

        assert sorted(parsed) == sorted(TEMPLATE_SLOTS)
        assert not any("REFRESH_TOKEN" in key for key in parsed)
        assert all(value in {"", ".data-live"} for value in parsed.values())


class TestEnvHygiene:
    # @unit
    # Scenario: T0-1-S2 (unit): env hygiene
    #   Given the repository .gitignore
    #   When checked
    #   Then .env is ignored, env.template is not ignored (committable), and .data-live/ is ignored
    @pytest.mark.parametrize(
        ("path", "expected_ignored"),
        [(".env", True), ("env.template", False), (".data-live/live-run.log", True)],
        ids=["env_ignored", "template_committable", "data_dir_ignored"],
    )
    def test_gitignore_hygiene(self, path, expected_ignored):
        result = subprocess.run(["git", "check-ignore", "-q", "--", path], cwd=_REPO_ROOT)
        assert (result.returncode == 0) is expected_ignored


class TestProductionTopology:
    # @unit
    # Scenario: T0-1-S3 (unit): initial-condition credential topology (dummy valve, no file token yet)
    #   Given a filled .env in a tmp dir (client id/secret, user id u1, tmp DATA_DIR — NO tokens)
    #   When the harness builds the tool
    #   Then valves are set from env (google_refresh_token == DUMMY_REFRESH_TOKEN — non-empty,
    #     client id/secret, digest settings)
    #   And no token file is written (<DATA_DIR>/u1/google-refresh-token.md does NOT exist yet)
    #   And the topology holds: valve token = the documented non-empty dummy, per-user file token = absent
    def test_build_tools_dummy_valve_and_no_file_token(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "YTM_GOOGLE_CLIENT_ID=client-id\n"
            "YTM_GOOGLE_CLIENT_SECRET=client-secret\n"
            "YTM_USER_ID=u1\n"
            f"YTM_DATA_DIR={tmp_path / 'data-live'}\n"
        )
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "pre"))

        env = hl.load_env(str(env_file))
        tools = hl.build_tools(env, tmp_path / "data-live")

        assert tools.valves.google_refresh_token == hl.DUMMY_REFRESH_TOKEN
        assert tools.valves.google_client_id == "client-id"
        assert tools.valves.google_client_secret == "client-secret"
        assert tools.valves.digest_playlist_title == "Open WebUI Digest"
        assert tools.valves.digest_max_items == 50
        assert tools.valves.digest_max_age_days == 30
        assert tools.valves.watch_later_playlist_title == "Watch Later"
        token_path = tmp_path / "data-live" / "u1" / f"{CREDENTIAL_TITLE}.md"
        assert not token_path.exists()
        assert os.environ["DATA_DIR"] == str(tmp_path / "data-live")
        assert ym._file_refresh_token("u1") is None

    # @unit
    # Scenario T1-2-C-S8 (unit): harness env drives the watch_later_playlist_title valve
    #   Given a filled .env with YTM_WATCH_LATER_PLAYLIST_TITLE="My Later"
    #   When the harness builds the tool
    #   Then the watch_later_playlist_title valve equals "My Later"
    #   # provenance: user instruction "the live harness must be able to set the new valve from the env"
    def test_build_tools_watch_later_valve_from_env(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "YTM_GOOGLE_CLIENT_ID=client-id\n"
            "YTM_GOOGLE_CLIENT_SECRET=client-secret\n"
            "YTM_USER_ID=u1\n"
            "YTM_WATCH_LATER_PLAYLIST_TITLE=My Later\n"
        )
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "pre"))

        env = hl.load_env(str(env_file))
        tools = hl.build_tools(env, tmp_path / "data-live")

        assert tools.valves.watch_later_playlist_title == "My Later"


class TestOwuiCall:
    # @unit
    # Scenario: T0-1-S4 (unit): OWUI-faithful __user__ injection
    #   Given a tool method that declares __user__ and one that does not
    #   When the harness dispatches both via owui_call
    #   Then __user__={"id": <env user id>} is injected only for the declared one
    #   # (pre-fix list_playlists is therefore called without a user, exactly as OWUI does — faithful repro)
    async def test_injection_only_where_declared(self):
        seen = {}

        async def declared(__user__: dict | None = None) -> str:
            seen["declared"] = __user__
            return "declared"

        async def undeclared() -> str:
            return "undeclared"

        assert await hl.owui_call(declared, "u1") == "declared"
        assert await hl.owui_call(undeclared, "u1") == "undeclared"
        assert seen["declared"] == {"id": "u1"}


class TestLoadEnv:
    """load_env units: missing file, missing required keys, defaults + stripping."""

    def test_missing_file_raises_pointing_at_template(self, tmp_path):
        with pytest.raises(FileNotFoundError, match=r"env\.template"):
            hl.load_env(str(tmp_path / "absent"))

    def test_missing_required_key_is_named(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("YTM_GOOGLE_CLIENT_ID=client-id\nYTM_USER_ID=\n")

        with pytest.raises(ValueError, match="YTM_USER_ID"):
            hl.load_env(str(env_file))

    def test_filled_env_applies_defaults_and_strips(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "YTM_GOOGLE_CLIENT_ID=client-id\n"
            "YTM_GOOGLE_CLIENT_SECRET=client-secret\n"
            "YTM_USER_ID=u1\n"
            "YTM_DATA_DIR= custom-dir \n"
        )

        env = hl.load_env(str(env_file))

        assert env["YTM_DATA_DIR"] == "custom-dir"
        assert env["YTM_VERBOSE"] == "false"
        assert env["YTM_DIGEST_MAX_ITEMS"] == "50"


class TestProbeIdentity:
    """probe_identity units: canned account, empty reply, errored API (reason carried)."""

    def test_success_returns_channel_and_title(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={},
            channels={"items": [{"id": "ch-self", "snippet": {"title": "Self Channel"}}]},
        )

        identity, reason = hl.probe_identity(tools, "u1")

        assert identity == {"channel_id": "ch-self", "title": "Self Channel"}
        assert reason is None

    def test_empty_items_returns_none_and_no_reason(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, channels={"items": []})

        identity, reason = hl.probe_identity(tools, "u1")

        assert identity is None
        assert reason is None

    def test_api_error_returns_cleaned_reason(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, raise_for={"channels.list": RuntimeError("boom")})

        identity, reason = hl.probe_identity(tools, "u1")

        assert identity is None
        assert reason == "unexpected error"


class TestItemCount:
    """_item_count units: both response shapes (bytes/dict) plus the defensive edge branches."""

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"items": [1, 2, 3]}, 3),  # dict with items
            (b'{"items": [1, 2]}', 2),  # bytes JSON with items
            (b"not valid json", 0),  # bytes that fail to decode -> 0
            ("a plain string", 0),  # neither bytes nor dict -> 0
            (None, 0),  # None -> 0
            ({}, 0),  # dict without items -> 0
            (b"{}", 0),  # bytes JSON without items -> 0
        ],
    )
    def test_item_count(self, payload, expected):
        assert hl._item_count(payload) == expected


class TestRunAuth:
    # @unit
    # Scenario: T0-1-S7 (unit, mocked seams, no network): interactive auth acquires the credential
    #   Given a harness with NO token file for user id u1 and an injected input_fn (no real input(),
    #     no network: _oauth_token / urllib.request.urlopen faked, guard_urlopen active)
    #   When run_auth performs the browser flow and input_fn returns
    #     [parametrize] the bare code OR the full redirect URL (http://127.0.0.1:8085/oauth2callback?code=…)
    #   Then start_auth is called WITHOUT __user__ (it declares none) and finish_auth is called
    #     with the pasted value
    #   And the token file <DATA_DIR>/u1/google-refresh-token.md exists afterwards (0600)
    #   And the pasted code/URL appears in NEITHER stdout NOR the run log (secret invariant)
    @pytest.mark.parametrize("paste", ["code-abc", "http://127.0.0.1:8085/oauth2callback?code=code-abc"])
    async def test_interactive_auth_acquires_credential(self, tools, monkeypatch, capsys, paste):
        captured: dict = {}

        def fake_oauth(valves, code=None, user_id=None):
            captured["code"] = code
            captured["user_id"] = user_id
            return {"refresh_token": "fresh-token", "access_token": "tok"}

        monkeypatch.setattr("youtube_manager._oauth_token", fake_oauth)
        guard_urlopen(monkeypatch)
        data_dir = Path(os.environ["DATA_DIR"])

        def input_fn(prompt: str) -> str:
            return paste

        await hl.run_auth(tools, "u1", data_dir, input_fn=input_fn)

        token_path = data_dir / "u1" / f"{CREDENTIAL_TITLE}.md"
        assert token_path.exists()
        assert token_path.read_text() == "fresh-token"
        assert oct(token_path.stat().st_mode & 0o777) == "0o600"
        assert captured["code"] == "code-abc"
        assert captured["user_id"] == "u1"
        out = capsys.readouterr().out
        assert paste not in out
        assert "code-abc" not in out

    # @unit
    # Scenario: T0-1-S8 (unit, mocked seams, no network): token reuse skips the browser flow
    #   Given the token file <DATA_DIR>/u1/google-refresh-token.md already present
    #   When run_auth runs
    #   Then start_auth is NOT called and input_fn is NOT called (no browser, no pause)
    #   And the existing token file is untouched
    async def test_token_reuse_skips_browser_flow(self, tools, monkeypatch, capsys):
        guard_urlopen(monkeypatch)
        data_dir = Path(os.environ["DATA_DIR"])
        token_path = data_dir / "u1" / f"{CREDENTIAL_TITLE}.md"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("existing-token")
        token_path.chmod(0o600)

        def input_fn(prompt: str) -> str:
            raise AssertionError("input_fn must not be called when the token file exists")

        await hl.run_auth(tools, "u1", data_dir, input_fn=input_fn)

        assert token_path.read_text() == "existing-token"
        assert capsys.readouterr().out == ""
