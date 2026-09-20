"""T7-1 C1: finish_auth self-stores the exchanged refresh token via the Open WebUI valve update."""

import email.message
import urllib.error
from unittest.mock import patch

import pytest

import youtube_manager

from .conftest import FakeRequest

TOKEN = {"access_token": "tok", "refresh_token": "new-refresh", "expires_in": 3600}
MISSING_CONTEXT = "Error: valve update unavailable: missing internal request context"


class TestFinishAuthReservedContext:
    """finish_auth requires the reserved __id__/__request__ context before any token exchange."""

    # @unit [AC-C1]
    # Scenario: T7-1 missing internal request context fails before token exchange
    #   Given a valid authorization code
    #     And either __id__ is missing or __request__ is missing or the authorization header is missing
    #   When finish_auth is called
    #   Then the result is exactly "Error: valve update unavailable: missing internal request context"
    #     And _oauth_token is not called
    @pytest.mark.parametrize(
        ("id_", "fake_request"),
        [
            (None, FakeRequest(headers={"authorization": "Bearer test"})),
            ("tool-id", None),
            ("tool-id", FakeRequest(headers={})),
        ],
        ids=["missing_id", "missing_request", "missing_authorization"],
    )
    async def test_missing_context_guard(self, tools, id_, fake_request):
        with patch("youtube_manager._oauth_token") as oauth_token:
            result = await tools.finish_auth("code123", __id__=id_, __request__=fake_request)
        assert result == MISSING_CONTEXT
        assert oauth_token.call_count == 0


class TestFinishAuthValveUpdate:
    """The valve-update POST carries the new refresh token; failures report a clean retry error."""

    # @unit [AC-C1]
    # Scenario: T7-1 successful finish_auth stores the refresh token and returns native OK
    #   Given a Tools instance whose _oauth_token exchange returns a refresh token
    #     And reserved context with __id__="tool-id" and an authorization header is present
    #     And _notes_http succeeds
    #   When finish_auth is called with a valid authorization code
    #   Then _notes_http receives POST to the valve-update endpoint with the authorization header
    #     And the JSON body {"google_refresh_token": "new-refresh"}
    #   And the result is exactly "OK - credential stored; check_setup should now show ok"
    #     And google_refresh_token is set to the exchanged refresh token
    #     And the result does not contain the raw refresh token
    async def test_valve_update_payload_on_success(self, tools):
        request = FakeRequest(headers={"authorization": "Bearer test"})
        with (
            patch("youtube_manager._oauth_token", return_value=TOKEN),
            patch("youtube_manager._notes_http", return_value={}) as notes_http,
        ):
            result = await tools.finish_auth("code123", __id__="tool-id", __request__=request)
        notes_http.assert_called_once_with(
            "POST",
            "http://localhost:3000/api/v1/tools/id/tool-id/valves/update",
            "Bearer test",
            {"google_refresh_token": "new-refresh"},
        )
        assert result == "OK - credential stored; check_setup should now show ok"
        assert tools.valves.google_refresh_token == "new-refresh"
        assert "new-refresh" not in result

    # @unit [AC-C1-SECRET]
    # Scenario: T7-1 valve update failure after exchange reports retry without raw token
    #   Given _oauth_token returns a refresh token
    #     And _notes_http raises a 503 HTTP error or a generic runtime error
    #   When finish_auth is called
    #   Then the result is exactly the valve-update failure string for that clean reason
    #     And the result does not contain the raw refresh token
    #     And google_refresh_token is not set to the exchanged refresh token
    @pytest.mark.parametrize(
        ("boom", "clean_reason"),
        [
            (
                urllib.error.HTTPError(
                    "http://localhost:3000/valves", 503, "Service Unavailable", email.message.Message(), None
                ),
                "service unavailable - retry later",
            ),
            (RuntimeError("update failed"), "unexpected error"),
        ],
        ids=["http_503", "runtime_error"],
    )
    async def test_valve_update_failure_after_exchange(self, tools, boom, clean_reason):
        request = FakeRequest(headers={"authorization": "Bearer test"})
        with (
            patch("youtube_manager._oauth_token", return_value=TOKEN),
            patch("youtube_manager._notes_http", side_effect=boom),
        ):
            result = await tools.finish_auth("code123", __id__="tool-id", __request__=request)
        assert result == (
            f"Error: valve update failed: {clean_reason}. "
            "The authorization code was exchanged, but the new refresh token was not stored. "
            "Run start_auth and finish_auth again."
        )
        assert "new-refresh" not in result
        assert tools.valves.google_refresh_token == "refresh-token"


class TestFinishAuthDocstring:
    """Agent-instruction step 3 reflects the stored-credential flow (no manual token storage)."""

    # @unit [AC-C1]
    # Scenario: T7-1 agent-instruction step 3 reflects the stored-credential flow
    #   Given the top-level tool docstring
    #   When the finish_auth agent-instruction step is read
    #   Then it no longer says to print the refresh token to store
    #   And it says the refresh token is stored via the Open WebUI valve update
    def test_finish_auth_docstring_instruction_updated(self):
        doc = youtube_manager.__doc__ or ""
        assert "print the refresh token to store" not in doc
        assert "store the refresh token via the Open WebUI valve update" in doc
