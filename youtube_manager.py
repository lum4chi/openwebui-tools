"""
title: YouTube Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Personal YouTube digest - gathers candidates from the user's watch later, subscribed channels, and search via anonymous yt-dlp and the YouTube Data API, and tracks state in Open WebUI Notes.
requirements: google-api-python-client, google-auth, yt-dlp, youtube-transcript-api
version: 1.1.0
licence: MIT
required_open_webui_version: 0.5.0

Agent instructions:
  SETUP (this slice):
   1. check_setup — verify the Google OAuth set (live token check only when the set is complete)
  2. start_auth — print the Google consent URL for the youtube scope
  3. finish_auth — exchange the pasted code/redirect URL and print the refresh token to store
"""

import contextlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
SOURCES = ("watch_later", "search", "subscriptions")
REAUTH_CLASSES = ("reauth",)
TASTE_STARTER = "# Taste profile\n\n## Topics\n- rust async\n- postgres\n\n## Avoid\n- cat videos"
PODCAST_MAX_LINES = 400
MAX_PER_SOURCE = 20
SUBSCRIPTION_CHANNEL_CAP = 25
RSS_TIMEOUT = 10.0
FEEDBACK_HEADER = "| date | video_id | decision | title | source | reason |"


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


@dataclass
class FeedbackStats:
    totals: dict[str, int]
    skips_by_duration_band: dict[str, int]
    channel_counts: list[tuple[str, int, int]]


@dataclass
class TasteProfile:
    topics: list[str]
    disliked: set[str]
    text: str


@dataclass
class PruneItem:
    item_id: str
    video_id: str
    title: str
    added_at: str


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


def _http_status(err: Exception) -> int | None:
    status = getattr(getattr(err, "resp", None), "status", None)
    return status if isinstance(status, int) else None


def _http_message(err: Exception) -> str:
    return str(getattr(getattr(err, "resp", None), "reason", None) or err)


def classify_feed_error(err: Exception) -> str:
    msg = str(err).lower()
    if "bot" in msg and "confirm" in msg:
        return "bot_check"
    if "quota" in msg:
        return "quota"
    status = _http_status(err)
    if status is not None:
        if status in (401, 403):
            return "permissions"
        if status == 400:
            return "client"
        return "transient"  # 429 / 5xx / other HTTP
    if isinstance(err, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return "transient"  # network
    return "local"  # local/code: AttributeError, KeyError, RuntimeError, ...


def _failure_label(err: Exception) -> str:
    """Provider failures keep the YouTube Error label; local/code failures get a clearly-local label."""
    return "YouTube Error" if isinstance(err, (HttpError, QuotaError)) else "Local Error"


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


def parse_sources_arg(s: str) -> list[str] | None:
    names = [part.strip() for part in (s or "").split(",")]
    if any(name not in SOURCES for name in names):
        return None
    return names


def _published_from_ts(entry: dict) -> str | None:
    ts = entry.get("timestamp")
    if ts:
        return datetime.fromtimestamp(int(ts), tz=UTC).date().isoformat()
    date = entry.get("upload_date")
    if isinstance(date, str) and len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return None


def candidates_from_ytdlp(entries: list[dict], source: str) -> list[Candidate]:
    cands: list[Candidate] = []
    for entry in entries:
        cands.append(
            Candidate(
                video_id=entry.get("id", ""),
                title=entry.get("title") or "",
                channel_name=entry.get("uploader") or entry.get("channel") or "",
                channel_id=entry.get("channel_id"),
                duration_sec=entry.get("duration"),
                views=entry.get("view_count"),
                published=_published_from_ts(entry),
                description=entry.get("description"),
                tags=entry.get("tags") or [],
                sources=[source],
            )
        )
    return cands


def _iso_duration_to_sec(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    days, hours, minutes, secs = (int(part) if part else 0 for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + secs


def _published_from_api(value: object) -> str | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    return value[:10]


def candidates_from_api(items: list[dict], source: str) -> list[Candidate]:
    cands: list[Candidate] = []
    for item in items:
        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        views = snippet.get("viewCount")
        cands.append(
            Candidate(
                video_id=item.get("id", ""),
                title=snippet.get("title") or "",
                channel_name=snippet.get("channelTitle") or "",
                channel_id=snippet.get("channelId"),
                duration_sec=_iso_duration_to_sec(content.get("duration")),
                views=int(views) if views is not None else None,
                published=_published_from_api(snippet.get("publishedAt")),
                description=snippet.get("description"),
                tags=snippet.get("tags") or [],
                sources=[source],
            )
        )
    return cands


def _rss_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _fetch_rss(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=RSS_TIMEOUT) as resp:
        return resp.read()


def _rss_local(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _rss_find(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem.iter():
        if child is not elem and _rss_local(child) == name:
            return child
    return None


def _rss_text(elem: ET.Element, name: str) -> str | None:
    found = _rss_find(elem, name)
    if found is None or not found.text:
        return None
    return found.text


def _rss_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rss_attr(elem: ET.Element | None, name: str) -> str | None:
    return elem.get(name) if elem is not None else None


def _rss_entry(elem: ET.Element) -> dict | None:
    video_id = _rss_text(elem, "videoId")
    if video_id is None:
        atom_id = _rss_text(elem, "id")
        video_id = atom_id.removeprefix("yt:video:") if atom_id and atom_id.startswith("yt:video:") else None
    if video_id is None:
        return None
    return {
        "video_id": video_id,
        "title": _rss_text(elem, "title"),
        "channel_name": _rss_text(elem, "name"),
        "channel_id": _rss_text(elem, "channelId") or "",
        "published": _published_from_api(_rss_text(elem, "published")),
        "duration_sec": _rss_int(_rss_attr(_rss_find(elem, "content"), "duration")),
        "views": _rss_int(_rss_attr(_rss_find(elem, "statistics"), "views")),
        "description": _rss_text(elem, "description"),
    }


def _parse_rss(raw: bytes) -> list[dict]:
    entries: list[dict] = []
    for elem in ET.fromstring(raw).iter():
        if _rss_local(elem) != "entry":
            continue
        entry = _rss_entry(elem)
        if entry is not None:
            entries.append(entry)
    return entries


def candidates_from_rss(entries: list[dict], source: str) -> list[Candidate]:
    cands: list[Candidate] = []
    for entry in entries:
        cands.append(
            Candidate(
                video_id=entry["video_id"],
                title=entry["title"] or "",
                channel_name=entry["channel_name"] or "",
                channel_id=entry["channel_id"],
                duration_sec=entry["duration_sec"],
                views=entry["views"],
                published=entry["published"],
                description=entry["description"],
                tags=[],
                sources=[source],
            )
        )
    return cands


def merge_candidates(lists: list[list[Candidate]]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for batch in lists:
        for cand in batch:
            existing = merged.get(cand.video_id)
            if existing is None:
                merged[cand.video_id] = cand
                continue
            new = [name for name in cand.sources if name not in existing.sources]
            existing.sources = [*existing.sources, *new]
    return list(merged.values())


def _topic_batch(topic: str, source_counts: dict[str, int], notes: list[str]) -> list[Candidate]:
    """One digest topic search; a failure is a note (never a reauth), the count is recorded pre-merge."""
    label = f"search:{topic}"
    candidates: list[Candidate] = []
    try:
        entries = _ytdlp_extract(f"ytsearch{MAX_PER_SOURCE}:{topic}").get("entries") or []
    except Exception as err:
        notes.append(f"source {topic} failed: {_failure_reason(err)}")
    else:
        candidates = candidates_from_ytdlp(entries, label)
    source_counts[label] = len(candidates)
    return candidates


def _bullets_under(md: str, heading: str) -> list[str] | None:
    """Bullets under a heading (None when the heading is absent, [] when it has none)."""
    bullets: list[str] = []
    found = False
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if found:
                break
            found = stripped == heading
            continue
        if found and stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets if found else None


def _first_bullet_list(md: str) -> list[str]:
    lines = [line.strip() for line in md.splitlines()]
    start = next((i for i, line in enumerate(lines) if line.startswith("- ")), len(lines))
    stop = next((i for i in range(start, len(lines)) if not lines[i].startswith("- ")), len(lines))
    return [lines[i][2:].strip() for i in range(start, stop)]


def parse_taste_profile(md: str | None) -> TasteProfile:
    text = md or ""
    if not text.strip():
        return TasteProfile([], set(), text)
    topics = _bullets_under(text, "## Topics")
    if topics is None:
        topics = _first_bullet_list(text)
    disliked = {bullet.lower() for bullet in _bullets_under(text, "## Avoid") or []}
    return TasteProfile(topics, disliked, text)


def filter_disliked(candidates: list[Candidate], disliked: set[str]) -> tuple[list[Candidate], int]:
    kept: list[Candidate] = []
    removed = 0
    for cand in candidates:
        if any(needle in cand.title.lower() for needle in disliked):
            removed += 1
            continue
        kept.append(cand)
    return kept, removed


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _duration_band(sec: int) -> str:
    if sec < 600:
        return "<10m"
    if sec <= 1800:
        return "10-30m"
    return ">30m"


def aggregate_feedback(entries: list[FeedbackEntry], candidates: list[Candidate]) -> FeedbackStats:
    by_id = {cand.video_id: cand for cand in candidates}
    totals: dict[str, int] = {}
    bands: dict[str, int] = {}
    per_channel: dict[str, list[int]] = {}
    for entry in entries:
        _bump(totals, entry.decision)
        cand = by_id.get(entry.video_id)
        if cand is None:
            continue
        count = per_channel.setdefault(cand.channel_name, [0, 0])
        count[0 if entry.decision in ("watched", "listened") else 1] += 1
        if entry.decision == "skipped" and cand.duration_sec is not None:
            _bump(bands, _duration_band(cand.duration_sec))
    channels = [(name, count[0], count[1]) for name, count in sorted(per_channel.items())]
    return FeedbackStats(totals, bands, channels)


def _fmt_duration(sec: int | None) -> str:
    if sec is None:
        return "duration unknown"
    hours, rem = divmod(sec, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"


def _fmt_views(views: int | None) -> str:
    if views is None:
        return "no view count"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M views"
    if views >= 1_000:
        return f"{views / 1_000:.0f}K views"
    return f"{views} views"


def _fmt_date(published: str | None) -> str:
    return published or "date unknown"


def _candidate_lines(candidates: list[Candidate]) -> list[str]:
    lines: list[str] = []
    for idx, cand in enumerate(candidates, start=1):
        lines.append(
            f"[{idx}] {cand.title} - {cand.channel_name} "
            f"({_fmt_duration(cand.duration_sec)}, {_fmt_views(cand.views)}, {_fmt_date(cand.published)})"
        )
    return lines


def _candidates_section(candidates: list[Candidate]) -> list[str]:
    lines = [f"=== Candidates ({len(candidates)}) ===", *_candidate_lines(candidates)]
    if candidates:
        lines.append("Candidate IDs: " + ", ".join(cand.video_id for cand in candidates))
    else:
        lines.append("Candidate IDs: (none)")
    return lines


def _taste_lines(taste: TasteProfile | None) -> list[str]:
    lines = ["=== Taste profile ==="]
    if taste is None or not taste.topics:
        lines.append("No taste profile yet")
        lines.append("Starter template:")
        lines.append(TASTE_STARTER)
        lines.append("Save your own profile with the save_taste_profile tool.")
        return lines
    lines.append(taste.text.strip())
    return lines


def _stats_lines(stats: FeedbackStats) -> list[str]:
    lines = ["=== Feedback stats ==="]
    if not stats.totals:
        lines.append("no feedback rows yet")
        return lines
    lines.append("totals: " + " ".join(f"{key}={n}" for key, n in sorted(stats.totals.items())))
    if stats.skips_by_duration_band:
        bands = ", ".join(f"{band}={n}" for band, n in sorted(stats.skips_by_duration_band.items()))
        lines.append(f"skips by duration: {bands}")
    if stats.channel_counts:
        channels = " | ".join(f"{name} (watch/listen {w}, skip {s})" for name, w, s in stats.channel_counts)
        lines.append(f"channels: {channels}")
    return lines


def _sources_lines(source_counts: dict[str, int]) -> list[str]:
    lines = ["=== Sources ==="]
    if not source_counts:
        lines.append("(none)")
        return lines
    lines.append(", ".join(f"{name}={count}" for name, count in sorted(source_counts.items())))
    return lines


def _with_notes(payload: str, notes: list[str]) -> str:
    if not notes:
        return payload
    return payload + "\n=== Source notes ===\n" + "\n".join(notes)


def _candidates_payload(candidates: list[Candidate], notes: list[str]) -> str:
    return _with_notes("\n".join(_candidates_section(candidates)), notes)


def render_digest(
    candidates: list[Candidate], taste: TasteProfile | None, stats: FeedbackStats, source_counts: dict[str, int]
) -> str:
    lines: list[str] = ["YouTube digest", ""]
    lines += _taste_lines(taste)
    lines += _stats_lines(stats)
    lines += _sources_lines(source_counts)
    lines += _candidates_section(candidates)
    return "\n".join(lines)


_VTT_CUE_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.\d+\s*-->")


def _vtt_cue_start(line: str) -> int | None:
    match = _VTT_CUE_RE.match(line)
    if match is None:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_vtt(text: str) -> list[tuple[int, str]]:
    """WEBVTT caption text -> (start_seconds, line) per caption line.

    WEBVTT header, blank, and cue-index lines are skipped; cue times
    (e.g. 00:00:05.120) are truncated to integer seconds.
    """
    segments: list[tuple[int, str]] = []
    start: int | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        cue = _vtt_cue_start(line)
        if cue is not None:
            start = cue
            continue
        if start is not None and line and not line.isdigit():
            segments.append((start, line))
    return segments


def assemble_podcast_text(title: str, channel: str, segments: list[tuple[int, str]]) -> str:
    lines = [f"=== Podcast transcript: {title} — {channel} ==="]
    kept = 0
    last = ""
    for start, text in segments:
        if text == last:
            continue
        if kept >= PODCAST_MAX_LINES:
            lines.append(f"... (truncated at {PODCAST_MAX_LINES} lines)")
            break
        lines.append(f"[{start // 60}:{start % 60:02d}] {text}")
        last = text
        kept += 1
    return "\n".join(lines)


def _failure_reason(err: Exception) -> str:
    if isinstance(err, ReauthNeeded):
        return "reauth"
    reason = classify_feed_error(err)
    status = _http_status(err)
    return f"{reason} HTTP {status}: {_http_message(err)}" if status is not None else reason


def _reauth_block(notes: list[str], reauth_reasons: set[str]) -> str:
    lines = ["REAUTH_NEEDED", *notes]
    if "reauth" in reauth_reasons:
        lines.append("Fix: run start_auth, open the URL, then finish_auth with the new code.")
    return "\n".join(lines)


def _fetch_gated(
    source: str, fetch: Callable[[], list[Candidate]], notes: list[str], reauth_reasons: set[str]
) -> list[Candidate] | None:
    """Fetch one OAuth-gated source; isolate failures as notes + reauth reasons (None = failed)."""
    try:
        return fetch()
    except Exception as err:
        reason = _failure_reason(err)
        notes.append(f"{source} failed: {reason}")
        if reason in REAUTH_CLASSES:
            reauth_reasons.add(reason)
        return None


def _oauth_set(valves) -> bool:
    return all(getattr(valves, name) for name in GOOGLE_FIELDS)


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


def _resolve_api_method(service, path: str):
    """Walk `path` on the API service, dereferencing 2.200 `__is_resource__` bound-method nodes.

    In googleapiclient 2.200 a nested collection is a bound method whose `__is_resource__`
    IS the bool `True`; calling it returns the underlying Resource. A genuinely missing
    segment surfaces as AttributeError (a local bug, kept visible — never mislabelled).
    `is True` (identity, NOT truthiness): a bare MagicMock's auto-attr `__is_resource__`
    is a truthy MagicMock (not `True`) → takes the false branch → seam stays unchanged.
    """
    resource = service
    for part in path.split("."):
        attr = getattr(resource, part)
        if getattr(attr, "__is_resource__", False) is True:
            attr = attr()  # 2.200: nested resource is a bound method; call it to reach the Resource
        resource = attr
    return resource


def _data_api_request(valves, method: str, params: dict) -> dict:
    token = _oauth_token(valves)
    service = discovery.build(
        "youtube",
        DATA_API_VERSION,
        http=_authed_http(token["access_token"]),
        cache_discovery=False,
    )
    try:
        api_method = _resolve_api_method(service, method)
        result = api_method(**params).execute()
    except HttpError as err:
        mapped = _map_api_error(err)
        if mapped:
            raise mapped from err
        raise
    return json.loads(result) if isinstance(result, (bytes, str)) else result


def _ytdlp_extract(url: str, extra: dict | None = None) -> dict:
    opts = cast("Any", {"skip_download": True, "quiet": True, "no_warnings": True, **(extra or {})})
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


def _read_doc(store, title: str) -> str | None:
    try:
        return store.read(title)
    except Exception:
        return None


def _token_status(valves) -> str | None:
    try:
        _oauth_token(valves)
    except ReauthNeeded:
        return "google token: INVALID - stored refresh token is stale; run start_auth then finish_auth"
    except Exception:
        return "google token: CHECK FAILED - token endpoint unreachable"
    return None


def _subtitle_extra(tmp: str, language: str) -> dict:
    return {
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": [language],
        "skip_download": True,
        "outtmpl": f"{tmp}/sub.%(ext)s",
    }


def _vtt_segments(info: dict, tmp: str, language: str) -> list[tuple[int, str]] | None:
    """(start, text) segments from a yt-dlp subtitle result, or None when no VTT is readable."""
    subtitles = info.get("requested_subtitles") or {}
    entry = subtitles.get(language) or {}
    path = entry.get("filepath")
    if path is None:
        matches = sorted(Path(tmp).glob("*.vtt"))
        path = str(matches[0]) if matches else None
    if path is None:
        return None
    try:
        return parse_vtt(Path(path).read_text())
    except OSError:
        return None


def _video_meta(info: dict | None, video_id: str) -> tuple[str, str]:
    if info is None:
        return video_id, "unknown"
    title = info.get("title") or video_id
    channel = info.get("uploader") or info.get("channel") or "unknown"
    return title, channel


def _try_primary(video_id: str, language: str, tmp: str) -> tuple[dict | None, str | None]:
    """(info, primary failure reason) from yt-dlp subtitle extraction. No reauth path (decision 3): a primary failure just falls through to the fallback."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        return _ytdlp_extract(url, extra=_subtitle_extra(tmp, language)), None
    except Exception as err:
        return None, str(err) or err.__class__.__name__


def _fallback_transcript(video_id: str) -> tuple[list[tuple[int, str]], str | None]:
    """Fallback (youtube-transcript-api) segments and failure reason (None on success)."""
    try:
        return _fetch_transcript_fallback(video_id), None
    except Exception as err:
        return [], str(err) or err.__class__.__name__


def _resolve_transcript(video_id: str, primary_reason: str, title: str, channel: str) -> str:
    segments, reason = _fallback_transcript(video_id)
    if not segments and reason is None:
        reason = "no transcript returned"
    if segments:
        return assemble_podcast_text(title, channel, segments)
    return f"Error: no transcript available for {video_id}: primary: {primary_reason}; fallback: {reason}"


def _feedback_doc(entries: list[FeedbackEntry]) -> str:
    return "\n".join([FEEDBACK_HEADER, *(serialize_feedback_line(entry) for entry in entries)]) + "\n"


def _feedback_reason(rows: list[FeedbackEntry], video_id: str, added_at: str) -> str | None:
    for row in reversed(rows):
        if row.video_id == video_id and row.date >= added_at:
            return f"{row.decision} {row.date}"
    return None


def _age_reason(added_at: str, max_age_days: int, today: date) -> str | None:
    age = (today - date.fromisoformat(added_at)).days
    if age > max_age_days:
        return f"older than digest_max_age_days ({age} days)"
    return None


def _removal_reason(
    item: PruneItem, rank: int, rows: list[FeedbackEntry], max_items: int, max_age_days: int, today: date
) -> str | None:
    feedback = _feedback_reason(rows, item.video_id, item.added_at)
    if feedback:
        return feedback
    if rank > max_items:
        return f"over digest_max_items (newest {max_items} kept)"
    return _age_reason(item.added_at, max_age_days, today)


def _removal_plan(
    items: list[PruneItem], rows: list[FeedbackEntry], max_items: int, max_age_days: int
) -> list[tuple[PruneItem, str]]:
    today = datetime.now().date()
    ranked = sorted(items, key=lambda item: item.added_at, reverse=True)
    planned: list[tuple[PruneItem, str]] = []
    for rank, item in enumerate(ranked, start=1):
        reason = _removal_reason(item, rank, rows, max_items, max_age_days, today)
        if reason:
            planned.append((item, reason))
    return planned


def _prune_report(removed: list[tuple[PruneItem, str]], kept: int, failure: Exception | None, notes: list[str]) -> str:
    if failure is not None:
        lines = [f"{_failure_label(failure)}: {failure}", f"partial: {len(removed)} item(s) removed before failure"]
    elif removed:
        lines = [f"OK — pruned {len(removed)} item(s)"]
        lines += [f"- {item.video_id} — {item.title or '?'}: {reason}" for item, reason in removed]
    else:
        lines = [f"OK — nothing to prune ({kept} tracked item(s) kept)"]
    lines.extend(notes)
    return "\n".join(lines)


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        # google oauth (the only credential set - no YouTube session)
        google_client_id: str = Field(
            default="", description="Google OAuth client ID (installed-app, Production-mode client)"
        )
        google_client_secret: str = Field(default="", description="Google OAuth client secret")
        google_refresh_token: str = Field(
            default="", description="Stored OAuth refresh token (scope: https://www.googleapis.com/auth/youtube)"
        )
        # digest playlist policy
        digest_playlist_title: str = Field(
            default="Open WebUI Digest",
            description="Title of the managed custom digest playlist (resolved by exact title match; created if absent; id cached in digest-state). The default Watch Later is never touched.",
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
        token_line = _token_status(valves) if google_ok else None
        if token_line:
            lines.append(token_line)
        ready = google_ok and token_line is None
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
            "Authorization code exchanged. Store the refresh token in the valve:\n"
            f'  Valves.google_refresh_token = "{token["refresh_token"]}"'
        )

    def _video_details(self, video_ids: list[str]) -> dict[str, dict]:
        details: dict[str, dict] = {}
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start : start + 50]
            resp = _data_api_request(
                self.valves, "videos.list", {"part": "snippet,contentDetails", "ids": ",".join(chunk)}
            )
            for item in resp.get("items") or []:
                details[item["id"]] = item
        return details

    def _fetch_watch_later(self, max_per_source: int) -> list[Candidate]:
        channel = _data_api_request(self.valves, "channels.list", {"part": "contentDetails", "mine": "true"})
        item = (channel.get("items") or [{}])[0]
        playlist_id = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("watchLater")
        if not playlist_id:
            return []
        resp = _data_api_request(
            self.valves,
            "playlistItems.list",
            {"part": "contentDetails", "playlistId": playlist_id, "maxResults": str(max_per_source)},
        )
        video_ids: list[str] = []
        for it in resp.get("items") or []:
            vid = (it.get("contentDetails") or {}).get("videoId")
            if vid:
                video_ids.append(vid)
        details = self._video_details(video_ids)
        return candidates_from_api([details[vid] for vid in video_ids if vid in details], "watch_later")

    def _list_subscription_channels(self) -> list[dict]:
        channels: list[dict] = []
        page_token: str | None = None
        while len(channels) < SUBSCRIPTION_CHANNEL_CAP:
            params: dict[str, object] = {"part": "snippet", "mine": "true", "maxResults": 50}
            if page_token:
                params["pageToken"] = page_token
            resp = _data_api_request(self.valves, "subscriptions.list", params)
            channels.extend(resp.get("items") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        channels.sort(key=lambda item: ((item.get("snippet") or {}).get("publishedAt")) or "", reverse=True)
        return channels[:SUBSCRIPTION_CHANNEL_CAP]

    def _fetch_subscriptions(self, max_per_source: int, notes: list[str]) -> list[Candidate]:
        try:
            channels = self._list_subscription_channels()
        except HttpError as err:
            if _http_status(err) != 404:
                raise
            notes.append(f"subscriptions list failed: {_failure_reason(err)}")
            return []
        entries: list[dict] = []
        for channel in channels:
            self._collect_channel(channel, entries, notes)
        entries.sort(key=lambda entry: entry["published"] or "", reverse=True)
        return candidates_from_rss(entries[:max_per_source], "subscriptions")

    def _collect_channel(self, channel: dict, entries: list[dict], notes: list[str]) -> None:
        snippet = channel.get("snippet") or {}
        channel_id = snippet.get("channelId") or ""
        name = snippet.get("channelTitle") or channel_id
        try:
            parsed = _parse_rss(_fetch_rss(_rss_url(channel_id)))
        except Exception as err:  # per-channel isolation: one bad RSS feed must not sink the rest
            notes.append(f"subscriptions channel {name} failed: {_failure_reason(err)}")
            return
        for entry in parsed:
            entry["channel_id"] = channel_id
            entries.append(entry)

    def _gather_one(self, source: str, max_per_source: int, search_query: str, notes: list[str]) -> list[Candidate]:
        if source == "watch_later":
            if not _oauth_set(self.valves):
                notes.append("watch_later skipped: OAuth not configured")
                return []
            return self._fetch_watch_later(max_per_source)
        if source == "subscriptions":
            if not _oauth_set(self.valves):
                notes.append("subscriptions skipped: OAuth not configured")
                return []
            return self._fetch_subscriptions(max_per_source, notes)
        entries = _ytdlp_extract(f"ytsearch{max_per_source}:{search_query}").get("entries") or []
        return candidates_from_ytdlp(entries, "search")

    async def gather_candidates(
        self, sources: str = "search", max_per_source: int = MAX_PER_SOURCE, search_query: str = ""
    ) -> str:
        """Gather candidate videos from the given sources (comma-separated: watch_later, subscriptions, search).

        search_query is required only for the search source. watch_later and subscriptions use the
        existing Google OAuth valves and are skipped with a note when OAuth is not configured.
        """
        parsed = parse_sources_arg(sources)
        if parsed is None:
            return f"Error: unknown source name(s) in {sources!r} - valid sources: {', '.join(SOURCES)}"
        if "search" in parsed and not search_query.strip():
            return "Error: search needs search_query (e.g. search_query='rust async')"
        notes: list[str] = []
        batches = [self._gather_one(source, max_per_source, search_query, notes) for source in parsed]
        return _candidates_payload(merge_candidates(batches), notes)

    def _digest_sources(self, taste: TasteProfile) -> tuple[list[list[Candidate]], dict[str, int], list[str], set[str]]:
        """Per-topic search + watch_later + subscriptions: (batches, pre-merge source counts, notes, reauth reasons)."""
        notes: list[str] = []
        reauth_reasons: set[str] = set()
        source_counts: dict[str, int] = {}
        batches = [_topic_batch(topic, source_counts, notes) for topic in taste.topics]
        if _oauth_set(self.valves):
            gated = (
                ("watch_later", lambda: self._fetch_watch_later(MAX_PER_SOURCE)),
                ("subscriptions", lambda: self._fetch_subscriptions(MAX_PER_SOURCE, notes)),
            )
            for source, fetch in gated:
                candidates = _fetch_gated(source, fetch, notes, reauth_reasons)
                if candidates is not None:
                    batches.append(candidates)
                    source_counts[source] = len(candidates)
        return batches, source_counts, notes, reauth_reasons

    async def digest(self) -> str:
        store = _state_store(None)
        taste = parse_taste_profile(_read_doc(store, NOTE_TASTE))
        rows = parse_feedback_log(_read_doc(store, NOTE_FEEDBACK) or "")
        batches, source_counts, notes, reauth_reasons = self._digest_sources(taste)
        merged = merge_candidates(batches)
        kept, _ = filter_disliked(merged, taste.disliked)
        stats = aggregate_feedback(rows, kept)
        payload = render_digest(kept, taste, stats, source_counts)
        if reauth_reasons:
            return _reauth_block(notes, reauth_reasons)
        return _with_notes(payload, notes)

    async def save_taste_profile(self, md: str) -> str:
        try:
            _state_store(None).write(NOTE_TASTE, md)
        except Exception as err:
            return f"Error: {err}"
        return "OK"

    async def transcript(self, video_id: str, language: str = "en") -> str:
        """Podcast-format transcript: yt-dlp subtitles primary, youtube-transcript-api fallback."""
        tmp = tempfile.mkdtemp(prefix="ytm-sub-")
        try:
            return self._transcript_core(video_id, language, tmp)
        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(tmp)

    def _transcript_core(self, video_id: str, language: str, tmp: str) -> str:
        info, primary_reason = _try_primary(video_id, language, tmp)
        title, channel = _video_meta(info, video_id)
        segments = _vtt_segments(info, tmp, language) if info is not None else None
        if segments:
            return assemble_podcast_text(title, channel, segments)
        if primary_reason is None:
            primary_reason = "no captions found"
        return _resolve_transcript(video_id, primary_reason, title, channel)

    async def add_to_playlist(self, video_id: str) -> str:
        """Idempotent add to the custom digest playlist (resolve-or-create by title), record tool-added items in digest-state."""
        if not self.valves.digest_playlist_title.strip():
            return "Error: set the digest_playlist_title valve first"
        if not video_id:
            return "Error: video_id is required"
        try:
            return self._add_to_playlist_core(video_id)
        except ReauthNeeded as err:
            return f"REAUTH_NEEDED\n{err}\nFix: run start_auth, open the URL, then finish_auth with the new code."
        except Exception as err:
            return f"{_failure_label(err)}: {err}"

    def _add_to_playlist_core(self, video_id: str) -> str:
        notes: list[str] = []
        store = _state_store(None)
        state = parse_digest_state(_read_doc(store, NOTE_STATE) or "")
        playlist_id, _created = self._resolve_digest_playlist(store, state, notes)
        if video_id in self._playlist_video_ids(playlist_id):
            return self._present_message(video_id, state)
        title = self._insert_into_playlist(playlist_id, video_id)
        self._record_tool_added(store, state, video_id, title, notes)
        return "\n".join(
            [f'OK — added {title or video_id} to "{self.valves.digest_playlist_title}" ({playlist_id})', *notes]
        )

    def _resolve_digest_playlist(self, store, state: dict, notes: list[str]) -> tuple[str, bool]:
        """Digest playlist id: cached in digest-state, else exact-title match, else create. Returns (id, created)."""
        title = self.valves.digest_playlist_title
        cached = state.get("playlist_id") or ""
        if cached:
            return cached, False
        playlist_id = self._find_playlist_by_title(title)
        if not playlist_id:
            playlist_id = self._create_digest_playlist(title)
        state["playlist_id"] = playlist_id
        self._persist_state(store, state, notes)
        return playlist_id, True

    def _find_playlist_by_title(self, title: str) -> str | None:
        token = ""
        while True:
            params: dict = {"part": "snippet", "mine": True, "maxResults": 100}
            if token:
                params["pageToken"] = token
            resp = _data_api_request(self.valves, "playlists.list", params)
            for item in resp.get("items") or []:
                if (item.get("snippet") or {}).get("title") == title:
                    return item.get("id") or None
            token = resp.get("nextPageToken") or ""
            if not token:
                return None

    def _create_digest_playlist(self, title: str) -> str:
        body = {"snippet": {"title": title}}
        resp = _data_api_request(self.valves, "playlists.insert", {"part": "snippet", "body": body})
        return (resp or {}).get("id") or ""

    def _playlist_video_ids(self, playlist_id: str) -> list[str]:
        video_ids: list[str] = []
        token = ""
        while True:
            params: dict = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 5000}
            if token:
                params["pageToken"] = token
            resp = _data_api_request(self.valves, "playlistItems.list", params)
            video_ids.extend(self._item_video_ids(resp))
            token = resp.get("nextPageToken") or ""
            if not token:
                break
        return video_ids

    @staticmethod
    def _item_video_ids(resp: dict) -> list[str]:
        video_ids: list[str] = []
        for item in resp.get("items") or []:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        return video_ids

    def _present_message(self, video_id: str, state: dict) -> str:
        tracked = video_id in (state.get("tool_added") or {})
        suffix = "tracked; no change" if tracked else "not tool-managed; left untracked"
        return f'OK — {video_id} already in "{self.valves.digest_playlist_title}" ({suffix})'

    def _insert_into_playlist(self, playlist_id: str, video_id: str) -> str:
        body = {"snippet": {"playlistId": playlist_id, "resourceId": {"videoId": video_id}}}
        resp = _data_api_request(self.valves, "playlistItems.insert", {"part": "snippet", "body": body})
        snippet = (resp or {}).get("snippet") or {}
        return snippet.get("title") or ""

    def _record_tool_added(self, store, state: dict, video_id: str, title: str, notes: list[str]) -> None:
        state.setdefault("tool_added", {})[video_id] = {
            "added_at": datetime.now().date().isoformat(),
            "title": title,
        }
        self._persist_state(store, state, notes)

    def _persist_state(self, store, state: dict, notes: list[str]) -> bool:
        try:
            store.write(NOTE_STATE, serialize_digest_state(state))
        except Exception as err:
            message = f"state record failed: {err}"
            if message not in notes:
                notes.append(message)
            return False
        return True

    async def record_feedback(self, video_id: str, decision: str, reason: str = "") -> str:
        """Append a validated feedback row to the feedback-log document."""
        if decision not in DECISIONS:
            return "Error: decision must be one of: watched, listened, skipped"
        if not video_id:
            return "Error: video_id is required"
        entry = FeedbackEntry(
            date=datetime.now().date().isoformat(),
            video_id=video_id,
            decision=decision,
            title="",
            source="digest",
            reason=reason,
        )
        store = _state_store(None)
        prior = parse_feedback_log(_read_doc(store, NOTE_FEEDBACK) or "")
        try:
            store.write(NOTE_FEEDBACK, _feedback_doc([*prior, entry]))
        except Exception as err:
            return f"Error: state record failed: {err}"
        return f"OK — recorded {decision} for {video_id}"

    async def prune_playlist(self) -> str:
        """Remove policy-stale tool-added items from the custom digest playlist and report the removals."""
        if not self.valves.digest_playlist_title.strip():
            return "Error: set the digest_playlist_title valve first"
        try:
            return self._prune_core()
        except ReauthNeeded as err:
            return f"REAUTH_NEEDED\n{err}\nFix: run start_auth, open the URL, then finish_auth with the new code."
        except Exception as err:
            return f"{_failure_label(err)}: {err}"

    def _prune_core(self) -> str:
        store = _state_store(None)
        state = parse_digest_state(_read_doc(store, NOTE_STATE) or "")
        tool_added = state.get("tool_added") or {}
        if not tool_added:
            return "OK — nothing to prune (no tracked items)"
        rows = parse_feedback_log(_read_doc(store, NOTE_FEEDBACK) or "")
        playlist_id = state.get("playlist_id") or ""
        if not playlist_id:
            return "Error: no resolved playlist id in digest-state (run add_to_playlist first)"
        listed = self._listed_items(playlist_id, tool_added)
        stale = len(tool_added) - len({item.video_id for item in listed})
        plan = _removal_plan(listed, rows, self.valves.digest_max_items, self.valves.digest_max_age_days)
        removed, failure = self._delete_planned(plan)
        notes: list[str] = []
        if removed or stale:
            self._write_pruned_state(store, state, listed, removed, stale, notes)
        kept = len(tool_added) - stale - len(removed)
        return _prune_report(removed, kept, failure, notes)

    def _listed_items(self, playlist_id: str, tool_added: dict) -> list[PruneItem]:
        items: list[PruneItem] = []
        for raw in self._playlist_items(playlist_id):
            video_id = (raw.get("contentDetails") or {}).get("videoId") or ""
            entry = tool_added.get(video_id)
            if entry is None:
                continue
            title = entry.get("title") or (raw.get("snippet") or {}).get("title") or ""
            items.append(PruneItem(raw.get("id", ""), video_id, title, entry.get("added_at", "")))
        return items

    def _playlist_items(self, playlist_id: str) -> list[dict]:
        items: list[dict] = []
        token = ""
        while True:
            params: dict = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 5000}
            if token:
                params["pageToken"] = token
            resp = _data_api_request(self.valves, "playlistItems.list", params)
            items.extend(resp.get("items") or [])
            token = resp.get("nextPageToken") or ""
            if not token:
                break
        return items

    def _delete_planned(
        self, plan: list[tuple[PruneItem, str]]
    ) -> tuple[list[tuple[PruneItem, str]], Exception | None]:
        removed: list[tuple[PruneItem, str]] = []
        for item, reason in plan:
            try:
                _data_api_request(self.valves, "playlistItems.delete", {"id": item.item_id})
            except ReauthNeeded:
                raise
            except Exception as err:
                return removed, err
            removed.append((item, reason))
        return removed, None

    def _write_pruned_state(
        self,
        store,
        state: dict,
        listed: list[PruneItem],
        removed: list[tuple[PruneItem, str]],
        stale: int,
        notes: list[str],
    ) -> None:
        tool_added = state.get("tool_added") or {}
        removed_ids = {item.video_id for item, _ in removed}
        kept = {item.video_id: tool_added[item.video_id] for item in listed if item.video_id not in removed_ids}
        if self._persist_state(store, {**state, "tool_added": kept}, notes) and stale:
            unit = "entry" if stale == 1 else "entries"
            notes.append(f"state cleaned: {stale} stale {unit} removed")
