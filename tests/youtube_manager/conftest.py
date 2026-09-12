"""Shared fixtures and helpers for youtube_manager tests."""

import pytest

from youtube_manager import Candidate, Tools


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """Tools with both credential sets configured; DATA_DIR pointed at a temp dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    t = Tools()
    t.valves.google_client_id = "client-id"
    t.valves.google_client_secret = "client-secret"
    t.valves.google_refresh_token = "refresh-token"
    t.valves.ytdlp_cookies_file = str(tmp_path / "cookies.txt")
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
            sources=["recommended"],
        )
        for i in range(n)
    ]


class FakeRequest:
    """Minimal request stand-in: headers dict + base_url (Open WebUI request shape)."""

    def __init__(self, headers: dict, base_url: str = "http://localhost:3000/"):
        self.headers = headers
        self.base_url = base_url
