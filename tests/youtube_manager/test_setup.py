"""T0 setup checks: check_setup readiness reporting (scenarios T0-1…T0-3) + B3 per-source readiness."""

from unittest.mock import patch
from urllib.error import URLError

import pytest

from youtube_manager import ReauthNeeded

GOOGLE_FIELDS = ("google_client_id", "google_client_secret", "google_refresh_token")


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


class TestCheckSetup:
    """check_setup readiness reporting."""

    # @unit
    # Scenario: T0-1 check_setup ready
    #   Given the valves have a full Google credential set and the token seam returns an access token (no session involved)
    #   When the tool runs check_setup
    #   Then the result contains "READY"
    #   And it names no missing or invalid item
    #   And it names no session, cookies, or username requirement
    async def test_ready(self, tools):
        with patch(
            "youtube_manager._oauth_token",
            return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        assert lines[1] == "subscriptions: ok"
        assert lines[2] == "watch_later: ok (playlist not checked)"
        assert lines[-1] == "READY"
        assert "NOT READY" not in result
        assert "MISSING" not in result
        assert "INVALID" not in result
        lowered = result.lower()
        assert "session" not in lowered
        assert "cookies" not in lowered
        assert "username" not in lowered

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
    #   And each missing item carries a one-line setup instruction
    #   And the result names no session, cookies, or username requirement
    @pytest.mark.parametrize(
        "case",
        ["no_google", "partial_google", "no_token"],
        ids=["no_google", "partial_google", "no_token"],
    )
    async def test_missing_parts(self, tools, case):
        _set_case(tools, case)
        with patch(
            "youtube_manager._oauth_token",
            side_effect=AssertionError("live token check must not run with an incomplete set"),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        assert lines[1] == "subscriptions: MISSING - OAuth fields incomplete"
        assert lines[2] == "watch_later: MISSING - OAuth fields incomplete"
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


class TestCheckSetupPerSource:
    """B3 per-source OAuth readiness lines in check_setup (locked order, single shared token check)."""

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup is ready
    #   Given a Tools instance with complete OAuth fields and a valid refresh token
    #   When check_setup is called
    #   Then the first line is exactly "search: ok"
    #   And the second line is exactly "subscriptions: ok"
    #   And the third line is exactly "watch_later: ok (playlist not checked)"
    #   And the last line is exactly "READY"
    async def test_check_setup_per_source_ready(self, tools):
        with patch(
            "youtube_manager._oauth_token",
            return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
        ):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok",
            "watch_later: ok (playlist not checked)",
            "READY",
        ]

    # @workflow [AC-3]
    # Scenario: B3 per-source check_setup reports incomplete OAuth fields
    #   Given a Tools instance with at least one OAuth field missing
    #   When check_setup is called
    #   Then the second line is exactly "subscriptions: MISSING - OAuth fields incomplete"
    #   And the third line is exactly "watch_later: MISSING - OAuth fields incomplete"
    #   And the last line is exactly "NOT READY"
    @pytest.mark.parametrize(
        "case",
        ["no_google", "partial_google", "no_token"],
        ids=["no_google", "partial_google", "no_token"],
    )
    async def test_check_setup_oauth_missing_per_source(self, tools, case):
        _set_case(tools, case)
        with patch(
            "youtube_manager._oauth_token",
            side_effect=AssertionError("live token check must not run with an incomplete set"),
        ):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: MISSING - OAuth fields incomplete",
            "watch_later: MISSING - OAuth fields incomplete",
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
