"""
title: YouTube Manager
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Personal YouTube digest - passes the user's taste profile verbatim and gathers candidates from the user's watch later and subscribed channels via the YouTube Data API; search is a separate explicit gather_candidates tool call. State is tracked in Open WebUI Notes.
requirements: google-api-python-client, google-auth, yt-dlp, youtube-transcript-api
version: 1.5.2
licence: MIT
required_open_webui_version: 0.5.0

Agent instructions:
  SETUP (this slice):
   1. check_setup — verify the Google OAuth set (live token check only when the set is complete)
  2. start_auth — print the Google consent URL for the youtube scope
   3. finish_auth — exchange the pasted code/redirect URL and store the refresh token to a local credential file (automatic; no manual storage)
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
from typing import Any, Literal, cast

import yt_dlp
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient import discovery
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field, TypeAdapter
from pydantic import dataclasses as pydantic_dataclasses
from yt_dlp.utils import DownloadError, ExtractorError

SCOPE = "https://www.googleapis.com/auth/youtube"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LOOPBACK_REDIRECT = "http://127.0.0.1:8085/oauth2callback"
NOTE_TASTE, NOTE_FEEDBACK, NOTE_STATE = "taste-profile", "feedback-log", "digest-state"
CREDENTIAL_TITLE = "google-refresh-token"
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


class _AllUnavailable(Exception):  # noqa: N818 - private internal signal, not a user-facing error type
    """All listed search results failed to resolve; carry the first cleaned reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


@pydantic_dataclasses.dataclass
class FeedbackEntry:
    date: str
    video_id: str
    decision: Literal["watched", "listened", "skipped"]
    title: str
    source: str
    reason: str

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        return TypeAdapter(cls).json_schema()


@dataclass
class FeedbackStats:
    totals: dict[str, int]
    skips_by_duration_band: dict[str, int]
    channel_counts: list[tuple[str, int, int]]


@dataclass
class TasteProfile:
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


def _http_status(err: BaseException) -> int | None:
    status = getattr(getattr(err, "resp", None), "status", None)
    if status is None:
        status = getattr(err, "code", None)
    return status if isinstance(status, int) else None


def _http_message(err: Exception) -> str:
    return str(getattr(getattr(err, "resp", None), "reason", None) or err)


def classify_feed_error(err: Exception) -> str:
    msg = str(err).lower()
    if "bot" in msg and "confirm" in msg:
        return "bot_check"
    if "quota" in msg:
        return "quota"
    if isinstance(err, urllib.error.HTTPError):
        return f"HTTP {err.code}: {err.reason}"
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


def _clean_http_error(exc: BaseException) -> str:
    status = _http_status(exc)
    if status == 404:
        return "not found - the resource no longer exists"
    if status == 429:
        return "rate limited - retry later"
    if status is not None and 500 <= status < 600:
        return "service unavailable - retry later"
    return "unexpected error"


_TRANSCRIPT_API_REASONS: dict[str, str] = {
    "NoTranscriptFound": "no transcript found",
    "TranscriptsDisabled": "transcripts disabled",
    "VideoUnavailable": "video unavailable",
    "TranscriptRetrievalFailed": "transcript retrieval failed",
    "CouldNotRetrieveTranscript": "transcript retrieval failed",
    "InvalidVideoId": "invalid video id",
}


def _clean_exception(exc: BaseException) -> str:
    if isinstance(exc, ReauthNeeded):
        return "reauthentication required"
    if isinstance(exc, QuotaError):
        return "quota reached"
    if isinstance(exc, HttpError):
        return _clean_http_error(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return _clean_http_error(exc)
    if isinstance(exc, (urllib.error.URLError, TimeoutError)):
        return "network error"
    if isinstance(exc, ValueError):
        return "invalid API response"
    if isinstance(exc, (ExtractorError, DownloadError)):
        return "transcript extraction failed"
    if isinstance(exc, TranscriptUnavailable):
        return "fallback dependency not installed"
    name = _TRANSCRIPT_API_REASONS.get(type(exc).__name__)
    return name if name is not None else "unexpected error"


def _valid_video_id(video_id: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]+", video_id) is not None


def _error_return(exc: BaseException, verbose: bool = False) -> str:
    reason = _clean_exception(exc)
    if verbose:
        return f"Error: {reason} (detail: {exc!r})"
    return f"Error: {reason}"


def _note_error(notes: list[str], exc: BaseException, verbose: bool = False) -> None:
    message = f"state record failed: {_clean_exception(exc)}"
    if message not in notes:
        notes.append(message)


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
        decision = cast(Literal["watched", "listened", "skipped"], cells[2])
        entries.append(FeedbackEntry(cells[0], cells[1], decision, cells[3], cells[4], cells[5]))
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


def _parse_rss(raw: bytes, drop_counts: dict[str, int] | None = None) -> list[dict]:
    entries: list[dict] = []
    raw_count = 0
    no_video_count = 0
    for elem in ET.fromstring(raw).iter():
        if _rss_local(elem) != "entry":
            continue
        entry = _rss_entry(elem)
        raw_count += 1
        if entry is None:
            no_video_count += 1
        else:
            entries.append(entry)
    if drop_counts is not None:
        drop_counts["raw_entries"] = drop_counts.get("raw_entries", 0) + raw_count
        drop_counts["no_video_id"] = drop_counts.get("no_video_id", 0) + no_video_count
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


def parse_taste_profile(md: str | None) -> TasteProfile:
    text = md or ""
    if not text.strip():
        return TasteProfile(set(), text)
    disliked = {bullet.lower() for bullet in _bullets_under(text, "## Avoid") or []}
    return TasteProfile(disliked, text)


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


def _latest_wins(entries: list[FeedbackEntry]) -> list[FeedbackEntry]:
    """Keep the newest-dated row per video_id; on a date tie, the later input row wins."""
    latest: dict[str, FeedbackEntry] = {}
    for entry in entries:
        prev = latest.get(entry.video_id)
        if prev is None or entry.date >= prev.date:
            latest[entry.video_id] = entry
    return list(latest.values())


def aggregate_feedback(entries: list[FeedbackEntry], candidates: list[Candidate]) -> FeedbackStats:
    by_id = {cand.video_id: cand for cand in candidates}
    totals: dict[str, int] = {}
    bands: dict[str, int] = {}
    per_channel: dict[str, list[int]] = {}
    for entry in _latest_wins(entries):
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
    if taste is None or not taste.text.strip():
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
    lines.append("feedback (latest wins): " + " ".join(f"{key}={n}" for key, n in sorted(stats.totals.items()) if n))
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
    if isinstance(err, urllib.error.HTTPError):
        return reason
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
    return (
        bool(valves.google_client_id) and bool(valves.google_client_secret) and bool(_effective_refresh_token(valves))
    )


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
            "refresh_token": _effective_refresh_token(valves),
            "client_id": valves.google_client_id,
            "client_secret": valves.google_client_secret,
        }
    request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        if err.code in (400, 401):
            msg = (
                "Google rejected the authorization code - no stored credential was involved; the pasted code was invalid or already used"
                if code
                else "Google rejected the grant - stored credential is stale"
            )
            raise ReauthNeeded(msg) from err
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


def _data_api_execute(valves, method: str, params: dict) -> bytes:
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
    return result


def _decode_api_response(raw: bytes | str) -> dict:
    if not isinstance(raw, (bytes, str)):
        return raw  # already-parsed payload (e.g. mock dict) — pass through untouched
    text = raw.decode() if isinstance(raw, bytes) else raw
    if not text.strip():
        raise ValueError("YouTube API returned an empty or non-JSON response (transient); retry the operation.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(
            "YouTube API returned an empty or non-JSON response (transient); retry the operation."
        ) from err


def _as_text(raw: bytes | str) -> str:
    """Decode a raw Data API body to text (bytes -> utf-8; str passthrough)."""
    return raw.decode() if isinstance(raw, bytes) else raw


def _parse_delete_response(raw: bytes | str) -> dict:
    """Lenient parse of a playlistItems.delete body: empty/invalid -> {} (treated as applied).

    Unlike the strict read-path ``_decode_api_response`` (which raises on an empty or
    non-JSON body), a delete is fire-and-forget: a 200 with no body, or a body that is
    not JSON, still means the item was removed server-side.
    """
    if not isinstance(raw, (bytes, str)):
        return raw  # already-parsed payload (e.g. mock dict) — pass through untouched
    text = _as_text(raw)
    if not text.strip():
        return {}  # 200-no-content: the normal success shape
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}  # invalid body: still applied


def _is_silent_delete(text: str) -> bool:
    """True when a delete body needs no note: empty (200-no-content) or valid JSON."""
    if not text.strip():
        return True
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _note_non_json_delete(raw: bytes | str, notes: list[str] | None) -> None:
    """Append one deduped note when a delete body is non-empty but not valid JSON."""
    if not isinstance(raw, (bytes, str)) or notes is None:
        return
    text = _as_text(raw)
    if _is_silent_delete(text):
        return
    msg = "note: non-JSON delete response body (treated as applied): " + text[:80]
    if msg not in notes:
        notes.append(msg)


def _data_api_request(valves, method: str, params: dict) -> dict:
    return _decode_api_response(_data_api_execute(valves, method, params))


def _ytdlp_extract(url: str, extra: dict | None = None) -> dict:
    opts = cast("Any", {"skip_download": True, "quiet": True, "no_warnings": True, **(extra or {})})
    ydl = yt_dlp.YoutubeDL(opts)
    return cast("dict", ydl.extract_info(url, download=False))


def _fetch_transcript_fallback(video_id: str) -> tuple[list[tuple[int, str]], str | None]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as err:
        raise TranscriptUnavailable("fallback dependency not installed") from err
    fetched = YouTubeTranscriptApi().fetch(video_id)
    segments = [(int(segment["start"]), segment["text"]) for segment in fetched.to_raw_data()]
    return segments, getattr(fetched, "language_code", None)


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

    def write(self, title: str, md: str, *, secret: bool = False) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"{title}.md"
        path.write_text(md)
        if secret:
            path.chmod(0o600)


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

    def write(self, title: str, md: str, *, secret: bool = False) -> None:
        _notes_http("POST", self.url, self.auth, {"title": title, "content": md})


def _state_store(request):
    if request is not None and request.headers.get("authorization"):
        auth = request.headers.get("authorization")
        base = (request.base_url or "http://localhost:3000/").rstrip("/")
        return _NotesStore(f"{base}/api/v1/studio/notes", auth)
    data_dir = Path(os.environ.get("DATA_DIR") or Path.cwd() / "data")
    return _FileStore(data_dir)


def _file_refresh_token() -> str | None:
    token = _read_doc(_state_store(None), CREDENTIAL_TITLE)
    return token.strip() if token else None


def _effective_refresh_token(valves) -> str:
    return _file_refresh_token() or valves.google_refresh_token


def _read_doc(store, title: str) -> str | None:
    try:
        return store.read(title)
    except Exception:
        return None


def _token_status(valves) -> str | None:
    try:
        _oauth_token(valves)
    except ReauthNeeded:
        return "INVALID - stored refresh token is stale; run start_auth then finish_auth"
    except Exception:
        return "CHECK FAILED - token endpoint unreachable"
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
        return None, _clean_exception(err)


def _fallback_transcript(video_id: str) -> tuple[list[tuple[int, str]], str | None, str | None]:
    """Fallback segments, failure reason (None on success), and language code (None when unavailable)."""
    try:
        segments, language_code = _fetch_transcript_fallback(video_id)
        return segments, None, language_code
    except Exception as err:
        return [], _clean_exception(err), None


def _primary_actual_language(info: dict | None, language: str) -> str:
    subtitles = (info or {}).get("requested_subtitles") or {}
    if (subtitles.get(language) or {}).get("filepath"):
        return language
    return next(iter(subtitles), None) or "unknown"


def _transcript_with_notice(text: str, language: str, used: str) -> str:
    if used == language:
        return text
    return f"Notice: transcript language fallback: requested {language}, used {used}\n{text}"


def _resolve_transcript(video_id: str, primary_reason: str, title: str, channel: str, language: str) -> str:
    segments, reason, language_code = _fallback_transcript(video_id)
    if not segments and reason is None:
        reason = "no transcript returned"
    if segments:
        return _transcript_with_notice(
            assemble_podcast_text(title, channel, segments),
            language,
            language_code or "unknown",
        )
    if primary_reason == "no captions found":
        return f"No captions found for {video_id}"
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
        lines = [
            f"Error: {_clean_exception(failure)}",
            f"partial: {len(removed)} item(s) removed before failure",
        ]
    elif removed:
        lines = [f"OK — pruned {len(removed)} item(s)"]
        lines += [f"- {item.video_id} — {item.title or '?'}: {reason}" for item, reason in removed]
    else:
        lines = [f"OK — nothing to prune ({kept} tracked item(s) kept)"]
    lines.extend(notes)
    return "\n".join(lines)


def _note_watch_later(notes: list[str] | None, reason: str) -> None:
    """Append a ``watch_later skipped: {reason}`` note (None-safe for the digest path)."""
    if notes is not None:
        notes.append(f"watch_later skipped: {reason}")


def _note_details_unavailable(notes: list[str] | None, video_ids: list[str], resolved: list[dict]) -> None:
    """Note when the playlist listed items but none resolved in the videos.list details."""
    if video_ids and not resolved:
        _note_watch_later(notes, "details unavailable")


def _subscription_zero_suffix(entries: list[dict], drop_counts: dict[str, int] | None = None) -> str:
    if entries:
        return "capped entries produced no candidates"
    counts = drop_counts or {}
    if counts.get("no_video_id", 0):
        return f"feeds returned {counts.get('raw_entries', counts['no_video_id'])} entry(s) with no usable video id"
    if counts.get("zero_entry_feeds", 0):
        return "feeds returned zero entries"
    return "feeds returned no usable entries"


def _subscription_headline(
    ok: int, failed: int, entries: list[dict], candidate_count: int, drop_counts: dict[str, int] | None = None
) -> str:
    """Headline for the subscriptions digest note, computed after the capped candidate count is known."""
    if ok == 0:
        return f"subscriptions: {ok} ok, {failed} failed"
    if candidate_count > 0:
        return f"subscriptions: {ok} ok, {failed} failed, {candidate_count} candidates"
    return f"subscriptions: {ok} ok, {failed} failed, 0 candidates ({_subscription_zero_suffix(entries, drop_counts)})"


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
        # source notes verbosity
        verbose: bool = Field(
            default=False, description="Include raw HTTP error detail in source notes (off by default)"
        )

    async def check_setup(self) -> str:
        oauth_ok = _oauth_set(self.valves)
        token_status = _token_status(self.valves) if oauth_ok else None
        if oauth_ok and token_status is None:
            subscriptions = "subscriptions: ok"
            watch_later = f"watch_later: {await self._watch_later_probe()}"
            overall = "READY" if watch_later.startswith("watch_later: ok") else "NOT READY"
        elif oauth_ok:
            subscriptions = f"subscriptions: {token_status}"
            watch_later = f"watch_later: {token_status}"
            overall = "NOT READY"
        else:
            subscriptions = "subscriptions: MISSING - OAuth fields incomplete"
            watch_later = "watch_later: MISSING - OAuth fields incomplete"
            overall = "NOT READY"
        return "\n".join(["search: ok", subscriptions, watch_later, overall])

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
            return _error_return(err, self.valves.verbose)
        try:
            _state_store(None).write(CREDENTIAL_TITLE, token["refresh_token"], secret=True)
        except Exception as err:
            return (
                f"Error: credential file write failed: {_clean_exception(err)}. "
                "The authorization code was exchanged, but the new refresh token was not stored. "
                "Run start_auth and finish_auth again."
            )
        return "OK - credential stored; check_setup should now show ok"

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

    def _fetch_watch_later(self, max_per_source: int, notes: list[str] | None = None) -> list[Candidate]:
        resp = _data_api_request(
            self.valves,
            "playlistItems.list",
            {"part": "contentDetails", "playlistId": "WL", "maxResults": str(max_per_source)},
        )
        video_ids: list[str] = []
        for it in resp.get("items") or []:
            vid = (it.get("contentDetails") or {}).get("videoId")
            if vid:
                video_ids.append(vid)
        details = self._video_details(video_ids)
        resolved = [details[vid] for vid in video_ids if vid in details]
        _note_details_unavailable(notes, video_ids, resolved)
        return candidates_from_api(resolved, "watch_later")

    async def _watch_later_probe(self) -> str:
        try:
            _data_api_request(
                self.valves,
                "playlistItems.list",
                {"part": "contentDetails", "playlistId": "WL", "maxResults": "1"},
            )
        except Exception as err:
            return f"CHECK FAILED - {_failure_reason(err)}"
        return "ok (playlist checked)"

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
        channels.sort(key=lambda item: (item.get("snippet") or {}).get("channelId") or "")
        channels.sort(key=lambda item: (item.get("snippet") or {}).get("publishedAt") or "", reverse=True)
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
        failures: dict[str, int] = {}
        ok = 0
        drop_counts: dict[str, int] = {}
        for channel in channels:
            reason = self._collect_channel(channel, entries, drop_counts)
            if reason is None:
                ok += 1
            else:
                failures[reason] = failures.get(reason, 0) + 1
        entries.sort(key=lambda entry: entry["published"] or "", reverse=True)
        capped_entries = entries[:max_per_source]
        candidate_count = len(candidates_from_rss(capped_entries, "subscriptions"))
        self._note_subscription_results(notes, ok, failures, entries, candidate_count, drop_counts)
        return candidates_from_rss(capped_entries, "subscriptions")

    def _note_subscription_results(
        self,
        notes: list[str],
        ok: int,
        failures: dict[str, int],
        entries: list[dict],
        candidate_count: int,
        drop_counts: dict[str, int] | None = None,
    ) -> None:
        notes.append(_subscription_headline(ok, sum(failures.values()), entries, candidate_count, drop_counts))
        if self.valves.verbose:
            for reason, count in failures.items():
                notes.append(f"{count} channel(s) failed: {reason}")

    def _collect_channel(
        self, channel: dict, entries: list[dict], drop_counts: dict[str, int] | None = None
    ) -> str | None:
        snippet = channel.get("snippet") or {}
        channel_id = snippet.get("channelId") or ""
        try:
            parsed = _parse_rss(_fetch_rss(_rss_url(channel_id)), drop_counts)
        except Exception as err:  # per-channel isolation: one bad RSS feed must not sink the rest
            return _failure_reason(err)
        if not parsed and drop_counts is not None:
            _bump(drop_counts, "zero_entry_feeds")
        for entry in parsed:
            entry["channel_id"] = channel_id
            entries.append(entry)
        return None

    @staticmethod
    def _resolve_search_videos(flat: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
        entries: list[dict] = []
        failures: list[tuple[str, str]] = []
        for entry in flat:
            video_id = entry.get("id")
            if not video_id:
                continue
            try:
                entries.append(_ytdlp_extract(f"https://www.youtube.com/watch?v={video_id}"))
            except Exception as err:
                failures.append((video_id, _failure_reason(err)))
        return entries, failures

    def _search_candidates(self, search_query: str, max_per_source: int, notes: list[str]) -> list[Candidate]:
        flat = (
            _ytdlp_extract(f"ytsearch{max_per_source}:{search_query}", extra={"extract_flat": "in_playlist"}).get(
                "entries"
            )
            or []
        )
        entries, failures = self._resolve_search_videos(flat)
        if not entries and failures:
            raise _AllUnavailable(failures[0][1])
        if failures:
            notes.append(f"skipped {len(failures)} unavailable: {', '.join(video_id for video_id, _ in failures)}")
        return candidates_from_ytdlp(entries, "search")

    def _gather_one(self, source: str, max_per_source: int, search_query: str, notes: list[str]) -> list[Candidate]:
        if source == "watch_later":
            if not _oauth_set(self.valves):
                notes.append("watch_later skipped: OAuth not configured")
                return []
            return self._fetch_watch_later(max_per_source, notes)
        if source == "subscriptions":
            if not _oauth_set(self.valves):
                notes.append("subscriptions skipped: OAuth not configured")
                return []
            return self._fetch_subscriptions(max_per_source, notes)
        return self._search_candidates(search_query, max_per_source, notes)

    def _gather_isolated(
        self,
        source: str,
        max_per_source: int,
        search_query: str,
        notes: list[str],
        reauth_reasons: set[str],
        failures: list[str],
    ) -> list[Candidate]:
        try:
            return self._gather_one(source, max_per_source, search_query, notes)
        except ReauthNeeded:
            reauth_reasons.add("reauth")
            notes.append(f"{source} failed: reauth")
        except _AllUnavailable as err:
            failures.append(err.reason)
            notes.append(f"search unavailable: {err.reason}")
        except Exception as err:
            reason = _failure_reason(err)
            failures.append(f"{source}: {reason}")
            notes.append(f"{source} failed: {reason}")
        return []

    @staticmethod
    def _compose_gather(
        merged: list[Candidate], notes: list[str], reauth_reasons: set[str], failures: list[str]
    ) -> str:
        if reauth_reasons and not merged:
            return _reauth_block(notes, reauth_reasons)
        if not merged and failures:
            return f"Error: {'; '.join(failures)}"
        return _candidates_payload(merged, notes)

    def _gather_all(self, parsed: list[str], max_per_source: int, search_query: str) -> str:
        notes: list[str] = []
        reauth_reasons: set[str] = set()
        failures: list[str] = []
        batches: list[list[Candidate]] = []
        for source in parsed:
            batch = self._gather_isolated(source, max_per_source, search_query, notes, reauth_reasons, failures)
            if batch:
                batches.append(batch)
        return self._compose_gather(merge_candidates(batches), notes, reauth_reasons, failures)

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
        return self._gather_all(parsed, max_per_source, search_query)

    def _digest_sources(self, taste: TasteProfile) -> tuple[list[list[Candidate]], dict[str, int], list[str], set[str]]:
        """Watch_later + subscriptions: (batches, pre-merge source counts, notes, reauth reasons)."""
        notes: list[str] = []
        reauth_reasons: set[str] = set()
        source_counts: dict[str, int] = {}
        batches: list[list[Candidate]] = []
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
        else:
            notes.append("watch_later skipped: OAuth not configured")
            notes.append("subscriptions skipped: OAuth not configured")
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
            return _reauth_block(notes, reauth_reasons) + "\n\n" + payload
        return _with_notes(payload, notes)

    async def save_taste_profile(self, md: str) -> str:
        if not (md or "").strip():
            return "Error: cannot save an empty taste profile"
        try:
            _state_store(None).write(NOTE_TASTE, md)
        except Exception as err:
            return _error_return(err, self.valves.verbose)
        first_line = next((line for line in md.splitlines() if line.strip()), "")[:80]
        return f'OK - saved taste profile: {len(md)} chars, {len(md.splitlines())} lines; first line: "{first_line}"'

    async def transcript(self, video_id: str, language: str = "en") -> str:
        """Podcast-format transcript: yt-dlp subtitles primary, youtube-transcript-api fallback."""
        if not _valid_video_id(video_id):
            return f"Error: invalid video_id: {video_id!r}"
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
            return _transcript_with_notice(
                assemble_podcast_text(title, channel, segments),
                language,
                _primary_actual_language(info, language),
            )
        if primary_reason is None:
            primary_reason = "no captions found"
        return _resolve_transcript(video_id, primary_reason, title, channel, language)

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
            return f"Error: {_clean_exception(err)}"

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
        body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
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
            _note_error(notes, err)
            return False
        return True

    async def record_feedback(
        self, video_id: str, decision: Literal["watched", "listened", "skipped"], reason: str = ""
    ) -> str:
        """Append a validated feedback row to the feedback-log document.

        decision must be one of: watched, listened, skipped.
        """
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
            return f"Error: state record failed: {_clean_exception(err)}"
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
            return f"Error: {_clean_exception(err)}"

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
        notes: list[str] = []
        removed, failure = self._delete_planned(plan, notes)
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
        self, plan: list[tuple[PruneItem, str]], notes: list[str] | None = None
    ) -> tuple[list[tuple[PruneItem, str]], Exception | None]:
        removed: list[tuple[PruneItem, str]] = []
        for item, reason in plan:
            try:
                raw = _data_api_execute(self.valves, "playlistItems.delete", {"id": item.item_id})
                _parse_delete_response(raw)
                _note_non_json_delete(raw, notes)
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
