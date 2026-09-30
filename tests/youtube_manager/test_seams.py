"""T0 direct seam tests: oauth token, data api, ytdlp, notes http, transcript fallback (T0-13..T0-17)."""

import io
import json
import sys
import urllib.error
import urllib.parse
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from yt_dlp.utils import ExtractorError

import youtube_manager
from youtube_manager import (
    CREDENTIAL_TITLE,
    QuotaError,
    ReauthNeeded,
    Tools,
    TranscriptUnavailable,
    _data_api_request,
    _error_return,
    _fetch_transcript_fallback,
    _notes_http,
    _oauth_token,
    _ytdlp_extract,
)


class _FakeResp:
    """urlopen answer: file-like read() + context manager."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _valves(**overrides):
    v = Tools().Valves()
    v.google_client_id = "client-id"
    v.google_client_secret = "client-secret"
    for key, value in overrides.items():
        setattr(v, key, value)
    return v


def _seed_credential(tmp_path, monkeypatch, token: str) -> None:
    """Seed the default user's credential file under a tmp DATA_DIR (the file store is the only source)."""
    data_dir = tmp_path / "data"
    user_dir = data_dir / "default"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / f"{CREDENTIAL_TITLE}.md").write_text(token)
    monkeypatch.setenv("DATA_DIR", str(data_dir))


class TestOauthToken:
    # @unit
    # Scenario: T0-13 oauth token seam
    #   Given a urllib seam (urlopen) that answers the token endpoint POST
    #   When _oauth_token runs with a stored refresh token (refresh grant)
    #   Then it POSTs grant_type=refresh_token with the client credentials and returns a dict with access_token, refresh_token, expires_in
    #   And when a code is given it uses grant_type=authorization_code with that code
    #   And when the endpoint answers invalid_grant (400) or 401 it raises ReauthNeeded (no other exception type)

    # @unit
    # Scenario: T4-1-S3 (unit) — trace: "and during execution"
    #   Given a stored credential file for the user (tmp DATA_DIR)
    #   When _oauth_token is called without a code and the token endpoint mock returns 200 with an access token
    #   Then the access token dict is returned and the refresh grant POSTed the file's token
    def test_refresh_grant(self, tmp_path, monkeypatch):
        token = {"access_token": "AT", "refresh_token": "NEW-RT", "expires_in": 3600}
        _seed_credential(tmp_path, monkeypatch, "stored-rt")
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResp(json.dumps(token).encode())
            result = _oauth_token(_valves(), code=None)
        assert result == token
        req = urlopen.call_args[0][0]
        assert req.full_url == "https://oauth2.googleapis.com/token"
        assert req.get_method() == "POST"
        body = urllib.parse.parse_qs(req.data.decode())
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["stored-rt"]
        assert body["client_id"] == ["client-id"]
        assert body["client_secret"] == ["client-secret"]

    def test_authorization_code_grant(self):
        token = {"access_token": "AT", "refresh_token": "NEW-RT", "expires_in": 3600}
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResp(json.dumps(token).encode())
            result = _oauth_token(_valves(), code="the-code")
        assert result == token
        body = urllib.parse.parse_qs(urlopen.call_args[0][0].data.decode())
        assert body["grant_type"] == ["authorization_code"]
        assert body["code"] == ["the-code"]

    @pytest.mark.parametrize(
        "code",
        [400, 401],
        ids=["invalid_grant_400", "unauthorized_401"],
    )
    # @unit
    # Scenario: T4-1-S4 (unit) — trace: "and during execution" (the re-auth loop on a revoked/expired grant)
    #   Given a stored credential file for the user (tmp DATA_DIR)
    #   When _oauth_token is called without a code and the token endpoint mock returns 400
    #   Then ReauthNeeded is raised with the existing stale-credential message (L834) and the REAUTH surfacing carries the start_auth/finish_auth fix guidance
    def test_reauth_on_bad_grant(self, code, tmp_path, monkeypatch):
        _seed_credential(tmp_path, monkeypatch, "stored-rt")
        err = urllib.error.HTTPError(
            "https://oauth2.googleapis.com/token", code, "err", Message(), io.BytesIO(b'{"error":"invalid_grant"}')
        )
        with patch("urllib.request.urlopen", side_effect=err), pytest.raises(ReauthNeeded):
            _oauth_token(_valves(), code=None)

    # @unit
    # Scenario: T1-3 oauth reject message branches on code presence
    #   Given the real _oauth_token function (unpatched)
    #   And a mocked urllib.request.urlopen that raises HTTPError(code=400)
    #   When _oauth_token is called with code="some-auth-code" (code present)
    #   Then the raised ReauthNeeded message contains "authorization code"
    #   And the raised ReauthNeeded message does NOT contain "stale"
    #   # And when _oauth_token is called with code=None (code absent)
    #   # Then the raised ReauthNeeded message equals "Google rejected the grant - stored credential is stale"
    @pytest.mark.parametrize(
        "code",
        ["some-auth-code", None],
        ids=["code_present", "code_absent"],
    )
    def test_reauth_message_branches_on_code_presence(self, code, tmp_path, monkeypatch):
        if code is None:
            _seed_credential(tmp_path, monkeypatch, "stored-rt")
        err = urllib.error.HTTPError(
            "https://oauth2.googleapis.com/token", 400, "err", Message(), io.BytesIO(b'{"error":"invalid_grant"}')
        )
        with patch("urllib.request.urlopen", side_effect=err), pytest.raises(ReauthNeeded) as exc_info:
            _oauth_token(_valves(), code=code)
        msg = str(exc_info.value)
        if code:
            assert "authorization code" in msg
            assert "stale" not in msg
        else:
            assert msg == "Google rejected the grant - stored credential is stale"

    def test_other_http_error_propagates(self, tmp_path, monkeypatch):
        _seed_credential(tmp_path, monkeypatch, "stored-rt")
        err = urllib.error.HTTPError(
            "https://oauth2.googleapis.com/token", 500, "boom", Message(), io.BytesIO(b"server error")
        )
        with patch("urllib.request.urlopen", side_effect=err), pytest.raises(urllib.error.HTTPError):
            _oauth_token(_valves(), code=None)


class TestDataApiRequest:
    # @unit
    # Scenario: T0-14 data api seam
    #   Given a built youtube v3 client whose executor answers playlistItems.list with an API JSON dict
    #   When _data_api_request runs a method
    #   Then it returns that API JSON dict
    #   And when the executor raises a 401/invalid_grant error it raises ReauthNeeded
    #   And when the executor raises a quotaExceeded error it raises QuotaError

    @staticmethod
    def _http_error(status: int, body: str) -> HttpError:
        return HttpError(MagicMock(status=status, reason=str(status)), body.encode())

    def test_returns_api_json(self):
        api_json = {"items": [{"id": "i1"}]}
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}) as token,
            patch("youtube_manager.discovery.build") as build,
        ):
            service = MagicMock()
            build.return_value = service
            request = MagicMock()
            request.execute.return_value = api_json
            service.playlistItems.list.return_value = request
            result = _data_api_request(_valves(), "playlistItems.list", {"playlistId": "PL1"})
        assert result is api_json
        token.assert_called_once()
        service.playlistItems.list.assert_called_once_with(playlistId="PL1")

    @pytest.mark.parametrize(
        ("status", "body", "exc"),
        [
            (401, "unauthorized", ReauthNeeded),
            (400, '{"error":"invalid_grant"}', ReauthNeeded),
            (403, '{"error":"quotaExceeded"}', QuotaError),
            (500, "server error", HttpError),
        ],
        ids=["unauthorized_401", "invalid_grant", "quota_exceeded", "server_error_propagates"],
    )
    def test_error_mapping(self, status, body, exc):
        err = self._http_error(status, body)
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build") as build,
        ):
            service = MagicMock()
            build.return_value = service
            service.playlistItems.list.side_effect = err
            with pytest.raises(exc):
                _data_api_request(_valves(), "playlistItems.list", {"playlistId": "PL1"})


class TestYtdlpExtract:
    # @unit
    # Scenario: T0-15 ytdlp seam
    #   Given a YoutubeDL factory whose instance answers extract_info with an info dict
    #   When _ytdlp_extract runs a URL (no valves, no session options)
    #   Then it returns that info dict
    #   And skip_download/quiet/no_warnings stay set in the options
    #   And an ExtractError raised by extract_info propagates unchanged (no re-wrap)

    def test_returns_info_dict(self):
        info = {"id": "vid1", "title": "T", "subtitles": {}}
        with patch("yt_dlp.YoutubeDL") as ydl_cls:
            instance = ydl_cls.return_value
            instance.extract_info.return_value = info
            result = _ytdlp_extract("https://youtu.be/vid1", {"quiet": False})
        assert result is info
        instance.extract_info.assert_called_once_with("https://youtu.be/vid1", download=False)
        opts = ydl_cls.call_args[0][0]
        assert "cookies" not in opts
        assert opts["quiet"] is False
        assert opts["skip_download"] is True
        assert opts["no_warnings"] is True

    def test_extractor_error_propagates_unchanged(self):
        boom = ExtractorError("Sign in to confirm you're not a bot")
        with patch("yt_dlp.YoutubeDL") as ydl_cls:
            ydl_cls.return_value.extract_info.side_effect = boom
            with pytest.raises(ExtractorError) as exc_info:
                _ytdlp_extract("https://youtu.be/vid1", None)
        assert exc_info.value is boom


class TestNotesHttp:
    # @unit
    # Scenario: T0-16 notes http seam
    #   Given a urllib seam that answers the Notes endpoint
    #   When _notes_http runs a GET (read) and a POST (write)
    #   Then it forwards the authorization header verbatim on both calls
    #   And it returns the parsed JSON dict for each
    #   And a non-2xx answer raises a structured error the caller can catch (no crash)

    def test_get_and_post_forward_auth(self):
        notes = {"notes": [{"title": "taste-profile", "content": "# x"}]}
        payload = {"title": "taste-profile", "content": "# x"}
        url = "http://localhost:3000/api/v1/studio/notes"
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [
                _FakeResp(json.dumps(notes).encode()),
                _FakeResp(json.dumps({"status": "ok"}).encode()),
            ]
            got = _notes_http("GET", url, "Bearer abc", None)
            posted = _notes_http("POST", url, "Bearer abc", payload)
        assert got == notes
        assert posted == {"status": "ok"}
        get_req, post_req = (call[0][0] for call in urlopen.call_args_list)
        assert get_req.get_header("Authorization") == "Bearer abc"
        assert post_req.get_header("Authorization") == "Bearer abc"
        assert post_req.get_method() == "POST"
        assert json.loads(post_req.data.decode()) == payload

    def test_non_2xx_raises_structured_error(self):
        err = urllib.error.HTTPError(
            "http://localhost:3000/api/v1/studio/notes", 404, "not found", Message(), io.BytesIO(b"nope")
        )
        with patch("urllib.request.urlopen", side_effect=err), pytest.raises(urllib.error.HTTPError):
            _notes_http("GET", "http://localhost:3000/api/v1/studio/notes", "Bearer abc", None)


class TestTranscriptFallback:
    # @unit
    # Scenario: T0-17 fallback seam
    #   Given the youtube-transcript-api module that returns caption segments for a video
    #   When _fetch_transcript_fallback runs
    #   Then it returns (segments, language_code) where segments are (start_seconds, text) tuples
    #   And when the dependency import fails it raises TranscriptUnavailable("fallback dependency not installed")

    def test_returns_segment_tuples(self, monkeypatch):
        fetched = MagicMock()
        fetched.language_code = "de"
        fetched.to_raw_data.return_value = [
            {"text": "hello", "start": 0.5, "duration": 1.0},
            {"text": "world", "start": 2.0, "duration": 1.0},
        ]
        module = MagicMock()
        module.YouTubeTranscriptApi.return_value.fetch.return_value = fetched
        monkeypatch.setitem(sys.modules, "youtube_transcript_api", module)
        assert _fetch_transcript_fallback("vid1") == ([(0, "hello"), (2, "world")], "de")

    def test_missing_dependency(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
        with pytest.raises(TranscriptUnavailable) as exc_info:
            _fetch_transcript_fallback("vid1")
        assert str(exc_info.value) == "fallback dependency not installed"


# @workflow [AC-2]
# Scenario: B2 verbose mode exposes detail without changing clean reason
#   Given a ReauthNeeded exception and verbose enabled
#   When a generic error return is built
#   Then it starts with "Error: reauthentication required (detail: "
#   And it ends with ")"
def test_verbose_error_detail():
    err = ReauthNeeded("Google credential rejected")
    result = _error_return(err, verbose=True)
    assert result.startswith("Error: reauthentication required (detail: ")
    assert result.endswith(f"{err!r})")
