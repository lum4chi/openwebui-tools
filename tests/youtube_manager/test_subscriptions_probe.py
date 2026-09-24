"""T1-1 S9/S10/S11: check_setup probes the real subscription-feed capability (token scope is not proof of listing)."""

from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError

from .conftest import api_fake, guard_urlopen, listing_page, sub_channel, uploads_channel_reply


def _quota_error() -> HttpError:
    body = b'{"error": {"message": "You have exceeded your quota.", "errors": [{"reason": "quotaExceeded"}]}}'
    return HttpError(MagicMock(status=403, reason="quotaExceeded"), body)


class TestCheckSetupSubscriptionsProbe:
    """check_setup distinguishes token scope (OAuth ok) from the ability to actually list subscription videos."""

    # S9 [unit] — AC suggestion 2 (capability true)
    # Scenario: check_setup reports the subscription feed capability
    #   Given healthy OAuth, mocked subscriptions.list (1 item), channels.list, playlistItems.list all succeeding
    #   And the watch_later probe succeeding
    #   When check_setup runs
    #   Then the subscriptions line is "subscriptions: ok (subscription feed checked)"
    #   And the overall line is "READY"
    async def test_probe_reports_subscription_feed_capability(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={"PU0000": [listing_page([])], "WL": [listing_page([])]},
            subscription_pages=[{"items": [sub_channel("UC0000")]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
        )
        guard_urlopen(monkeypatch)
        with patch("youtube_manager._oauth_token", return_value={"access_token": "fake"}):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (subscription feed checked)",
            "watch_later: ok (playlist checked)",
            "READY",
        ]

    # S10 [unit] — AC suggestion 2 (the report's exact scenario: "token has youtube scope" true, "can actually list subscription videos" false)
    # Scenario: check_setup distinguishes token scope from listing capability
    #   Given healthy OAuth (token endpoint ok) and subscriptions.list succeeding
    #   And playlistItems.list raising HttpError 403 during the probe
    #   When check_setup runs
    #   Then the subscriptions line is "subscriptions: CHECK FAILED - HTTP 403: …"
    #   And the watch_later line is still "watch_later: ok (playlist checked)"
    #   And the overall line is "NOT READY"
    async def test_probe_surfaces_http_403_during_listing(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={"WL": [listing_page([])]},
            subscription_pages=[{"items": [sub_channel("UC0000")]}],
            channels_by_id={"UC0000": uploads_channel_reply("PU0000")},
            raise_for_playlist={"PU0000": _quota_error()},
        )
        guard_urlopen(monkeypatch)
        with patch("youtube_manager._oauth_token", return_value={"access_token": "fake"}):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: CHECK FAILED - HTTP 403: You have exceeded your quota. (quotaExceeded)",
            "watch_later: ok (playlist checked)",
            "NOT READY",
        ]

    # S11 [unit] — edge: zero subscriptions
    # Scenario: check_setup with zero subscriptions
    #   Given subscriptions.list returning an empty items list
    #   And the watch_later probe succeeding
    #   When check_setup runs
    #   Then the subscriptions line is "subscriptions: ok (0 subscriptions)"
    #   And the overall line is "READY"
    async def test_probe_zero_subscriptions(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={"WL": [listing_page([])]},
            subscription_pages=[{"items": []}],
        )
        guard_urlopen(monkeypatch)
        with patch("youtube_manager._oauth_token", return_value={"access_token": "fake"}):
            result = await tools.check_setup()
        assert result.splitlines() == [
            "search: ok",
            "subscriptions: ok (0 subscriptions)",
            "watch_later: ok (playlist checked)",
            "READY",
        ]
