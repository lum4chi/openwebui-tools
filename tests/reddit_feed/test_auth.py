"""Auth, valve, error-surface, and rate-limit tests for the reddit_feed tool (S5, S9, S10)."""

import json
import time
from unittest.mock import patch

import pytest
import requests

import reddit_feed
from reddit_feed import TIMEOUT, TOKEN_URL


# @unit
# Scenario: T1-1-S5 Script-app OAuth token flow
#   # Provenance: locked scope 1 (script app), user-confirmed at intake
#   Given the OAuth valves are set
#   When the tool requests an access token
#   Then it POSTs to the token endpoint with HTTP Basic client credentials and grant_type password with username and password
#   And every subsequent API request carries Authorization Bearer and a descriptive User-Agent
async def test_token_flow(tools, make_response, subs_listing, feed_listing, comment_tree):
    now = time.time()
    token_resp = make_response(200, {"access_token": "tok-1", "token_type": "bearer", "expires_in": 3600})
    subs = make_response(200, subs_listing(["python"]))
    feed = make_response(200, feed_listing(now, [(0, 60)]))
    comment = make_response(200, comment_tree())

    with (
        patch("requests.post", return_value=token_resp) as mock_post,
        patch("requests.get", side_effect=[subs, feed, comment]) as mock_get,
    ):
        raw = await tools.get_home_feed()

    assert json.loads(raw)["item_count"] == 1

    post_args = mock_post.call_args
    assert post_args.args[0] == TOKEN_URL
    assert post_args.kwargs["auth"] == ("client-id", "client-secret")
    assert post_args.kwargs["data"] == {
        "grant_type": "password",
        "username": "testuser",
        "password": "testpass",
    }
    assert post_args.kwargs["headers"]["User-Agent"] == "openwebui:reddit-feed-digest:1.0.0 (by /u/testuser)"
    assert post_args.kwargs["timeout"] == TIMEOUT

    for call in mock_get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer tok-1"
        assert call.kwargs["headers"]["User-Agent"] == "openwebui:reddit-feed-digest:1.0.0 (by /u/testuser)"


# @unit
# Scenario: T1-1-S9 Failures surface as readable error strings
#   # Provenance: AC-1 (the digest call must fail gracefully, never raise);
#   # house convention: tool methods return readable error strings, never raise (email tools).
#   Given a failure mode: missing OAuth valves, or token endpoint 401, or data endpoint 429 twice, or a network failure
#   When get_home_feed() is called
#   Then a human-readable error string naming the failure is returned and no exception escapes
@pytest.mark.parametrize("valve", ["client_id", "client_secret", "username", "password"])
async def test_missing_valves_error(tools, valve):
    setattr(tools.valves, valve, "")
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        result = await tools.get_home_feed()
    assert result == "Reddit OAuth valves are not configured. Set client id, client secret, username and password."
    mock_post.assert_not_called()
    mock_get.assert_not_called()


# @unit
# Scenario: T1-1-S9 Failures surface as readable error strings
#   # Provenance: AC-1 (the digest call must fail gracefully, never raise);
#   # house convention: tool methods return readable error strings, never raise (email tools).
#   Given a failure mode: missing OAuth valves, or token endpoint 401, or data endpoint 429 twice, or a network failure
#   When get_home_feed() is called
#   Then a human-readable error string naming the failure is returned and no exception escapes
async def test_auth_401_error(tools, make_response):
    with patch("requests.post", return_value=make_response(401, {})), patch("requests.get") as mock_get:
        result = await tools.get_home_feed()
    assert result == "Reddit authentication failed (401): check the OAuth valves."
    mock_get.assert_not_called()


# @unit
# Scenario: T1-1-S9 Failures surface as readable error strings
#   # Provenance: AC-1 (the digest call must fail gracefully, never raise);
#   # house convention: tool methods return readable error strings, never raise (email tools).
#   Given a failure mode: missing OAuth valves, or token endpoint 401, or data endpoint 429 twice, or a network failure
#   When get_home_feed() is called
#   Then a human-readable error string naming the failure is returned and no exception escapes
@pytest.mark.parametrize("phase", ["token-phase", "data-phase"])
async def test_network_error(tools, make_response, phase):
    if phase == "token-phase":
        with (
            patch("requests.post", side_effect=requests.exceptions.ConnectionError("token down")),
            patch("requests.get") as mock_get,
        ):
            result = await tools.get_home_feed()
        assert result == "Reddit request failed: token down"
        mock_get.assert_not_called()
    else:
        token = make_response(200, {"access_token": "tok-1"})
        with (
            patch("requests.post", return_value=token),
            patch("requests.get", side_effect=requests.exceptions.ConnectionError("data down")),
        ):
            result = await tools.get_home_feed()
        assert result == "Reddit request failed: data down"


# @unit
# Scenario: T1-1-S9 Failures surface as readable error strings
#   # Provenance: AC-1 (the digest call must fail gracefully, never raise);
#   # house convention: tool methods return readable error strings, never raise (email tools).
#   Given a failure mode: missing OAuth valves, or token endpoint 401, or data endpoint 429 twice, or a network failure
#   When get_home_feed() is called
#   Then a human-readable error string naming the failure is returned and no exception escapes
def test_http_error_without_response():
    error = requests.HTTPError("boom")
    assert error.response is None
    assert reddit_feed._http_error_detail(error) == (0, "")


# @unit
# Scenario: T1-1-S10 A single transient 429 does not fail the digest
#   # Provenance: AC-1 (transient throttling must not break the digest); user-confirmed RETRY-ONCE —
#   # OPEN-3 resolved, user verbatim: "ok" (retry once after a short delay on 429 is the default)
#   Given the first data response is 429 with Retry-After 0
#   And the retried response succeeds
#   When get_home_feed() is called
#   Then the digest is returned successfully
async def test_rate_limit_retry_once(tools, make_response, subs_listing):
    subs_429 = make_response(429, {}, {"Retry-After": "0"})
    subs_ok = make_response(200, subs_listing(["python"]))
    feed = make_response(200, {"kind": "Listing", "data": {"children": [], "after": None}})
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=[subs_429, subs_ok, feed]) as mock_get,
    ):
        result = await tools.get_home_feed()
    digest = json.loads(result)
    assert digest["item_count"] == 0
    assert not result.startswith("Reddit")
    assert mock_get.call_count == 3


# @unit
# Scenario: T1-1-S9 Failures surface as readable error strings
#   # Provenance: AC-1 (the digest call must fail gracefully, never raise);
#   # house convention: tool methods return readable error strings, never raise (email tools).
#   Given a failure mode: missing OAuth valves, or token endpoint 401, or data endpoint 429 twice, or a network failure
#   When get_home_feed() is called
#   Then a human-readable error string naming the failure is returned and no exception escapes
async def test_rate_limit_exhausted_error(tools, make_response):
    first = make_response(429, {}, {"Retry-After": "0"})
    second = make_response(429, {}, {"Retry-After": "0"})
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=[first, second]) as mock_get,
    ):
        result = await tools.get_home_feed()
    assert result == "Reddit API error (429): Too Many Requests"
    assert mock_get.call_count == 2
