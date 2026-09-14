"""Shared fixtures and helpers for youtube_manager tests."""

import pytest

from youtube_manager import NOTE_STATE, Candidate, Tools, serialize_digest_state


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """Tools with the Google credential set configured; DATA_DIR pointed at a temp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    t = Tools()
    t.valves.google_client_id = "client-id"
    t.valves.google_client_secret = "client-secret"
    t.valves.google_refresh_token = "refresh-token"
    return t


class FakeNotesApi:
    """In-memory Notes API: records calls, serves/records documents by title."""

    def __init__(self) -> None:
        self.docs: dict[str, str] = {}
        self.calls: list[tuple[str, str, str, dict | None]] = []

    def __call__(self, method: str, url: str, auth: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, auth, payload))
        if method == "GET":
            return {"notes": [{"title": t, "content": c} for t, c in self.docs.items()]}
        assert payload is not None
        self.docs[payload["title"]] = payload["content"]
        return {"status": "ok"}


@pytest.fixture
def fake_state(monkeypatch):
    """In-memory Notes API store patched in as youtube_manager._notes_http."""
    api = FakeNotesApi()
    monkeypatch.setattr("youtube_manager._notes_http", api)
    return api


def sample_feedback_log(rows: list[tuple]) -> str:
    """Build a feedback-log markdown document (contract header + data rows)."""
    lines = ["| date | video_id | decision | title | source | reason |"]
    for row in rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |")
    return "\n".join(lines) + "\n"


def sample_candidates(n: int) -> list[Candidate]:
    """Build n sample Candidate rows (digest/feedback consumers)."""
    return [
        Candidate(
            video_id=f"vid{i:03d}",
            title=f"Sample video {i}",
            channel_name=f"Channel {i % 3}",
            channel_id=f"ch{i % 3}",
            duration_sec=600 + i,
            views=1000 + i,
            published=f"2026-09-{(i % 28) + 1:02d}",
            description="",
            tags=[],
            sources=["search"],
        )
        for i in range(n)
    ]


def sample_taste_profile(topics: list[str], avoid: list[str]) -> str:
    """Build a taste-profile markdown document (## Topics / ## Avoid bullet lists)."""
    lines = ["# Taste profile", "", "## Topics"]
    lines += [f"- {t}" for t in topics]
    lines += ["", "## Avoid"]
    lines += [f"- {a}" for a in avoid]
    return "\n".join(lines) + "\n"


class FakeRequest:
    """Minimal request stand-in: headers dict + base_url (Open WebUI request shape)."""

    def __init__(self, headers: dict, base_url: str = "http://localhost:3000/"):
        self.headers = headers
        self.base_url = base_url


class FakeStateStore:
    """In-memory stand-in for a _state_store result (.read/.write by note title)."""

    def __init__(self, docs: dict[str, str] | None = None, raise_on_read: bool = False):
        self.docs = docs or {}
        self.raise_on_read = raise_on_read

    def read(self, title: str) -> str | None:
        if self.raise_on_read:
            raise RuntimeError("state store unreachable")
        return self.docs.get(title)

    def write(self, title: str, md: str) -> None:
        self.docs[title] = md


@pytest.fixture
def fake_store(monkeypatch):
    """Patch youtube_manager._state_store to a per-test in-memory FakeStateStore."""
    store = FakeStateStore()
    monkeypatch.setattr("youtube_manager._state_store", lambda request: store)
    return store


PLAYLIST_ID = "PL-WATCH-LATER"


def channels_reply() -> dict:
    """channels.list reply resolving the Watch Later playlist id."""
    return {"items": [{"contentDetails": {"relatedPlaylists": {"watchLater": PLAYLIST_ID}}}]}


def item_row(item_id: str, video_id: str, title: str = "") -> dict:
    """One playlistItems.list item row (snippet + contentDetails)."""
    return {"id": item_id, "snippet": {"title": title}, "contentDetails": {"videoId": video_id}}


def listing_page(rows: list[dict], token: str = "") -> dict:
    """A playlistItems.list page (optional nextPageToken)."""
    page: dict = {"items": rows}
    if token:
        page["nextPageToken"] = token
    return page


def seed_state(store, entries: dict[str, tuple[str, str]]) -> None:
    """Seed digest-state with tool_added entries: video_id -> (added_at, title)."""
    tool_added = {vid: {"added_at": added, "title": title} for vid, (added, title) in entries.items()}
    store.docs[NOTE_STATE] = serialize_digest_state({"tool_added": tool_added})


def api_fake(
    monkeypatch, channels: dict, pages: list[dict], deletes: list | None = None, raise_for: dict | None = None
):
    """Route _data_api_request by method; serve listing pages in order; record calls.

    ``deletes`` optionally feeds per-call playlistItems.delete outcomes in order
    (None = ok, an Exception instance = raise it); ``raise_for`` raises before dispatch.
    """
    calls: list[tuple[str, dict]] = []
    page_index = {"n": 0}
    delete_index = {"n": 0}

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if raise_for is not None and method in raise_for:
            raise raise_for[method]
        if method == "channels.list":
            return channels
        if method == "playlistItems.list":
            page = pages[page_index["n"]]
            page_index["n"] += 1
            return page
        if method == "playlistItems.delete":
            outcomes = deletes or []
            outcome = outcomes[delete_index["n"]] if delete_index["n"] < len(outcomes) else None
            delete_index["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return {}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr("youtube_manager._data_api_request", fake)
    return calls
