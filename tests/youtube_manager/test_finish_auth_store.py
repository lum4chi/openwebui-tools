"""T7R-1 B: finish_auth stores the exchanged refresh token in a DATA_DIR file (0600); file-over-valve read precedence."""

import os
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

import youtube_manager
from youtube_manager import TOKEN_URL, ReauthNeeded

TOKEN = {"access_token": "tok", "refresh_token": "new-refresh-token", "expires_in": 3600}
CREDENTIAL_FILE = "google-refresh-token.md"


def _credential_path() -> Path:
    return Path(os.environ["DATA_DIR"]) / CREDENTIAL_FILE


class _BoomStore:
    """State store stub whose write raises OSError (S2 credential-file write failure)."""

    def write(self, title: str, md: str, *, secret: bool = False) -> None:
        raise OSError("disk full")


class TestFinishAuthFileStore:
    """finish_auth persists the exchanged refresh token to DATA_DIR/google-refresh-token.md (0600)."""

    # @unit
    # Scenario: S1 finish_auth success
    #   Given a Tools whose token exchange returns refresh token "new-refresh-token"
    #     And a fresh DATA_DIR with no credential file
    #   When finish_auth is called with a valid authorization code
    #   Then DATA_DIR contains google-refresh-token.md containing exactly "new-refresh-token"
    #     And the credential file mode is 0600
    #     And the response is exactly "OK - credential stored; check_setup should now show ok"
    #     And the response does not contain "new-refresh-token"
    async def test_success_writes_0600_credential_file(self, tools):
        with patch("youtube_manager._oauth_token", return_value=TOKEN):
            result = await tools.finish_auth("code123")
        cred = _credential_path()
        assert cred.read_text() == "new-refresh-token"
        assert (cred.stat().st_mode & 0o777) == 0o600
        assert result == "OK - credential stored; check_setup should now show ok"
        assert "new-refresh-token" not in result

    # @unit
    # Scenario: S2 file-write failure after exchange
    #   Given exchange returns "new-refresh-token"
    #     And a fresh DATA_DIR
    #     And the credential file write fails with an OSError
    #   When finish_auth runs
    #   Then the response is exactly the credential-file write failure string with the clean reason
    #     And the response does not contain "new-refresh-token"
    #     And the valve google_refresh_token is not modified
    async def test_write_failure_after_exchange_reports_retry_without_raw_token(self, tools):
        with (
            patch("youtube_manager._oauth_token", return_value=TOKEN),
            patch("youtube_manager._state_store", lambda request: _BoomStore()),
        ):
            result = await tools.finish_auth("code123")
        expected = (
            "Error: credential file write failed: unexpected error. "
            "The authorization code was exchanged, but the new refresh token was not stored. "
            "Run start_auth and finish_auth again."
        )
        assert result == expected
        assert "new-refresh-token" not in result
        assert tools.valves.google_refresh_token == "refresh-token"


class TestEffectiveRefreshToken:
    """File-over-valve precedence: the DATA_DIR credential file wins; the valve is the legacy fallback."""

    # @unit
    # Scenario: S3 file precedence
    #   Given DATA_DIR contains the credential file with "file-rt"
    #     And the valve google_refresh_token "valve-rt"
    #   When the effective refresh token is resolved
    #   Then it is exactly "file-rt"
    def test_file_precedence_over_valve(self, tools):
        data_dir = Path(os.environ["DATA_DIR"])
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / CREDENTIAL_FILE).write_text("file-rt")
        tools.valves.google_refresh_token = "valve-rt"
        assert youtube_manager._effective_refresh_token(tools.valves) == "file-rt"

    # @unit
    # Scenario: S4 valve fallback
    #   Given a fresh DATA_DIR (no file) or a whitespace-only credential file
    #     And the valve google_refresh_token "valve-rt"
    #   When the effective refresh token is resolved
    #   Then it is exactly "valve-rt"
    @pytest.mark.parametrize(
        "content",
        [pytest.param(None, id="no_file"), pytest.param("  \n", id="whitespace_only_file")],
    )
    def test_valve_fallback_when_file_absent(self, tools, content):
        if content is not None:
            data_dir = Path(os.environ["DATA_DIR"])
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / CREDENTIAL_FILE).write_text(content)
        tools.valves.google_refresh_token = "valve-rt"
        assert youtube_manager._effective_refresh_token(tools.valves) == "valve-rt"


class TestFinishAuthErrors:
    """finish_auth error paths: no code and reauth surface cleanly and write no credential file."""

    # @unit
    # Scenario: S7 no code
    #   Given a Tools
    #   When finish_auth is called with a string containing no code
    #   Then the response is exactly "Error: no authorization code found - paste the full redirect URL with ?code= from the browser."
    #     And no credential file is written
    async def test_no_code_exact_and_no_file(self, tools):
        with patch("youtube_manager._oauth_token"):
            result = await tools.finish_auth("http://127.0.0.1:8085/oauth2callback?error=access_denied")
        expected = "Error: no authorization code found - paste the full redirect URL with ?code= from the browser."
        assert result == expected
        assert not _credential_path().exists()

    # @unit
    # Scenario: S8 reauth
    #   Given exchange fails with ReauthNeeded
    #   When finish_auth runs with a valid code
    #   Then the response starts with REAUTH_NEEDED
    #     And it contains the start_auth / finish_auth fix instruction
    #     And no credential file is written
    async def test_reauth_pass_through_writes_no_file(self, tools):
        with patch("youtube_manager._oauth_token", side_effect=ReauthNeeded("invalid_grant")):
            result = await tools.finish_auth("some-auth-code")
        assert result.startswith("REAUTH_NEEDED")
        assert "start_auth" in result
        assert "finish_auth" in result
        assert not _credential_path().exists()


class TestFinishAuthExchangeFailure:
    """S-EX: a Google 503 from the token exchange maps to the clean service-unavailable error."""

    # @unit
    # Scenario: S-EX exchange failure mapping
    #   Given exchange fails with a urllib HTTPError 503
    #   When finish_auth runs with a valid code
    #   Then the response is exactly "Error: service unavailable - retry later"
    #     And no credential file is written
    async def test_exchange_http_503_maps_to_service_unavailable(self, tools):
        boom = urllib.error.HTTPError(TOKEN_URL, 503, "Service Unavailable", {}, None)
        with patch("youtube_manager._oauth_token", side_effect=boom):
            result = await tools.finish_auth("some-auth-code")
        assert result == "Error: service unavailable - retry later"
        assert not _credential_path().exists()


class TestFinishAuthDocstring:
    """Agent-instruction step 3 describes the local credential-file storage."""

    # @unit
    # Scenario: S10 docstring
    #   Given the tool file
    #   When agent-instructions step 3 is read
    #   Then it does not contain "via the Open WebUI valve update"
    #     And it contains "store the refresh token to a local credential file"
    def test_step3_describes_local_credential_file(self):
        doc = youtube_manager.__doc__ or ""
        assert "via the Open WebUI valve update" not in doc
        assert "store the refresh token to a local credential file" in doc
