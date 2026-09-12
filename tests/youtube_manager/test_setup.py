"""T0 setup checks: check_setup readiness reporting (scenarios T0-1…T0-3)."""

from unittest.mock import patch
from urllib.error import URLError

import pytest

from youtube_manager import ReauthNeeded

GOOGLE_FIELDS = ("google_client_id", "google_client_secret", "google_refresh_token")


def _set_case(tools, case):
    """Reset google/session valves to the T0-2 case table."""
    for field in GOOGLE_FIELDS:
        setattr(tools.valves, field, "")
    tools.valves.ytdlp_cookies_file = ""
    tools.valves.ytdlp_username = ""
    tools.valves.ytdlp_password = ""
    case_table = {
        "no_google": ({}, True),
        "partial_google": ({"google_client_id": "abc.iam"}, True),
        "no_token": ({"google_client_id": "abc.iam", "google_client_secret": "shh"}, True),
        "no_session": (
            {"google_client_id": "abc.iam", "google_client_secret": "shh", "google_refresh_token": "rt"},
            False,
        ),
        "nothing": ({}, False),
    }
    google, session = case_table[case]
    for field, value in google.items():
        setattr(tools.valves, field, value)
    if session:
        tools.valves.ytdlp_cookies_file = "cookies.txt"


class TestCheckSetup:
    """check_setup readiness reporting."""

    # @unit
    # Scenario: T0-1 check_setup ready
    #   Given the valves have a full Google credential set and a valid session (token seam returns an access token)
    #   When the tool runs check_setup
    #   Then the result contains "READY"
    #   And it names no missing or invalid item
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

    # @unit
    # Scenario: T0-2 check_setup missing parts
    #   Given "session configured" = ytdlp_cookies_file OR ytdlp_username valve non-empty (valve check ONLY — no disk check at setup time; disk problems surface later as feed errors)
    #   And the valves match one of the cases:
    #     | case           | google fields     | session configured |
    #     | no_google      | none             | yes                |
    #     | partial_google | client_id only   | yes                |
    #     | no_token       | id+secret, no token | yes             |
    #     | no_session     | full set         | no                 |
    #     | nothing        | none             | no                 |
    #   When the tool runs check_setup
    #   Then the result contains "NOT READY"
    #   And it lists exactly the missing items for that case
    #   And each missing item carries a one-line setup instruction
    @pytest.mark.parametrize(
        "case",
        ["no_google", "partial_google", "no_token", "no_session", "nothing"],
        ids=["no_google", "partial_google", "no_token", "no_session", "nothing"],
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
            "no_session": set(),
            "nothing": set(GOOGLE_FIELDS),
        }[case]
        lines = result.splitlines()
        for field in GOOGLE_FIELDS:
            if field in missing_google:
                line = next(ln for ln in lines if field in ln)
                assert "MISSING" in line
                assert " - " in line  # one-line setup instruction
            else:
                assert field not in result, f"{field} must not be flagged in case {case}"
        session_lines = [ln for ln in lines if "yt-dlp session" in ln]
        if case in ("no_session", "nothing"):
            assert session_lines and "MISSING" in session_lines[0] and " - " in session_lines[0]
        else:
            assert session_lines and "MISSING" not in session_lines[0]

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
