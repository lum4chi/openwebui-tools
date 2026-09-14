"""T0 feed error classification corpus (scenario T0-12) + T3-1 provider-vs-local status surfacing."""

import urllib.error

import pytest
from googleapiclient.errors import HttpError

from youtube_manager import QuotaError, ReauthNeeded, _failure_reason, classify_feed_error


class _Resp:
    """HttpError resp stand-in: numeric status + reason text (or None)."""

    def __init__(self, status: int, reason: str | None):
        self.status = status
        self.reason = reason


def _http_error(status: int, reason: str | None = None) -> HttpError:
    return HttpError(_Resp(status, reason), b"")


class TestClassifyFeedError:
    # @unit
    # Scenario: T0-12 error classification (corpus) + T3-1 provider-vs-local tokens
    #   Given an exception from one of the corpus rows:
    #     | input                                         | expected    |
    #     | "Sign in to confirm you're not a bot"         | bot_check   |
    #     | "quota" / "quotaExceeded"                     | quota       |
    #     | login/2FA/re-auth/503/timeout messages        | local       |
    #     | HttpError status 401 / 403                    | permissions |
    #     | HttpError status 400                          | client      |
    #     | HttpError status 429 / 500 / 503              | transient   |
    #     | network error (URLError / TimeoutError)       | transient   |
    #     | local/code exception (AttributeError, ...)    | local       |
    #   When classify_feed_error is called
    #   Then it returns the expected token for every row
    #   And a local/code exception returns "local" (not blanket "transient")
    @pytest.mark.parametrize(
        ("err", "expected"),
        [
            (Exception("Sign in to confirm you're not a bot"), "bot_check"),
            (Exception("LOGIN"), "local"),
            (Exception("2FA required"), "local"),
            (Exception("re-auth"), "local"),
            (Exception("quota"), "quota"),
            (Exception("quotaExceeded"), "quota"),
            (Exception("503"), "local"),
            (Exception("timeout"), "local"),
            (Exception("Connection reset"), "local"),
            (Exception("some unrecognised failure"), "local"),
        ],
        ids=[
            "bot_check",
            "login",
            "2fa",
            "reauth_message",
            "quota",
            "quota_exceeded",
            "503",
            "timeout",
            "connection_reset",
            "unrecognised",
        ],
    )
    def test_classification(self, err, expected):
        assert classify_feed_error(err) == expected

    # @unit
    # Scenario: T3-1 classify_feed_error distinguishes an HttpError by status
    #   Given classify_feed_error
    #   When an HttpError with status 401 or 403 is passed Then it returns "permissions"
    #   When an HttpError with status 400 is passed      Then it returns "client"
    #   When an HttpError with status 429/500/503 is passed Then it returns "transient"
    #   When a network error (urllib.error.URLError) is passed Then it returns "transient"
    #   When a local/code exception (AttributeError/KeyError) is passed Then it returns "local"
    #   When a QuotaError is passed Then it returns "quota"
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, "permissions"),
            (403, "permissions"),
            (400, "client"),
            (429, "transient"),
            (500, "transient"),
            (503, "transient"),
        ],
        ids=["http_401", "http_403", "http_400", "http_429", "http_500", "http_503"],
    )
    def test_http_error_by_status(self, status, expected):
        assert classify_feed_error(_http_error(status, str(status))) == expected

    @pytest.mark.parametrize(
        "err",
        [
            urllib.error.URLError("network down"),
            TimeoutError("read timed out"),
            ConnectionError("connection reset"),
            AttributeError("no attribute 'x'"),
            KeyError("videoId"),
            RuntimeError("backend 500"),
            QuotaError("YouTube Data API quota exceeded"),
        ],
        ids=["url_error", "timeout", "connection", "attribute_error", "key_error", "runtime_error", "quota_error"],
    )
    def test_network_local_and_quota(self, err):
        if isinstance(err, (urllib.error.URLError, ConnectionError, TimeoutError)):
            assert classify_feed_error(err) == "transient"  # network
        elif isinstance(err, QuotaError):
            assert classify_feed_error(err) == "quota"
        else:
            assert classify_feed_error(err) == "local"  # local/code


class TestFailureReason:
    """The digest-note formatter: status + message surfaced for HttpError, tokens otherwise."""

    # @unit
    # Scenario: T3-1 digest failure note surfaces the HttpError status + message
    #   Given a healthy auth where a Data-API call raises an HttpError 503 (reason "Service Unavailable")
    #   When the digest note is formatted (note reads "watch_later failed: {_failure_reason(err)}")
    #   Then the note reads "watch_later failed: transient HTTP 503: Service Unavailable"
    #   And a ReauthNeeded path still yields "watch_later failed: reauth" (unchanged)
    #   And a bot_check message still yields token-only "bot_check" (unchanged)
    #   And a local/code exception yields token-only "local" (no fake status)
    def test_http_error_carries_status_and_message(self):
        err = _http_error(503, "Service Unavailable")
        assert _failure_reason(err) == "transient HTTP 503: Service Unavailable"

    def test_http_error_without_reason_falls_back_to_message(self):
        assert _failure_reason(_http_error(500, None)).startswith("transient HTTP 500: ")

    def test_reauth_token_unchanged(self):
        assert _failure_reason(ReauthNeeded("Google credential rejected by the Data API")) == "reauth"

    def test_bot_check_token_unchanged(self):
        assert _failure_reason(Exception("Sign in to confirm you're not a bot")) == "bot_check"

    def test_local_is_token_only(self):
        assert _failure_reason(AttributeError("no attribute 'x'")) == "local"
