"""T1-1 (NTH-3): check_setup reflects the search bot-check cooldown (scenarios T1-1.S1–T1-1.S2)."""

from unittest.mock import patch

import youtube_manager
from youtube_manager import Tools


def _probe_return(value: str):
    async def probe(self, user_id=None):
        return value

    return probe


class TestCheckSetupCooldown:
    """The check_setup search line reflects an active bot-check cooldown."""

    # @unit
    # Scenario: T1-1.S1 check_setup shows the bot-check cooldown clause on the search line
    # Given a working OAuth setup (healthy token via _oauth_token, watch_later probe returns "ok (surrogate playlist checked)")
    # And the search bot-check cooldown is active (the injected _now clock is within SEARCH_BOT_CHECK_COOLDOWN_SECONDS of tools._search_bot_check_at)
    # When the agent calls check_setup
    # Then the first line is exactly "search: ok (bot-check cooldown active)"
    # And the overall status line is "READY"
    async def test_s1_cooldown_clause_on_search_line(self, tools, monkeypatch):
        base = 1000.0
        tools._search_bot_check_at = base
        monkeypatch.setattr(
            youtube_manager,
            "_now",
            lambda: base + youtube_manager.SEARCH_BOT_CHECK_COOLDOWN_SECONDS / 2,
        )
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("ok (surrogate playlist checked)")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok (bot-check cooldown active)"
        assert lines[-1] == "READY"

    # @unit
    # Scenario: T1-1.S2 regression guard: check_setup shows the plain search line when no cooldown is active
    # Given a working OAuth setup (healthy token via _oauth_token, watch_later probe returns "ok (surrogate playlist checked)")
    # And no bot-check cooldown is active (tools._search_bot_check_at is None)
    # When the agent calls check_setup
    # Then the first line is exactly "search: ok"
    # And the overall status line is "READY"
    async def test_s2_plain_search_line_without_cooldown(self, tools):
        assert tools._search_bot_check_at is None
        with (
            patch(
                "youtube_manager._oauth_token",
                return_value={"access_token": "tok", "refresh_token": "r", "expires_in": 3600},
            ),
            patch.object(Tools, "_watch_later_probe", _probe_return("ok (surrogate playlist checked)")),
            patch.object(Tools, "_subscriptions_probe", _probe_return("ok (subscription feed checked)")),
        ):
            result = await tools.check_setup()
        lines = result.splitlines()
        assert lines[0] == "search: ok"
        assert lines[-1] == "READY"
