"""Dev-only LIVE acceptance harness for the youtube_manager tool (T0-1).

Reproduces the INITIAL OWUI credential condition (a documented non-empty DUMMY valve token +
a browser-acquired per-user FILE token), acquires that FILE credential itself via the tool's
own start_auth/finish_auth browser flow (ONE auth; re-runs reuse the token file), runs the
bug's acceptance sequence against the real Google API with the user's credentials (loaded
from a root `.env`; see `env.template`), and logs raw API evidence (identity, WL raw response,
per-feed counts). The tool code is untouched: this module only WRAPS
`youtube_manager._data_api_execute` for instrumentation and threads the Open WebUI `__user__`
exactly as OWUI would (only where a tool method declares it).

Live run (human, real credentials, opt-in, NOT in CI):
    uv run python dev/youtube_live.py
"""

import asyncio
import inspect
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # script-mode: make the repo root importable

from dotenv import dotenv_values  # noqa: E402

import youtube_manager as ym  # noqa: E402
from youtube_manager import CREDENTIAL_TITLE, Tools  # noqa: E402

REQUIRED_KEYS = (
    "YTM_GOOGLE_CLIENT_ID",
    "YTM_GOOGLE_CLIENT_SECRET",
    "YTM_USER_ID",
)
DUMMY_REFRESH_TOKEN = "live-harness-dummy-refresh-token"
# Valve dummy, NOT env: the .env carries no refresh-token slot (initial condition only). The
# documented non-empty dummy is what makes pre-fix list_playlists resolve the valve token (not the
# file token) and reproduce the EXACT production ReauthNeeded: _effective_refresh_token has NO
# emptiness/format pre-check, so the dummy REACHES the token endpoint POST -> HTTP 400/401 ->
# ReauthNeeded("Google rejected the grant - stored credential is stale"). Any non-empty string
# works; this fixed value is the smallest such choice (KISS).
OPTIONAL_DEFAULTS = {
    "YTM_DATA_DIR": ".data-live",
    "YTM_VERBOSE": "false",
    "YTM_DIGEST_PLAYLIST_TITLE": "Open WebUI Digest",
    "YTM_DIGEST_MAX_ITEMS": "50",
    "YTM_DIGEST_MAX_AGE_DAYS": "30",
    "YTM_WATCH_LATER_PLAYLIST_TITLE": "Watch Later",
}
PLAYLISTS_HEADER = "=== Playlists (mine=true) ==="
SYNTHESIZED_WL_ROW = 'Watch Later (WL) — alias "WL" (synthesized row; not a playlists.list result)'
CANDIDATES_RE = re.compile(r"=== Candidates \((\d+)\) ===")


def load_env(path: str = ".env") -> dict[str, str]:
    """Parse the root .env (no env mutation), apply optional defaults, fail on missing required keys."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"no {path!r} — cp env.template .env and fill in the YTM_* values (keep .env uncommitted)"
        )
    file_env = {key: (value or "").strip() for key, value in dotenv_values(str(file_path)).items()}
    env: dict[str, str] = dict(OPTIONAL_DEFAULTS)
    for key in (*REQUIRED_KEYS, *OPTIONAL_DEFAULTS):
        if file_env.get(key):
            env[key] = file_env[key]
    missing = [key for key in REQUIRED_KEYS if not env.get(key)]
    if missing:
        raise ValueError("missing required env keys: " + ", ".join(missing))
    return env


def build_tools(env: dict[str, str], data_dir: Path) -> Tools:
    """Tools with the DUMMY valve token and NO token file (initial condition: run_auth acquires the file credential)."""
    os.environ["DATA_DIR"] = str(data_dir)
    tools = Tools()
    tools.valves.google_client_id = env["YTM_GOOGLE_CLIENT_ID"]
    tools.valves.google_client_secret = env["YTM_GOOGLE_CLIENT_SECRET"]
    tools.valves.google_refresh_token = DUMMY_REFRESH_TOKEN
    tools.valves.digest_playlist_title = env["YTM_DIGEST_PLAYLIST_TITLE"]
    tools.valves.digest_max_items = int(env["YTM_DIGEST_MAX_ITEMS"])
    tools.valves.digest_max_age_days = int(env["YTM_DIGEST_MAX_AGE_DAYS"])
    tools.valves.watch_later_playlist_title = env["YTM_WATCH_LATER_PLAYLIST_TITLE"]
    tools.valves.verbose = env["YTM_VERBOSE"].lower() in ("1", "true", "yes")
    return tools


async def owui_call(fn, user_id: str, *args, **kwargs):
    """Await fn(*args, **kwargs), injecting __user__ exactly as OWUI does: only where the method declares it."""
    if "__user__" in inspect.signature(fn).parameters:
        kwargs = {**kwargs, "__user__": {"id": user_id}}
    return await fn(*args, **kwargs)


def _playlist_rows(result: object) -> list:
    """Playlist rows across both response shapes: raw bytes (real API path) or dict (api_fake convention)."""
    if isinstance(result, (bytes, bytearray)):
        try:
            payload = json.loads(bytes(result).decode("utf-8"))
        except ValueError:
            return []
    elif isinstance(result, dict):
        payload = result
    else:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def _item_count(result: object) -> int:
    """Item count across both response shapes: raw bytes (real API path) or dict (api_fake convention)."""
    return len(_playlist_rows(result))


def _failure_detail(err: BaseException) -> dict:
    """Failure evidence for the instrumentation log: exception class + HTTP status (when present) + cleaned reason (no raw secrets)."""
    return {"class": type(err).__name__, "status": ym._http_status(err), "reason": ym._clean_exception(err)}


def instrument() -> list[dict]:
    """Wrap ym._data_api_execute (resolved now — late binding, so a test patch is wrapped, not bypassed).

    Every call is logged: a success entry ({method, params, user_id, items}) or, when the delegate
    raises, a failure entry ({method, params, user_id, error}) carrying the cleaned reason — then the
    exception is re-raised unchanged."""
    log: list[dict] = []
    delegate = ym._data_api_execute

    def wrapper(valves, method: str, params: dict, user_id: str | None = None):
        try:
            result = delegate(valves, method, params, user_id)
        except Exception as err:
            log.append({"method": method, "params": dict(params), "user_id": user_id, "error": _failure_detail(err)})
            raise
        items = _playlist_rows(result) if method == "playlists.list" else _item_count(result)
        log.append({"method": method, "params": dict(params), "user_id": user_id, "items": items})
        return result

    ym._data_api_execute = wrapper
    return log


async def run_auth(tools, user_id: str, data_dir: Path, input_fn=input) -> None:
    """Acquire the per-user credential via the tool's ONE browser auth (token-reuse guard first).

    Prints only the start_auth instructions (consent URL) and the finish_auth result line; the
    pasted code/URL is NEVER printed or logged (secret invariant — S7 pins this)."""
    token_path = data_dir / user_id / f"{CREDENTIAL_TITLE}.md"
    if token_path.exists():
        return
    print(await tools.start_auth())
    paste = input_fn("Paste the redirected URL (or just the code): ")
    print(await owui_call(tools.finish_auth, user_id, paste))


def probe_identity(tools: Tools, user_id: str) -> tuple[dict | None, str | None]:
    """Resolve the authenticated account via channels.list (evidence: WHICH account).

    Returns (identity, reason): identity is the account dict (or None on failure); reason carries
    the cleaned error when the API call raised (None for an empty reply)."""
    try:
        resp = ym._data_api_request(tools.valves, "channels.list", {"part": "snippet", "mine": True}, user_id=user_id)
    except Exception as err:
        return None, ym._clean_exception(err)
    items = resp.get("items") or []
    if not items:
        return None, None
    item = items[0]
    return {"channel_id": item.get("id"), "title": (item.get("snippet") or {}).get("title")}, None


async def _step_identity(tools: Tools, user_id: str) -> tuple[str, bool, str]:
    identity, reason = probe_identity(tools, user_id)
    if identity is None:
        detail = f"no channel resolved: {reason}" if reason else "no channel resolved (channels.list mine=true empty)"
        return ("identity", False, detail)
    return ("identity", True, f"channel_id={identity['channel_id']} title={identity['title']!r}")


async def _step_check_setup(tools: Tools, user_id: str) -> tuple[str, bool, str]:
    out = await owui_call(tools.check_setup, user_id)
    lines = out.splitlines()
    return ("check_setup", bool(lines) and lines[-1] == "READY", " | ".join(lines))


async def _step_list_playlists(tools: Tools, user_id: str) -> tuple[str, bool, str]:
    out = await owui_call(tools.list_playlists, user_id)
    lines = out.splitlines()
    if lines and lines[0] == PLAYLISTS_HEADER:
        playlist_lines = [line for line in lines[1:] if line != SYNTHESIZED_WL_ROW]
        return ("list_playlists", bool(playlist_lines), f"{len(playlist_lines)} playlist lines")
    return ("list_playlists", False, lines[0] if lines else out)


def _resolved_wl_id(log: list[dict], title: str) -> str | None:
    """The valve playlist id derived from logged playlists.list rows (trimmed exact title match, first match)."""
    for entry in log:
        if entry["method"] != "playlists.list" or "items" not in entry:
            continue
        for row in entry["items"]:
            if ((row.get("snippet") or {}).get("title") or "").strip() == title.strip():
                return row.get("id") or None
    return None


def _wl_raw_items(log: list[dict], title: str) -> int:
    playlist_id = _resolved_wl_id(log, title)
    if not playlist_id:
        return 0
    counts = [
        entry["items"]
        for entry in log
        if "items" in entry
        and entry["method"] == "playlistItems.list"
        and entry["params"].get("playlistId") == playlist_id
    ]
    return max(counts) if counts else 0


def _feed_counts(log: list[dict], title: str) -> dict[str, int]:
    excluded = _resolved_wl_id(log, title)
    counts: dict[str, int] = {}
    for entry in log:
        if "items" not in entry or entry["method"] != "playlistItems.list":
            continue
        playlist_id = entry["params"].get("playlistId")
        if playlist_id in (None, excluded):
            continue
        counts[str(playlist_id)] = entry["items"]
    return counts


def _evidence(source: str, log: list[dict], title: str) -> str:
    if source == "watch_later":
        return f"wl_raw_items={_wl_raw_items(log, title)}"
    feeds = ", ".join(f"{playlist_id}={items}" for playlist_id, items in sorted(_feed_counts(log, title).items()))
    return f"feeds={feeds}" if feeds else "feeds=(none)"


async def _step_gather(tools: Tools, user_id: str, source: str, log: list[dict], title: str) -> tuple[str, bool, str]:
    out = await owui_call(tools.gather_candidates, user_id, source)
    match = CANDIDATES_RE.search(out)
    count = int(match.group(1)) if match else 0
    return (source, count > 0, f"candidates={count}; {_evidence(source, log, title)}")


async def run_acceptance(tools: Tools, env: dict[str, str], log: list[dict]) -> list[tuple[str, bool, str]]:
    """The 5 acceptance steps (exception-safe: tool methods return error strings; probe_identity catches)."""
    user_id = env["YTM_USER_ID"]
    title = tools.valves.watch_later_playlist_title
    results: list[tuple[str, bool, str]] = []
    results.append(await _step_identity(tools, user_id))
    results.append(await _step_check_setup(tools, user_id))
    results.append(await _step_list_playlists(tools, user_id))
    results.append(await _step_gather(tools, user_id, "watch_later", log, title))
    results.append(await _step_gather(tools, user_id, "subscriptions", log, title))
    return results


def _render_api_line(entry: dict) -> str:
    base = f"api: {entry['method']} user_id={entry['user_id']}"
    if "items" in entry:
        items = entry["items"]
        count = len(items) if isinstance(items, list) else items
        return f"{base} items={count} params={entry['params']}"
    error = entry["error"]
    status = "" if error["status"] is None else f" status={error['status']}"
    return f"{base} FAILED class={error['class']}{status} reason={error['reason']} params={entry['params']}"


def _render_report(results: list[tuple[str, bool, str]], log: list[dict]) -> str:
    lines = [f"{'PASS' if ok else 'FAIL'}  {name}  {detail}" for name, ok, detail in results]
    api_lines = [_render_api_line(entry) for entry in log]
    return "\n".join(lines + api_lines) + "\n"


def main(argv=None) -> int:
    env_path = argv[0] if argv else ".env"
    try:
        env = load_env(env_path)
    except (FileNotFoundError, ValueError) as err:
        print(f"live harness: {err}")
        return 1
    data_dir = Path(env["YTM_DATA_DIR"])
    tools = build_tools(env, data_dir)
    log = instrument()
    asyncio.run(run_auth(tools, env["YTM_USER_ID"], data_dir))
    results = asyncio.run(run_acceptance(tools, env, log))
    report = _render_report(results, log)
    print(report)
    (data_dir / "live-run.log").write_text(report)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
