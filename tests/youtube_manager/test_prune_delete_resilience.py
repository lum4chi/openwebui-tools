"""T0-2 (R2-B3): prune_playlist treats an empty/non-JSON playlistItems.delete body as applied (first call succeeds)."""

from datetime import datetime, timedelta

from youtube_manager import NOTE_STATE, parse_digest_state

from .conftest import DIGEST_PLAYLIST_ID, item_row, seed_state

PL = DIGEST_PLAYLIST_ID


def days_ago(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


def _delete_api_fake(monkeypatch, items, delete_outcome):
    """Patch _data_api_execute: playlistItems.list -> one page of items; playlistItems.delete -> raw body (or raise)."""
    calls: list[tuple[str, dict]] = []

    def fake(valves, method, params):
        calls.append((method, dict(params)))
        if method == "playlistItems.list":
            return {"items": items}
        if method == "playlistItems.delete":
            if isinstance(delete_outcome, Exception):
                raise delete_outcome
            return delete_outcome
        raise AssertionError(f"unexpected API method {method}")

    monkeypatch.setattr("youtube_manager._data_api_execute", fake)
    return calls


def _seed_n_items(fake_store, n: int) -> list[dict]:
    """Seed n tool-added items (each older than the default 30-day cap) under PL; return their item rows."""
    entries = {f"vid{i:03d}": (days_ago(40 + i), f"Video {i}") for i in range(n)}
    seed_state(fake_store, entries, playlist_id=PL)
    return [item_row(f"pl{i:03d}", f"vid{i:03d}") for i in range(n)]


def _kept(fake_store) -> dict:
    return parse_digest_state(fake_store.docs[NOTE_STATE]).get("tool_added") or {}


class TestPruneDeleteResilience:
    """prune_playlist: lenient delete-body parsing (T0-2.1…T0-2.5)."""

    # @unit
    # Scenario: T0-2.1 first prune after fresh add_to_playlist succeeds on empty 200 delete body
    #   Given a playlist containing N tool-added items (fresh add_to_playlist)
    #   And the delete API call returns 200 with an empty body
    #   When prune_playlist runs for the first time
    #   Then it succeeds and reports N removed
    #   And the output does not contain "empty or non-JSON"
    async def test_empty_200_delete_body_succeeds(self, tools, monkeypatch, fake_store):
        items = _seed_n_items(fake_store, 3)
        _delete_api_fake(monkeypatch, items, b"")
        result = await tools.prune_playlist()
        assert result.startswith("OK — pruned 3 item(s)")
        assert "empty or non-JSON" not in result
        assert _kept(fake_store) == {}

    # @unit
    # Scenario: T0-2.2 valid JSON {} delete response keeps succeeding
    #   Given a playlist containing N tool-added items
    #   And the delete API call returns valid JSON {}
    #   When prune_playlist runs
    #   Then it succeeds and reports N removed
    async def test_valid_json_delete_body_succeeds(self, tools, monkeypatch, fake_store):
        items = _seed_n_items(fake_store, 3)
        _delete_api_fake(monkeypatch, items, b"{}")
        result = await tools.prune_playlist()
        assert result.startswith("OK — pruned 3 item(s)")
        assert "empty or non-JSON" not in result
        assert _kept(fake_store) == {}

    # @unit
    # Scenario: T0-2.3 invalid non-empty delete body treated as applied + raw body logged
    #   Given a playlist containing N tool-added items
    #   And the delete API call returns a non-empty non-JSON body
    #   When prune_playlist runs
    #   Then it succeeds and reports N removed (treated as applied)
    #   And a note line contains the raw body truncated to 80 chars
    async def test_non_json_delete_body_treated_as_applied(self, tools, monkeypatch, fake_store):
        items = _seed_n_items(fake_store, 3)
        _delete_api_fake(monkeypatch, items, b"garbage")
        result = await tools.prune_playlist()
        assert result.startswith("OK — pruned 3 item(s)")
        assert "note: non-JSON delete response body (treated as applied): garbage" in result
        assert _kept(fake_store) == {}

    # @unit
    # Scenario: T0-2.4 state coherence after first success
    #   Given a successful first prune_playlist (empty 200 delete body)
    #   When prune_playlist runs again immediately
    #   Then it reports nothing to prune (state file already written — no retry needed)
    async def test_state_coherence_after_first_success(self, tools, monkeypatch, fake_store):
        items = _seed_n_items(fake_store, 3)
        _delete_api_fake(monkeypatch, items, b"")
        first = await tools.prune_playlist()
        assert first.startswith("OK — pruned 3 item(s)")
        second = await tools.prune_playlist()
        assert second == "OK — nothing to prune (no tracked items)"

    # @unit
    # Scenario: T0-2.5 genuine API error still surfaces (regression)
    #   Given a playlist containing N tool-added items
    #   And the delete API call returns a googleapiclient error shape (e.g. 400 invalid request)
    #   When prune_playlist runs
    #   Then it reports the real error (not silent success)
    #   And the state file is not rewritten
    async def test_genuine_api_error_surfaces(self, tools, monkeypatch, fake_store):
        items = _seed_n_items(fake_store, 3)
        error = RuntimeError("playlistItems.delete: 400 invalid request")
        _delete_api_fake(monkeypatch, items, error)
        result = await tools.prune_playlist()
        assert result.startswith("Error:")
        assert "unexpected error" in result
        assert "partial: 0 item(s) removed before failure" in result
        assert len(_kept(fake_store)) == 3
