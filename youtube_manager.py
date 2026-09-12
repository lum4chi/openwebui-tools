"""
title: YouTube Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Personal YouTube digest - gathers candidates from the user's own feeds via a yt-dlp session, enriches via the YouTube Data API, and tracks state in Open WebUI Notes.
requirements: google-api-python-client, google-auth, yt-dlp, youtube-transcript-api
version: 1.0.0
licence: MIT
required_open_webui_version: 0.5.0

Agent instructions:
  SETUP (this slice):
  1. check_setup — verify the Google OAuth set + yt-dlp session (live token check only when the set is complete)
  2. start_auth — print the Google consent URL for the youtube scope
  3. finish_auth — exchange the pasted code/redirect URL and print the refresh token to store
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yt_dlp
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient import discovery
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

SCOPE = "https://www.googleapis.com/auth/youtube"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LOOPBACK_REDIRECT = "http://127.0.0.1:8085/oauth2callback"
NOTE_TASTE, NOTE_FEEDBACK, NOTE_STATE = "taste-profile", "feedback-log", "digest-state"
GOOGLE_FIELDS = ("google_client_id", "google_client_secret", "google_refresh_token")
DECISIONS = ("watched", "listened", "skipped")
DATA_API_VERSION = "v3"


class ReauthNeeded(Exception):  # noqa: N818 - plan/test contract name
    """Google credential invalid; run start_auth + finish_auth again."""


class QuotaError(Exception):
    """YouTube Data API quota exceeded."""


class TranscriptUnavailable(Exception):  # noqa: N818 - plan/test contract name
    """Transcript could not be fetched on any path."""


@dataclass
class Candidate:
    video_id: str
    title: str
    channel_name: str
    channel_id: str | None
    duration_sec: int | None
    views: int | None
    published: str | None
    description: str | None
    tags: list[str]
    sources: list[str]


@dataclass
class FeedbackEntry:
    date: str
    video_id: str
    decision: str
    title: str
    source: str
    reason: str


def build_consent_url(client_id: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def parse_code_from_url(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
        return params.get("code", [None])[0] or None
    return text


def classify_feed_error(err: Exception) -> str:
    msg = str(err).lower()
    if "bot" in msg and "confirm" in msg:
        return "bot_check"
    if "login" in msg or "log in" in msg or "sign in" in msg or "re-auth" in msg or "2fa" in msg:
        return "reauth"
    if "quota" in msg:
        return "quota"
    return "transient"


def serialize_feedback_line(entry: FeedbackEntry) -> str:
    return f"| {entry.date} | {entry.video_id} | {entry.decision} | {entry.title} | {entry.source} | {entry.reason} |"


def parse_feedback_log(md: str) -> list[FeedbackEntry]:
    entries: list[FeedbackEntry] = []
    for line in (md or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 6 or cells[2] not in DECISIONS:
            continue
        entries.append(FeedbackEntry(*cells))
    return entries


def serialize_digest_state(state: dict) -> str:
    return f"Digest state\n\n```json\n{json.dumps(state, indent=2)}\n```\n"


def parse_digest_state(md: str) -> dict:
    match = re.search(r"```json\n(.*?)\n```", md or "", re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _oauth_token(valves, code: str | None = None) -> dict:
    if code:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": valves.google_client_id,
            "client_secret": valves.google_client_secret,
            "redirect_uri": LOOPBACK_REDIRECT,
        }
    else:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": valves.google_refresh_token,
            "client_id": valves.google_client_id,
            "client_secret": valves.google_client_secret,
        }
    request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        if err.code in (400, 401):
            raise ReauthNeeded("Google rejected the grant - stored credential is stale") from err
        raise


def _authed_http(access_token: str):
    creds = Credentials(access_token)
    return AuthorizedHttp(creds)


def _map_api_error(err: HttpError) -> Exception | None:
    body = err.content.decode() if err.content else ""
    if "quota" in body.lower():
        return QuotaError("YouTube Data API quota exceeded")
    if err.resp.status in (401, 403) or "invalid_grant" in body:
        return ReauthNeeded("Google credential rejected by the Data API")
    return None


def _data_api_request(valves, method: str, params: dict) -> dict:
    token = _oauth_token(valves)
    service = discovery.build(
        "youtube",
        DATA_API_VERSION,
        http=_authed_http(token["access_token"]),
        cache_discovery=False,
    )
    try:
        resource = service
        for part in method.split("."):
            resource = getattr(resource, part)
        return resource(**params)
    except HttpError as err:
        mapped = _map_api_error(err)
        if mapped:
            raise mapped from err
        raise


def _ytdlp_options(valves) -> dict:
    if valves.ytdlp_cookies_file:
        return {
            "cookies": valves.ytdlp_cookies_file,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
    if valves.ytdlp_username:
        opts = {
            "username": valves.ytdlp_username,
            "password": valves.ytdlp_password,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        if valves.ytdlp_2fa_code:
            opts["twofactor"] = valves.ytdlp_2fa_code
        return opts
    return {}


def _ytdlp_extract(url: str, valves, extra: dict | None = None) -> dict:
    opts = cast("Any", {**_ytdlp_options(valves), **(extra or {})})
    ydl = yt_dlp.YoutubeDL(opts)
    return cast("dict", ydl.extract_info(url, download=False))


def _fetch_transcript_fallback(video_id: str) -> list[tuple[int, str]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as err:
        raise TranscriptUnavailable("fallback dependency not installed") from err
    fetched = YouTubeTranscriptApi().fetch(video_id)
    return [(int(segment["start"]), segment["text"]) for segment in fetched.to_raw_data()]


def _notes_http(method: str, url: str, auth: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", auth)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read().decode())


class _FileStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def read(self, title: str) -> str | None:
        path = self.data_dir / f"{title}.md"
        return path.read_text() if path.exists() else None

    def write(self, title: str, md: str) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / f"{title}.md").write_text(md)


class _NotesStore:
    def __init__(self, url: str, auth: str):
        self.url = url
        self.auth = auth

    def read(self, title: str) -> str | None:
        resp = _notes_http("GET", self.url, self.auth, None)
        for note in resp.get("notes", []):
            if note.get("title") == title:
                return note.get("content")
        return None

    def write(self, title: str, md: str) -> None:
        _notes_http("POST", self.url, self.auth, {"title": title, "content": md})


def _state_store(request):
    if request is not None and request.headers.get("authorization"):
        auth = request.headers.get("authorization")
        base = (request.base_url or "http://localhost:3000/").rstrip("/")
        return _NotesStore(f"{base}/api/v1/studio/notes", auth)
    data_dir = Path(os.environ.get("DATA_DIR") or Path.cwd() / "data")
    return _FileStore(data_dir)


def _token_status(valves) -> str | None:
    try:
        _oauth_token(valves)
    except ReauthNeeded:
        return "google token: INVALID - stored refresh token is stale; run start_auth then finish_auth"
    except Exception:
        return "google token: CHECK FAILED - token endpoint unreachable"
    return None


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        # google oauth (sanctioned half)
        google_client_id: str = Field(
            default="", description="Google OAuth client ID (installed-app, Production-mode client)"
        )
        google_client_secret: str = Field(default="", description="Google OAuth client secret")
        google_refresh_token: str = Field(
            default="", description="Stored OAuth refresh token (scope: https://www.googleapis.com/auth/youtube)"
        )
        # yt-dlp session (personal half)
        ytdlp_cookies_file: str = Field(
            default="", description="Path to exported Netscape cookies.txt for youtube.com (personal feeds)"
        )
        ytdlp_username: str = Field(default="", description="YouTube username (alternative to cookies file)")
        ytdlp_password: str = Field(default="", description="YouTube password (used with ytdlp_username)")
        ytdlp_2fa_code: str = Field(default="", description="One-time 2FA code, set when YouTube asks for it")
        # digest playlist policy
        digest_playlist: str = Field(
            default="watch_later", description="Managed digest playlist (v1: watch_later only)"
        )
        digest_max_items: int = Field(
            default=50, ge=1, description="Policy cap: keep at most the newest N tool-added items"
        )
        digest_max_age_days: int = Field(
            default=30, ge=1, description="Policy cap: drop tool-added items older than D days"
        )

    async def check_setup(self) -> str:
        valves = self.valves
        lines: list[str] = []
        google_ok = True
        for name in GOOGLE_FIELDS:
            if getattr(valves, name):
                continue
            google_ok = False
            lines.append(f"{name}: MISSING - set Valves.{name} (Google Cloud OAuth client)")
        session_ok = bool(valves.ytdlp_cookies_file or valves.ytdlp_username)
        if session_ok:
            lines.append("yt-dlp session: configured")
        else:
            lines.append("yt-dlp session: MISSING - set Valves.ytdlp_cookies_file or ytdlp_username/ytdlp_password")
        token_line = _token_status(valves) if google_ok else None
        if token_line:
            lines.append(token_line)
        ready = google_ok and session_ok and token_line is None
        lines.append("READY" if ready else "NOT READY")
        return "\n".join(lines)

    async def start_auth(self) -> str:
        client_id = self.valves.google_client_id
        if not client_id:
            return "Error: set Valves.google_client_id (Google Cloud OAuth client ID) first, then run start_auth again."
        url = build_consent_url(client_id, LOOPBACK_REDIRECT)
        return (
            "Open this URL in a browser, authorize, and paste the full redirect address (or just the code) into finish_auth:\n"
            f"{url}"
        )

    async def finish_auth(self, code_or_url: str) -> str:
        code = parse_code_from_url(code_or_url)
        if not code:
            return "Error: no authorization code found - paste the full redirect URL with ?code= from the browser."
        try:
            token = _oauth_token(self.valves, code=code)
        except ReauthNeeded as err:
            return f"REAUTH_NEEDED\n{err}\nFix: run start_auth, open the URL, then finish_auth with the new code."
        except Exception as err:
            return f"Error: {err}"
        return (
            "OK\n"
            "Authorization code exchanged. Set the stored valve:\n"
            f"  Valves.google_refresh_token = {token['refresh_token']}"
        )
