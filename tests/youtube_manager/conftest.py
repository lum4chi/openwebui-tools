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

    def __init__(self, docs: dict[str, str] | None = None, raise_on_read: bool = False, raise_on_write: bool = False):
        self.docs = docs or {}
        self.raise_on_read = raise_on_read
        self.raise_on_write = raise_on_write

    def read(self, title: str) -> str | None:
        if self.raise_on_read:
            raise RuntimeError("state store unreachable")
        return self.docs.get(title)

    def write(self, title: str, md: str) -> None:
        if self.raise_on_write:
            raise RuntimeError("state write failed")
        self.docs[title] = md


@pytest.fixture
def fake_store(monkeypatch):
    """Patch youtube_manager._state_store to a per-test in-memory FakeStateStore."""
    store = FakeStateStore()
    monkeypatch.setattr("youtube_manager._state_store", lambda request, user_id=None: store)
    return store


DIGEST_PLAYLIST_ID = "PL-DIGEST"


def channels_reply(watch_later_id: str) -> dict:
    """channels.list reply resolving the Watch Later playlist id (T4-12 scenario modeling only)."""
    return {"items": [{"contentDetails": {"relatedPlaylists": {"watchLater": watch_later_id}}}]}


def playlist_row(playlist_id: str, title: str) -> dict:
    """One playlists.list item row (id + snippet.title)."""
    return {"id": playlist_id, "snippet": {"title": title}}


def item_row(item_id: str, video_id: str, title: str = "") -> dict:
    """One playlistItems.list item row (snippet + contentDetails)."""
    return {"id": item_id, "snippet": {"title": title}, "contentDetails": {"videoId": video_id}}


def listing_page(rows: list[dict], token: str = "") -> dict:
    """A playlistItems.list page (optional nextPageToken)."""
    page: dict = {"items": rows}
    if token:
        page["nextPageToken"] = token
    return page


def seed_state(store, entries: dict[str, tuple[str, str]], playlist_id: str | None = None) -> None:
    """Seed digest-state: tool_added entries (video_id -> (added_at, title)) + optional cached playlist id.

    ``playlist_id=None`` omits the key entirely; ``""`` leaves it present but empty.
    """
    state: dict = {}
    if playlist_id is not None:
        state["playlist_id"] = playlist_id
    if entries:
        state["tool_added"] = {vid: {"added_at": added, "title": title} for vid, (added, title) in entries.items()}
    store.docs[NOTE_STATE] = serialize_digest_state(state)


def api_fake(
    monkeypatch,
    pages: dict[str, list[dict]],
    channels: dict | None = None,
    playlist_pages: list[dict] | None = None,
    create_reply: dict | None = None,
    insert_reply: dict | None = None,
    deletes: list | None = None,
    raise_for: dict | None = None,
    subscription_pages: list[dict] | None = None,
    channels_by_id: dict[str, dict] | None = None,
    videos: dict[str, dict] | None = None,
    raise_for_playlist: dict[str, Exception] | None = None,
):
    """Route _data_api_request by method; record every call as (method, params).

    ``pages`` maps playlist id -> ordered playlistItems.list pages; ``channels`` is the
    channels.list reply; ``playlist_pages`` serves playlists.list pages in order;
    ``create_reply``/``insert_reply`` are the playlists.insert / playlistItems.insert
    replies; ``deletes`` feeds per-call playlistItems.delete outcomes in order
    (None = ok, an Exception instance = raise it); ``raise_for`` raises before dispatch
    keyed by method name. ``subscription_pages`` serves subscriptions.list pages in order;
    ``channels_by_id`` serves per-id channels.list replies; ``videos`` serves videos.list
    rows; ``raise_for_playlist`` raises per playlistId before playlistItems.list dispatch.
    """
    calls: list[tuple[str, dict]] = []
    page_index: dict[str, int] = {}
    playlist_page_index = {"n": 0}
    delete_index = {"n": 0}
    subscription_page_index = {"n": 0}

    def fake(valves, method, params, user_id=None):
        calls.append((method, dict(params)))
        if raise_for is not None and method in raise_for:
            raise raise_for[method]
        if method == "channels.list":
            if channels_by_id is not None:
                return channels_by_id.get(params.get("id"), {"items": []})
            if channels is None:
                raise AssertionError("unexpected channels.list")
            return channels
        if method == "playlistItems.list":
            playlist_id = params.get("playlistId")
            if raise_for_playlist is not None and playlist_id in raise_for_playlist:
                raise raise_for_playlist[playlist_id]
            page_list = pages.get(playlist_id)
            if page_list is None:
                raise AssertionError(f"unseeded playlist {playlist_id!r}")
            n = page_index.get(playlist_id, 0)
            page_index[playlist_id] = n + 1
            return page_list[n]
        if method == "playlists.list":
            if not playlist_pages:
                raise AssertionError("unexpected playlists.list")
            n = playlist_page_index["n"]
            playlist_page_index["n"] = n + 1
            return playlist_pages[n]
        if method == "playlists.insert":
            if create_reply is None:
                raise AssertionError("unexpected playlists.insert")
            return create_reply
        if method == "playlistItems.insert":
            if insert_reply is None:
                raise AssertionError("unexpected playlistItems.insert")
            return insert_reply
        if method == "playlistItems.delete":
            outcomes = deletes or []
            outcome = outcomes[delete_index["n"]] if delete_index["n"] < len(outcomes) else None
            delete_index["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return {}
        if method == "subscriptions.list":
            if subscription_pages is None:
                raise AssertionError("unexpected subscriptions.list")
            n = subscription_page_index["n"]
            subscription_page_index["n"] = n + 1
            return subscription_pages[n] if n < len(subscription_pages) else {"items": []}
        if method == "videos.list":
            if videos is None:
                raise AssertionError("unexpected videos.list")
            ids = [vid for vid in str(params.get("ids", "")).split(",") if vid]
            return {"items": [videos[vid] for vid in ids if vid in videos]}
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr("youtube_manager._data_api_execute", fake)
    return calls


def guard_urlopen(monkeypatch) -> None:
    """Patch urllib.request.urlopen to fail if any code path tries real network I/O."""

    def blocked(*args, **kwargs):
        raise AssertionError("urllib.request.urlopen must not be called")

    monkeypatch.setattr("youtube_manager.urllib.request.urlopen", blocked)


def sub_channel(
    channel_id: str, title: str = "", published: str = "2026-01-01T00:00:00Z", own_channel_id: str | None = None
) -> dict:
    """One real-shape subscriptions.list item: the feed id lives in snippet.resourceId.channelId.

    The subscriber's own snippet.channelId defaults to the feed id; pass own_channel_id to model own != feed.
    """
    return {
        "id": channel_id,
        "snippet": {
            "channelId": own_channel_id or channel_id,
            "resourceId": {"channelId": channel_id},
            "title": title,
            "publishedAt": published,
        },
    }


def uploads_channel_reply(uploads: str) -> dict:
    """A channels.list reply whose item exposes the uploads playlist id."""
    return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": uploads}}}]}


def empty_channel_reply() -> dict:
    """A channels.list reply with no items (channel not found)."""
    return {"items": []}


def no_uploads_channel_reply() -> dict:
    """A channels.list reply whose item has no uploads playlist id."""
    return {"items": [{"contentDetails": {"relatedPlaylists": {}}}]}


def playlist_item(video_id: str, title: str, channel_title: str, published: str, description: str = "") -> dict:
    """One playlistItems.list item with a resolvable resourceId.videoId."""
    return {
        "snippet": {
            "resourceId": {"videoId": video_id},
            "title": title,
            "channelTitle": channel_title,
            "publishedAt": published,
            "description": description,
        }
    }


def idless_playlist_item(title: str = "No video id") -> dict:
    """One playlistItems.list item without a resolvable resourceId."""
    return {"snippet": {"title": title, "channelTitle": "No ID", "publishedAt": "2026-01-01T00:00:00Z"}}


def video_detail(video_id: str, duration: str | None = None, views: str | None = None, title: str | None = None):
    """One videos.list item; omit duration/views/title to exercise absent metadata."""
    return {
        "id": video_id,
        "snippet": {"title": title} if title is not None else {},
        "contentDetails": {"duration": duration} if duration is not None else {},
        "statistics": {"viewCount": views} if views is not None else {},
    }
