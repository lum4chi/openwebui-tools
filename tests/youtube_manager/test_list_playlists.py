"""T7-1 list_playlists(): public playlist enumeration (mine=true, all pages, maxResults 50)."""

import pytest

from youtube_manager import ReauthNeeded, Tools

from .conftest import api_fake

VIDEO_ID = "vid-list-001"
HEADER = "=== Playlists (mine=true) ==="
WL_ROW = 'Watch Later (WL) — alias "WL" (synthesized row; not a playlists.list result)'


def _row(playlist_id: str, title: str, privacy: str | None = None) -> dict:
    """One playlists.list item row (id + snippet.title + optional status.privacyStatus)."""
    row: dict = {"id": playlist_id, "snippet": {"title": title}}
    if privacy is not None:
        row["status"] = {"privacyStatus": privacy}
    return row


class TestListPlaylists:
    """list_playlists: one line per playlist (title, id, privacyStatus) + a single synthesized WL row."""

    # @unit
    # Scenario: T7-1-S1 one line per playlist with title, id, privacyStatus (unit)
    #   Given a Tools instance with OAuth configured
    #   And playlists.list serving playlists "Rust" (id PL1, privacyStatus public) and "Go" (id PL2, privacyStatus unlisted)
    #   When list_playlists()
    #   Then line 1 of the output is exactly "=== Playlists (mine=true) ==="
    #   And the output contains the line "Rust — id: PL1 — privacy: public"
    #   And the output contains the line "Go — id: PL2 — privacy: unlisted"
    #   When list_playlists() with an empty playlists.list result
    #   Then the output is exactly the header line and the synthesized WL row (no result lines)
    # (edge: missing/None privacyStatus renders as "unknown" — defensive)
    @pytest.mark.parametrize(
        ("label", "rows", "expected_lines"),
        [
            (
                "two_playlists",
                [_row("PL1", "Rust", "public"), _row("PL2", "Go", "unlisted")],
                ["Rust — id: PL1 — privacy: public", "Go — id: PL2 — privacy: unlisted"],
            ),
            ("empty", [], []),
            ("missing_privacy", [_row("PL3", "No Privacy")], ["No Privacy — id: PL3 — privacy: unknown"]),
        ],
        ids=["two_playlists", "empty", "missing_privacy"],
    )
    async def test_list_playlists_lines(self, tools, monkeypatch, label, rows, expected_lines):
        api_fake(monkeypatch, pages={}, playlist_pages=[{"items": rows}])

        result = await tools.list_playlists()

        lines = result.split("\n")
        assert lines[0] == HEADER
        assert lines[-1] == WL_ROW
        if label == "empty":
            assert lines == [HEADER, WL_ROW]
        else:
            assert lines[1:-1] == expected_lines

    # @unit
    # Scenario: T7-1-S2 pagination follows nextPageToken until exhausted (unit)
    #   Given playlists.list serving 120 playlists at maxResults 50 (pages 50/50/20)
    #   When list_playlists()
    #   Then exactly 3 playlists.list requests are made (nextPageToken followed on pages 1–2)
    #   And all 120 playlist lines are present, in API order
    async def test_pagination_follows_next_page_token(self, tools, monkeypatch):
        def build(n_start: int, n_count: int, token: str) -> dict:
            items = [_row(f"PL{i}", f"List {i}", "public") for i in range(n_start, n_start + n_count)]
            page: dict = {"items": items}
            if token:
                page["nextPageToken"] = token
            return page

        pages = [build(0, 50, "t2"), build(50, 50, "t3"), build(100, 20, "")]
        calls = api_fake(monkeypatch, pages={}, playlist_pages=pages)

        result = await tools.list_playlists()

        list_calls = [params for method, params in calls if method == "playlists.list"]
        assert len(list_calls) == 3
        assert "pageToken" not in list_calls[0]
        assert list_calls[1]["pageToken"] == "t2"
        assert list_calls[2]["pageToken"] == "t3"
        expected = [f"List {i} — id: PL{i} — privacy: public" for i in range(120)]
        assert result.split("\n")[1 : 1 + len(expected)] == expected

    # @unit
    # Scenario: T7-1-S3 the existing _find_playlist_by_title call is normalized to maxResults 50 (unit)
    #   Given a Tools instance with OAuth configured
    #   When a title lookup runs via _find_playlist_by_title
    #   Then the playlists.list request params carry maxResults 50 (not 100)
    #   And a playlist on page 2 (index 60) is still found by title
    @pytest.mark.parametrize("layout", ["params_assert", "page_2_found"], ids=["params_assert", "page_2_found"])
    async def test_find_playlist_by_title_max_results_50(self, tools, monkeypatch, layout):
        if layout == "params_assert":
            pages = [{"items": [_row("PL-T", "Target", "public")]}]
        else:
            pages = [
                {"items": [_row(f"PL{o}", f"Other {o}", "public") for o in range(50)], "nextPageToken": "t2"},
                {"items": [_row("PL-T2", "Target", "public")]},
            ]
        calls = api_fake(monkeypatch, pages={}, playlist_pages=pages)

        found = tools._find_playlist_by_title("Target")

        if layout == "params_assert":
            assert found == "PL-T"
            list_params = [params for method, params in calls if method == "playlists.list"]
            assert list_params[0]["maxResults"] == 50
        else:
            assert found == "PL-T2"

    # @unit
    # Scenario: T7-1-S4 mine is the only selector — no id/channelId in the request (unit)
    #   Given a Tools instance with OAuth configured
    #   When list_playlists() and a _find_playlist_by_title lookup run
    #   Then every playlists.list request params has mine true and contains neither "id" nor "channelId"
    async def test_mine_only_selector(self, tools, monkeypatch):
        calls = api_fake(monkeypatch, pages={}, playlist_pages=[{"items": [_row("PL1", "Rust", "public")]}])

        await tools.list_playlists()

        list_calls = [params for method, params in calls if method == "playlists.list"]
        assert list_calls
        for params in list_calls:
            assert params.get("mine") is True
            assert "id" not in params
            assert "channelId" not in params

    # @unit
    # Scenario: T7-1-S5 the Watch Later row is synthesized, labeled, and always last (unit)
    #   Given any playlists.list result (including none)
    #   When list_playlists()
    #   Then the final line is exactly "Watch Later (WL) — alias "WL" (synthesized row; not a playlists.list result)"
    #   And no result line is derived from playlists.list output for WL/HL
    @pytest.mark.parametrize(
        "rows",
        [
            [_row("PL1", "Rust", "public"), _row("PL2", "Go", "unlisted")],
            [],
            [_row("PLWL", "Watch Later", "public")],
        ],
        ids=["with_rows", "empty", "api_wl_row"],
    )
    async def test_wl_row_synthesized_labeled_last(self, tools, monkeypatch, rows):
        api_fake(monkeypatch, pages={}, playlist_pages=[{"items": rows}])

        result = await tools.list_playlists()

        lines = result.split("\n")
        assert lines[-1] == WL_ROW
        assert lines.count(WL_ROW) == 1

    # @unit
    # Scenario: T7-1-S6 the docstring states readonly-scope sufficiency and the live-verify flag (unit)
    #   Given Tools.list_playlists
    #   Then its docstring contains "youtube.readonly suffices"
    #   And its docstring contains "Live API verification NOT performed at design time"
    #   And its docstring contains "1 quota unit/page"
    async def test_docstring_scope_and_live_flag(self):
        doc = Tools.list_playlists.__doc__ or ""
        assert "youtube.readonly suffices" in doc
        assert "Live API verification NOT performed at design time" in doc
        assert "1 quota unit/page" in doc

    # @unit
    # Scenario: T7-1-S7 [OPEN] unconfigured OAuth reuses the sibling surface — no new string (unit)
    #   Given a Tools instance with OAuth unconfigured
    #   When list_playlists() and add_to_playlist (minimal valid args) run
    #   Then list_playlists() returns the existing unconfigured surface (sibling-equivalence with add_to_playlist; no string invented in T7-1)
    #   # Owner-statement pending (backlog item 7 is silent on no-OAuth) — KISS call: sibling-equivalence, zero new strings/branches.
    # (both error-mapping branches must be sibling-equivalent: ReauthNeeded -> REAUTH_NEEDED string, generic -> "Error: " string;
    #  the new method reuses the sibling's exact mapping, so equivalence is frozen for both)
    @pytest.mark.parametrize(
        ("exc", "prefix"),
        [
            (ReauthNeeded("simulated unconfigured OAuth surface"), "REAUTH_NEEDED"),
            (RuntimeError("simulated transient API failure"), "Error: "),
        ],
        ids=["reauth_needed", "generic_error"],
    )
    async def test_unconfigured_oauth_sibling_equivalence(self, tools, monkeypatch, fake_store, exc, prefix):
        def _raise(valves, method, params, user_id=None):
            raise exc

        monkeypatch.setattr("youtube_manager._data_api_execute", _raise)

        add_result = await tools.add_to_playlist(VIDEO_ID)
        list_result = await tools.list_playlists()

        assert list_result == add_result
        assert list_result.startswith(prefix)
