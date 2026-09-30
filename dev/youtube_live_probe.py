"""Dev-only LIVE evidence probe for the youtube_manager tool (T1-5).

Reuses the per-user credential stored by a previous `dev/youtube_live.py` run (NO re-auth:
the harness owns the browser flow) and dumps API evidence only — the authenticated account
identity, one real videos.list response body (single id `_4TryLfB_gM`, the shape that failed
live before the T1-4 fix), the valve-resolved Watch Later playlist (id + title + real item
count), and every playlist id+title row. Token, client-secret and valve values are never
printed: Data API response bodies carry no credential material by contract.

Live run (human, real credentials, opt-in, NOT in CI):
    uv run python dev/youtube_live_probe.py
"""

import importlib.util
import json
import sys
from pathlib import Path

_VIDEO_ID = "_4TryLfB_gM"


def _load_harness():
    """Load dev/youtube_live.py from this file's own directory (same pattern as the harness tests)."""
    spec = importlib.util.spec_from_file_location(
        "dev_youtube_live", Path(__file__).resolve().with_name("youtube_live.py")
    )
    if spec is None or spec.loader is None:
        raise AssertionError("harness spec/loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_h = _load_harness()
_ym = _h.ym  # the harness's youtube_manager module (shared sys.modules entry — test patches reach it)
CREDENTIAL_TITLE = _h.CREDENTIAL_TITLE


def _identity_section(tools, user_id: str) -> None:
    identity, reason = _h.probe_identity(tools, user_id)
    if identity is None:
        raise RuntimeError(f"no channel resolved: {reason or 'channels.list mine=true empty'}")
    print(f"probe: identity channel_id={identity['channel_id']} title={identity['title']}")


def _videos_section(tools, user_id: str) -> None:
    resp = _ym._data_api_request(
        tools.valves,
        "videos.list",
        {"part": "snippet,contentDetails,statistics", "id": _VIDEO_ID},
        user_id=user_id,
    )
    print("probe: videos.list")
    print(json.dumps(resp, indent=2, sort_keys=True))


def _sweep_playlists(tools, user_id: str) -> list:
    """One paginated playlists.list sweep (mine=true, 50/page) across every page token."""
    rows: list = []
    page_token = None
    while True:
        params: dict = {"part": "snippet", "mine": True, "maxResults": "50"}
        if page_token is not None:
            params["pageToken"] = page_token
        resp = _ym._data_api_request(tools.valves, "playlists.list", params, user_id=user_id)
        rows.extend(resp.get("items") or [])
        page_token = resp.get("nextPageToken")
        if page_token is None:
            break
    return rows


def _wl_section(tools, user_id: str, title: str, state: dict) -> None:
    rows = _sweep_playlists(tools, user_id)
    state["rows"] = rows
    match = next(
        (row for row in rows if ((row.get("snippet") or {}).get("title") or "").strip() == title.strip()), None
    )
    if match is None:
        raise RuntimeError(f"no playlist titled {title!r} among {len(rows)} rows")
    print(f"probe: wl_playlist id={match.get('id')} title={(match.get('snippet') or {}).get('title')}")
    items = _ym._data_api_request(
        tools.valves,
        "playlistItems.list",
        {"part": "snippet,contentDetails", "playlistId": match.get("id"), "maxResults": "50"},
        user_id=user_id,
    )
    item_rows = items.get("items") or []
    print(f"probe: wl_playlist items={len(item_rows)} more_pages={bool(items.get('nextPageToken'))}")


def _playlists_section(state: dict) -> None:
    rows = state.get("rows")
    if rows is None:
        raise RuntimeError("playlists sweep did not complete")
    print("probe: playlists")
    for row in rows:
        print(f"{row.get('id')} {(row.get('snippet') or {}).get('title')}")


def main(argv=None) -> int:
    env_path = argv[0] if argv else ".env"
    env = _h.load_env(env_path)
    user_id = _ym._user_id_from({"id": env["YTM_USER_ID"]})
    data_dir = Path(env["YTM_DATA_DIR"])
    token_path = data_dir / user_id / f"{CREDENTIAL_TITLE}.md"
    if not token_path.exists():
        print("probe: no stored token — run the harness first")
        return 2
    tools = _h.build_tools(env, data_dir)
    title = tools.valves.watch_later_playlist_title
    state: dict = {"rows": None}
    sections = (
        ("identity", lambda: _identity_section(tools, user_id)),
        ("videos.list", lambda: _videos_section(tools, user_id)),
        ("wl_playlist", lambda: _wl_section(tools, user_id, title, state)),
        ("playlists", lambda: _playlists_section(state)),
    )
    failed = False
    for name, run in sections:
        try:
            run()
        except Exception as err:
            failed = True
            print(f"probe: {name} FAILED class={type(err).__name__} detail={str(err)[:200]}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
