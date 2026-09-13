"""T0 setup checks: check_setup readiness reporting (scenarios T0-1…T0-3)."""

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
        assert "READY" in result
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
        assert "NOT READY" in result
        missing_google = {
            "no_google": set(GOOGLE_FIELDS),
            "partial_google": {"google_client_secret", "google_refresh_token"},
            "no_token": {"google_refresh_token"},
        }[case]
        lines = result.splitlines()
        for field in GOOGLE_FIELDS:
            if field in missing_google:
                line = next(ln for ln in lines if field in ln)
                assert "MISSING" in line
                assert " - " in line  # one-line setup instruction
            else:
                assert field not in result, f"{field} must not be flagged in case {case}"
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
        assert expect in result
        assert "NOT READY" in result
        if expect == "INVALID":
            assert "stale" in result
            assert "start_auth" in result
