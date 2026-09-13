"""T0 feed error classification corpus (scenario T0-12)."""

import pytest

from youtube_manager import classify_feed_error


class TestClassifyFeedError:
    # @unit
    # Scenario: T0-12 error classification
    #   Given an exception whose message matches one of the corpus rows:
    #     | message pattern                          | expected class |
    #     | "Sign in to confirm you're not a bot"    | bot_check      |
    #     | "quota" / "quotaExceeded"                | quota          |
    #     | "503" / "timeout" / "Connection reset"   | transient      |
    #   When classify_feed_error is called
    #   Then it returns the expected class for every row
    #   And an unrecognised message returns "transient"
    #   And login/2FA messages carry no reauth class after the purge (decision 3) - they fall through to "transient"
    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Sign in to confirm you're not a bot", "bot_check"),
            ("LOGIN", "transient"),
            ("2FA required", "transient"),
            ("re-auth", "transient"),
            ("quota", "quota"),
            ("quotaExceeded", "quota"),
            ("503", "transient"),
            ("timeout", "transient"),
            ("Connection reset", "transient"),
            ("some unrecognised failure", "transient"),
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
    def test_classification(self, message, expected):
        assert classify_feed_error(Exception(message)) == expected
