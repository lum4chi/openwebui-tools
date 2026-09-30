"""T0 setup checks: check_setup readiness reporting (scenarios T0-1…T0-3) + B3 per-source readiness."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

import youtube_manager
from youtube_manager import ReauthNeeded, Tools

GOOGLE_FIELDS = ("google_client_id", "google_client_secret")


def _no_credential() -> None:
    """Drop the fixture-seeded credential file (the no-stored-credential condition)."""
    (Path(os.environ["DATA_DIR"]) / "default" / "google-refresh-token.md").unlink(missing_ok=True)


def _set_case(tools, case):
    """Reset the google valves to the T0-2 case table (no session dimension after the purge)."""
    for field in GOOGLE_FIELDS:
        setattr(tools.valves, field, "")
    case_table = {
        "no_google": {},
        "partial_google": {"google_client_id": "abc.iam"},
        "no_token": {"google_client_id": "abc.iam", "google_client_secret": "shh"},
    }
    for field, value in case_table[case].items():
        setattr(tools.valves, field, value)


def _probe_return(value: str):
    async def probe(self, user_id=None):
        return value

    return probe


class TestCheckSetup:
    """check_setup readiness reporting."""

    # @unit
    # Scenario: T4-1-S6 (unit) — trace: "Remove them from the valve" (readiness must not gate on the valve)
    #   Given client id and secret are set
    #   When check_setup runs with a credential file present and a healthy probe
    #   Then the overall status is READY
    #   And when check_setup runs with no credential file
    #   Then the overall status is NOT READY
    #   And the subscriptions and watch_later lines are "MISSING - no stored credential; run start_auth then finish_auth"
    #   And when client id or secret is missing
    #   Then the overall status is NOT READY with the existing "OAuth fields incomplete" lines
    # Scenario: T0-1 check_setup ready
    #   Given the valves have a full Google credential set and the token seam returns an access token (no session involved)
    #   When the tool runs check_setup
    #   Then the result contains "READY"
    #   And it names no missing or invalid item
    #   And it names no session, cookies, or username requirement
    # Scenario: T9-1 S2 check_setup is READY only when the WL probe succeeds
    #   Given the OAuth fields are complete and the token status is valid
    #   And Tools._watch_later_probe returns "ok (surrogate playlist checked)"
    #   When check_setup runs
    #   Then the result lines are exactly "search: ok", "subscriptions: ok (subscription feed checked)", "watch_later: ok (surrogate playlist checked)", "READY"
    async def test_ready(self, tools):
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("ok (surrogate playlist checked)")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        assert lines[1] == "subscriptions: ok (subscription feed checked)"
        assert lines[2] == "watch_later: ok (surrogate playlist checked)"
        assert lines[-1] == "READY"
        assert "NOT READY" not in result
        assert "MISSING" not in result
        assert "INVALID" not in result
        lowered = result.lower()
        assert "session" not in lowered
        assert "cookies" not in lowered
        assert "username" not in lowered

    # @unit
    # Scenario: T4-1-S6 (unit, READY branch) — rescope: ready from credential file with client fields only (the empty-valve concept is gone)
    #   Given DATA_DIR/default contains the credential file with "file-rt"
    #     And a Tools with client_id and client_secret set (the credential file is the only credential source)
    #     And a successful token refresh
    #   When check_setup is called
    #   Then the response reports READY
    async def test_ready_from_credential_file_with_client_fields_only(self, tools):
        data_dir = Path(os.environ["DATA_DIR"])
        (data_dir / "default").mkdir(parents=True, exist_ok=True)
        (data_dir / "default" / "google-refresh-token.md").write_text("file-rt")
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("ok (surrogate playlist checked)")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        assert lines[1] == "subscriptions: ok (subscription feed checked)"
        assert lines[2] == "watch_later: ok (surrogate playlist checked)"
        assert lines[-1] == "READY"
        assert "NOT READY" not in result
        assert "MISSING" not in result
        assert "INVALID" not in result

    # @unit
    # Scenario: T9-1 S3 check_setup is NOT READY when the WL probe fails
    #   Given the OAuth fields are complete and the token status is valid
    #   And Tools._watch_later_probe returns "CHECK FAILED - reauth"
    #   When check_setup runs
    #   Then the watch_later line is exactly "watch_later: CHECK FAILED - reauth"
    #   And the final line is exactly "NOT READY"
    async def test_ready_probe_failed_not_ready(self, tools):
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("CHECK FAILED - reauth")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (subscription feed checked)",
            "watch_later: CHECK FAILED - reauth",
            "NOT READY",
        ]

    # @unit
    # Scenario: T0-2 check_setup missing parts
    #   Given the valves match one of the Google-set cases (no session is considered after the purge):
    #     | case           | google fields       |
    #     | no_google      | none                |
    #     | partial_google | client_id only      |
    #     | no_token       | id+secret, no token |
    #   When the tool runs check_setup
    #   Then the result contains "NOT READY"
    #   And it lists exactly the missing Google items for that case
    #   (T4-1-S6: the no_token case — client fields set, no credential file — carries the
    #    no-credential line, NOT the incomplete-fields line)
    #   And each missing item carries a one-line setup instruction
    #   And the result names no session, cookies, or username requirement
    @pytest.mark.parametrize(
        "case",
        ["no_google", "partial_google", "no_token"],
        ids=["no_google", "partial_google", "no_token"],
    )
    async def test_missing_parts(self, tools, case):
        _set_case(tools, case)
        if case == "no_token":
            _no_credential()
        with patch(
            "youtube_manager._oauth_token",
            side_effect=AssertionError("live token check must not run with an incomplete set"),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        missing = (
            "MISSING - no stored credential; run start_auth then finish_auth"
            if case == "no_token"
            else "MISSING - OAuth fields incomplete"
        )
        assert lines[1] == f"subscriptions: {missing}"
        assert lines[2] == f"watch_later: {missing}"
        assert lines[-1] == "NOT READY"
        lowered = result.lower()
        assert "session" not in lowered
        assert "cookies" not in lowered
        assert "username" not in lowered

    # @unit
    # Scenario: T0-3 check_setup invalid token
    #   Given the valves have a full Google credential set
    #   And the token seam raises ReauthNeeded (invalid_grant)
    #   When the tool runs check_setup
    #   Then the result marks the Google credential set as INVALID (stale token)
    #   And it contains the start_auth re-onboarding instruction
    #   And no exception propagates
    @pytest.mark.parametrize(
        ("exc", "expect"),
        [
            (ReauthNeeded("invalid_grant"), "INVALID"),
            (URLError("connection refused"), "CHECK FAILED"),
        ],
        ids=["invalid_grant", "network_error"],
    )
    async def test_invalid_token(self, tools, exc, expect):
        with patch("youtube_manager._oauth_token", side_effect=exc):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        if expect == "INVALID":
            state = "INVALID - stored refresh token is stale; run start_auth then finish_auth"
        else:
            state = "CHECK FAILED - token endpoint unreachable"
        assert lines[1] == f"subscriptions: {state}"
        assert lines[2] == f"watch_later: {state}"
        assert lines[-1] == "NOT READY"

    # @unit
    # Scenario: T4-1-S6 (unit, no-credential branch) — rescope: file absent → the no-credential readiness line (NOT INVALID)
    #   Given a fresh DATA_DIR (no file)
    #     And a Tools with client_id/client_secret set
    #   When check_setup is called
    #   Then the response reports NOT READY
    #     And the subscriptions and watch_later lines are exactly "MISSING - no stored credential; run start_auth then finish_auth"
    #     And the token check never runs (no INVALID line)
    async def test_absent_file_reports_no_credential_line(self, tools):
        _no_credential()
        with patch(
            "youtube_manager._oauth_token",
            side_effect=AssertionError("the token check must not run with no credential file"),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        state = "MISSING - no stored credential; run start_auth then finish_auth"
        assert lines[1] == f"subscriptions: {state}"
        assert lines[2] == f"watch_later: {state}"
        assert lines[-1] == "NOT READY"


class TestValvesModel:
    """The Valves model: no token field (S1); legacy config keys construct fine and are dropped (S5)."""

    # @unit
    # Scenario: T4-1-S1 (unit) — trace: "Remove them from the valve"
    #   Given a Tools instance constructed from the default Valves model
    #   When the Valves model fields are inspected
    #   Then the google_refresh_token field is not present
    def test_valves_model_has_no_refresh_token_field(self):
        assert "google_refresh_token" not in Tools().Valves.model_fields

    # @unit
    # Scenario: T4-1-S5 (unit) — trace: "assure that the tool does not need the valve itself" + work-package scope boundary (legacy OWUI configs)
    #   Given a legacy config dict still containing google_refresh_token = "legacy-rt" (old saved OWUI config shape)
    #   When the Valves model is constructed from that dict
    #   Then construction succeeds and the dumped model fields do not contain google_refresh_token
    #   And with no credential file, resolution takes the no-credential path and legacy-rt is never sent to the token endpoint
    def test_legacy_config_token_key_dropped_and_never_used(self, tools, monkeypatch):
        _no_credential()
        valves = Tools().Valves(
            google_client_id="legacy-id",
            google_client_secret="legacy-sec",
            google_refresh_token="legacy-rt",
        )
        assert "google_refresh_token" not in valves.model_dump()
        urlopen = MagicMock()
        monkeypatch.setattr("youtube_manager.urllib.request.urlopen", urlopen)
        with pytest.raises(ReauthNeeded) as exc_info:
            youtube_manager._oauth_token(valves, code=None)
        assert "start_auth" in str(exc_info.value)
        assert "finish_auth" in str(exc_info.value)
        urlopen.assert_not_called()


class TestCheckSetupPerSource:
    """B3 per-source OAuth readiness lines in check_setup (locked order, single shared token check)."""

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup is ready
    #   Given a Tools instance with complete OAuth fields and a valid refresh token
    #   When check_setup is called
    #   Then the first line is exactly "search: ok"
    #   And the second line is exactly "subscriptions: ok (subscription feed checked)"
    #   And the third line is exactly "watch_later: ok (surrogate playlist checked)"
    #   And the last line is exactly "READY"
    # Scenario: T9-1 S2 check_setup is READY only when the WL probe succeeds
    #   Given the OAuth fields are complete and the token status is valid
    #   And Tools._watch_later_probe returns "ok (surrogate playlist checked)"
    #   When check_setup runs
    #   Then the result lines are exactly "search: ok", "subscriptions: ok (subscription feed checked)", "watch_later: ok (surrogate playlist checked)", "READY"
    async def test_check_setup_per_source_ready(self, tools):
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("ok (surrogate playlist checked)")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (subscription feed checked)",
            "watch_later: ok (surrogate playlist checked)",
            "READY",
        ]

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup reports incomplete OAuth fields
    #   Given a Tools instance with at least one OAuth field missing
    #   When check_setup is called
    #   Then the second line is exactly "subscriptions: MISSING - OAuth fields incomplete"
    #   And the third line is exactly "watch_later: MISSING - OAuth fields incomplete"
    #   And the last line is exactly "NOT READY"
    #   (T4-1-S6: the no_token case — client fields set, no credential file — carries the
    #    no-credential line, NOT the incomplete-fields line)
    @pytest.mark.parametrize(
        "case",
        ["no_google", "partial_google", "no_token"],
        ids=["no_google", "partial_google", "no_token"],
    )
    async def test_check_setup_oauth_missing_per_source(self, tools, case):
        _set_case(tools, case)
        if case == "no_token":
            _no_credential()
        with patch(
            "youtube_manager._oauth_token",
            side_effect=AssertionError("live token check must not run with an incomplete set"),
        ):
            result = await tools.check_setup()
        missing = (
            "no stored credential; run start_auth then finish_auth" if case == "no_token" else "OAuth fields incomplete"
        )
        assert result.splitlines() == [
            "search: ok",
            f"subscriptions: MISSING - {missing}",
            f"watch_later: MISSING - {missing}",
            "NOT READY",
        ]

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup reports stale token
    #   Given a Tools instance with complete OAuth fields whose refresh token is rejected
    #   When check_setup is called
    #   Then the second line is exactly "subscriptions: INVALID - stored refresh token is stale; run start_auth then finish_auth"
    #   And the third line is exactly "watch_later: INVALID - stored refresh token is stale; run start_auth then finish_auth"
    #   And the last line is exactly "NOT READY"
    async def test_check_setup_invalid_token_per_source(self, tools):
        with patch("youtube_manager._oauth_token", side_effect=ReauthNeeded("invalid_grant")):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: INVALID - stored refresh token is stale; run start_auth then finish_auth",
            "watch_later: INVALID - stored refresh token is stale; run start_auth then finish_auth",
            "NOT READY",
        ]

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup reports unreachable token endpoint
    #   Given a Tools instance with complete OAuth fields whose token endpoint is unreachable
    #   When check_setup is called
    #   Then the second line is exactly "subscriptions: CHECK FAILED - token endpoint unreachable"
    #   And the third line is exactly "watch_later: CHECK FAILED - token endpoint unreachable"
    #   And the last line is exactly "NOT READY"
    async def test_check_setup_check_failed_per_source(self, tools):
        with patch("youtube_manager._oauth_token", side_effect=URLError("connection refused")):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: CHECK FAILED - token endpoint unreachable",
            "watch_later: CHECK FAILED - token endpoint unreachable",
            "NOT READY",
        ]
