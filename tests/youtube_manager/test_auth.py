"""T0 auth flow: consent URL, finish_auth exchange, reauth surfacing (scenarios T0-4…T0-6)."""

import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from googleapiclient.errors import HttpError
from yt_dlp.utils import DownloadError, ExtractorError

from youtube_manager import (
    LOOPBACK_REDIRECT,
    SCOPE,
    QuotaError,
    ReauthNeeded,
    Tools,
    TranscriptUnavailable,
    _error_return,
    build_consent_url,
    parse_code_from_url,
)


class TestAuth:
    """Consent URL, code exchange, reauth surfacing."""

    # @unit
    # Scenario: T0-4 consent url
    #   Given a client_id "abc.iam"
    #   When build_consent_url is called
    #   Then the URL points at the Google OAuth endpoint
    #   And it requests exactly the scope "https://www.googleapis.com/auth/youtube"
    #   And it uses the loopback redirect URI
    #   And it requests an authorization code
    async def test_consent_url(self):
        url = build_consent_url("abc.iam", LOOPBACK_REDIRECT)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert "accounts.google.com" in parsed.netloc
        assert "oauth2/v2/auth" in parsed.path
        assert query["scope"] == [SCOPE]
        assert query["redirect_uri"] == [LOOPBACK_REDIRECT]
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["abc.iam"]

    # T0-4 (coverage): start_auth returns the consent URL + paste-back instructions
    async def test_start_auth_returns_url_and_instructions(self, tools):
        result = await tools.start_auth()
        expected_url = build_consent_url(tools.valves.google_client_id, LOOPBACK_REDIRECT)
        assert expected_url in result
        assert "finish_auth" in result

    # T0-4 (edge): start_auth with an empty client_id reports the missing valve
    async def test_start_auth_requires_client_id(self):
        t = Tools()
        result = await t.start_auth()
        assert result.startswith("Error:")
        assert "google_client_id" in result

    # @unit
    # Scenario: T0-5 finish_auth happy path
    #   Given the token seam returns access + refresh tokens for the code
    #   And the user pastes either the bare code or the full redirect URL with ?code=...
    #   When the tool runs finish_auth
    #   Then the result is an OK message
    #   And it contains the returned refresh token
    #   And it instructs to set it in the google_refresh_token valve
    @pytest.mark.parametrize(
        ("pasted", "label"),
        [
            ("abc123code", "bare_code"),
            ("http://127.0.0.1:8085/oauth2callback?code=abc123code&state=x", "redirect_url"),
        ],
        ids=["bare_code", "redirect_url"],
    )
    async def test_finish_auth_code_and_url(self, tools, pasted, label):
        token = {"access_token": "tok", "refresh_token": "new-refresh", "expires_in": 3600}
        with patch("youtube_manager._oauth_token", return_value=token) as seam:
            result = await tools.finish_auth(pasted)
        assert seam.call_args.kwargs["code"] == "abc123code"
        assert result.startswith("OK")
        assert "new-refresh" in result
        assert "google_refresh_token" in result

    # @unit
    # Scenario: T1-2 finish_auth reauth pass-through
    #   Given a Tools() with OAuth valves set (google_client_id, google_client_secret)
    #   And a mocked _oauth_token that raises ReauthNeeded (simulating 400/401 reject)
    #   When finish_auth(code="some-auth-code") is called
    #   Then the returned string starts with "REAUTH_NEEDED"
    #   And the returned string contains "Fix:"
    async def test_finish_auth_reauth_pass_through(self):
        t = Tools()
        t.valves.google_client_id = "client-id"
        t.valves.google_client_secret = "client-secret"
        with patch("youtube_manager._oauth_token", side_effect=ReauthNeeded("simulated")):
            result = await t.finish_auth("some-auth-code")
        assert result.startswith("REAUTH_NEEDED")
        assert "Fix:" in result

    # T0-5 (edge): finish_auth without a code errors without calling the token seam
    async def test_finish_auth_without_code(self, tools):
        with patch("youtube_manager._oauth_token"):
            result = await tools.finish_auth("http://127.0.0.1:8085/oauth2callback?error=access_denied")
        assert result.startswith("Error:")
        assert "code" in result

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("bare-code-123", "bare-code-123"),
            ("  bare-code-123  ", "bare-code-123"),
            ("http://127.0.0.1:8085/oauth2callback?code=url-code-456", "url-code-456"),
            ("", None),
            ("   ", None),
            ("http://127.0.0.1:8085/oauth2callback?error=access_denied", None),
        ],
        ids=["bare", "bare_stripped", "url_with_code", "empty", "whitespace", "url_without_code"],
    )
    # T0-5 (edge): parse_code_from_url extracts bare/URL codes and rejects empty input
    async def test_parse_code_from_url(self, text, expected):
        assert parse_code_from_url(text) == expected

    # @unit
    # Scenario: T0-6 reauth surfacing
    #   Given the token seam raises ReauthNeeded (invalid_grant)
    #   When finish_auth runs (or check_setup with a stored token)
    #   Then the result starts with "REAUTH_NEEDED"
    #   And it contains the start_auth re-onboarding instruction
    #   And no exception propagates
    @pytest.mark.parametrize(
        ("boom", "expected"),
        [
            (ReauthNeeded("invalid_grant"), "REAUTH_NEEDED"),
            (URLError("network down"), "Error: network error"),
        ],
        ids=["invalid_grant", "network_error"],
    )
    async def test_reauth_on_invalid_grant(self, tools, boom, expected):
        with patch("youtube_manager._oauth_token", side_effect=boom):
            result = await tools.finish_auth("sometoken")
        if expected == "REAUTH_NEEDED":
            assert result.startswith("REAUTH_NEEDED")
            assert "start_auth" in result
            assert "finish_auth" in result
        else:
            assert result == expected


def _http_error(status: int) -> HttpError:
    return HttpError(MagicMock(status=status, reason=str(status)), b"")


class TestCleanedErrorMapping:
    """B2: _error_return cleaned operator-facing reason mapping (non-verbose)."""

    # @unit [AC-2]
    # Scenario: B2 cleaned reason mapping
    #   Given an exception of each mapped kind
    #   When a generic error return is built without verbose
    #   Then the return is exactly "Error: <cleaned reason>" for that kind
    #   (reauthentication required / quota reached / not found - the resource no longer exists /
    #    rate limited - retry later / service unavailable - retry later / network error /
    #    invalid API response / transcript extraction failed / fallback dependency not installed /
    #    unexpected error)
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (ReauthNeeded("credential rejected"), "Error: reauthentication required"),
            (QuotaError("quota exceeded"), "Error: quota reached"),
            (_http_error(404), "Error: not found - the resource no longer exists"),
            (_http_error(429), "Error: rate limited - retry later"),
            (_http_error(503), "Error: service unavailable - retry later"),
            (_http_error(400), "Error: unexpected error"),
            (URLError("dns down"), "Error: network error"),
            (TimeoutError("slow"), "Error: network error"),
            (ValueError("bad"), "Error: invalid API response"),
            (json.JSONDecodeError("bad", "doc", 0), "Error: invalid API response"),
            (ExtractorError("bot check"), "Error: transcript extraction failed"),
            (DownloadError("download failed"), "Error: transcript extraction failed"),
            (TranscriptUnavailable("no dep"), "Error: fallback dependency not installed"),
            (RuntimeError("mystery"), "Error: unexpected error"),
        ],
    )
    def test_cleaned_error_reason_mapping(self, exc, expected):
        assert _error_return(exc) == expected
