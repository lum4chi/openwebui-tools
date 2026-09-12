"""T0 yt-dlp session options resolution (scenario T0-11)."""

import pytest

from youtube_manager import Tools, _ytdlp_options


class TestYtdlpOptions:
    # @unit
    # Scenario: T0-11 session options
    #   Given the valves match one of the cases:
    #     | case         | fields                                   |
    #     | cookies      | ytdlp_cookies_file set                   |
    #     | userpass     | ytdlp_username + ytdlp_password          |
    #     | userpass_2fa | userpass + ytdlp_2fa_code                |
    #     | none         | nothing                                  |
    #   When _ytdlp_options is called
    #   Then cookies -> {"cookies": <path>}, userpass -> username/password keys,
    #        userpass_2fa -> also the 2FA code key, none -> {}
    #   And all options keep skip_download/quiet/no_warnings set
    @pytest.mark.parametrize(
        ("case", "fields", "expected"),
        [
            (
                "cookies",
                {"ytdlp_cookies_file": "cookies.txt"},
                {"cookies": "cookies.txt", "skip_download": True, "quiet": True, "no_warnings": True},
            ),
            (
                "userpass",
                {"ytdlp_username": "user", "ytdlp_password": "pass"},
                {
                    "username": "user",
                    "password": "pass",
                    "skip_download": True,
                    "quiet": True,
                    "no_warnings": True,
                },
            ),
            (
                "userpass_2fa",
                {"ytdlp_username": "user", "ytdlp_password": "pass", "ytdlp_2fa_code": "123456"},
                {
                    "username": "user",
                    "password": "pass",
                    "twofactor": "123456",
                    "skip_download": True,
                    "quiet": True,
                    "no_warnings": True,
                },
            ),
            ("none", {}, {}),
        ],
        ids=["cookies", "userpass", "userpass_2fa", "none"],
    )
    def test_options_by_credential_case(self, case, fields, expected):
        valves = Tools().Valves()
        for field, value in fields.items():
            setattr(valves, field, value)
        assert _ytdlp_options(valves) == expected
