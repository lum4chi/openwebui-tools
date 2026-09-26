"""Dev-only LIVE acceptance harness for the youtube_manager tool (T0-1).

Reproduces the PRODUCTION credential topology (STALE valve token + FRESH per-user file
token), runs the bug's acceptance sequence against the real Google API with the user's
credentials (loaded from a root `.env`; see `env.template`), and logs raw API evidence
(identity, WL raw response, per-feed counts). The tool code is untouched: this module
only WRAPS `youtube_manager._data_api_execute` for instrumentation and threads the Open
WebUI `__user__` exactly as OWUI would (only where a tool method declares it).

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
    "YTM_GOOGLE_REFRESH_TOKEN_STALE",
    "YTM_GOOGLE_CLIENT_SECRET",
    "YTM_GOOGLE_REFRESH_TOKEN_FRESH",
    "YTM_USER_ID",
)
OPTIONAL_DEFAULTS = {
    "YTM_DATA_DIR": ".data-live",
    "YTM_VERBOSE": "false",
    "YTM_DIGEST_PLAYLIST_TITLE": "Open WebUI Digest",
    "YTM_DIGEST_MAX_ITEMS": "50",
    "YTM_DIGEST_MAX_AGE_DAYS": "30",
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
    """Tools with the STALE valve token; the FRESH token is written to <data_dir>/<user_id>/ (production topology)."""
    os.environ["DATA_DIR"] = str(data_dir)
    user_dir = data_dir / env["YTM_USER_ID"]
    user_dir.mkdir(parents=True, exist_ok=True)
    token_path = user_dir / f"{CREDENTIAL_TITLE}.md"
    token_path.write_text(env["YTM_GOOGLE_REFRESH_TOKEN_FRESH"])
    token_path.chmod(0o600)
    tools = Tools()
    tools.valves.google_client_id = env["YTM_GOOGLE_CLIENT_ID"]
    tools.valves.google_client_secret = env["YTM_GOOGLE_CLIENT_SECRET"]
    tools.valves.google_refresh_token = env["YTM_GOOGLE_REFRESH_TOKEN_STALE"]
    tools.valves.digest_playlist_title = env["YTM_DIGEST_PLAYLIST_TITLE"]
    tools.valves.digest_max_items = int(env["YTM_DIGEST_MAX_ITEMS"])
    tools.valves.digest_max_age_days = int(env["YTM_DIGEST_MAX_AGE_DAYS"])
    tools.valves.verbose = env["YTM_VERBOSE"].lower() in ("1", "true", "yes")
    return tools


async def owui_call(fn, user_id: str, *args, **kwargs):
    """Await fn(*args, **kwargs), injecting __user__ exactly as OWUI does: only where the method declares it."""
    if "__user__" in inspect.signature(fn).parameters:
        kwargs = {**kwargs, "__user__": {"id": user_id}}
    return await fn(*args, **kwargs)


def _item_count(result: object) -> int:
    """Item count across both response shapes: raw bytes (real API path) or dict (api_fake convention)."""
    if isinstance(result, (bytes, bytearray)):
        try:
            payload = json.loads(bytes(result).decode("utf-8"))
        except ValueError:
            return 0
    elif isinstance(result, dict):
        payload = result
    else:
        return 0
    items = payload.get("items") if isinstance(payload, dict) else None
    return len(items) if isinstance(items, list) else 0


def instrument() -> list[dict]:
    """Wrap ym._data_api_execute (resolved now — late binding, so a test patch is wrapped, not bypassed)."""
    log: list[dict] = []
    delegate = ym._data_api_execute

    def wrapper(valves, method: str, params: dict, user_id: str | None = None):
        result = delegate(valves, method, params, user_id)
        log.append({"method": method, "params": dict(params), "user_id": user_id, "items": _item_count(result)})
        return result

    ym._data_api_execute = wrapper
    return log


def probe_identity(tools: Tools, user_id: str) -> dict | None:
    """Resolve the authenticated account via channels.list (evidence: WHICH account); None on any error."""
    try:
        resp = ym._data_api_request(tools.valves, "channels.list", {"part": "snippet", "mine": True}, user_id=user_id)
    except Exception:
        return None
    items = resp.get("items") or []
    if not items:
        return None
    item = items[0]
    return {"channel_id": item.get("id"), "title": (item.get("snippet") or {}).get("title")}


async def _step_identity(tools: Tools, user_id: str) -> tuple[str, bool, str]:
    identity = probe_identity(tools, user_id)
    if identity is None:
        return ("identity", False, "no channel resolved (channels.list mine=true empty or errored)")
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


def _wl_raw_items(log: list[dict]) -> int:
    counts = [
        entry["items"]
        for entry in log
        if entry["method"] == "playlistItems.list" and entry["params"].get("playlistId") == "WL"
    ]
    return max(counts) if counts else 0


def _feed_counts(log: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in log:
        if entry["method"] != "playlistItems.list":
            continue
        playlist_id = entry["params"].get("playlistId")
        if playlist_id in (None, "WL"):
            continue
        counts[str(playlist_id)] = entry["items"]
    return counts


def _evidence(source: str, log: list[dict]) -> str:
    if source == "watch_later":
        return f"wl_raw_items={_wl_raw_items(log)}"
    feeds = ", ".join(f"{playlist_id}={items}" for playlist_id, items in sorted(_feed_counts(log).items()))
    return f"feeds={feeds}" if feeds else "feeds=(none)"


async def _step_gather(tools: Tools, user_id: str, source: str, log: list[dict]) -> tuple[str, bool, str]:
    out = await owui_call(tools.gather_candidates, user_id, source)
    match = CANDIDATES_RE.search(out)
    count = int(match.group(1)) if match else 0
    return (source, count > 0, f"candidates={count}; {_evidence(source, log)}")


async def run_acceptance(tools: Tools, env: dict[str, str], log: list[dict]) -> list[tuple[str, bool, str]]:
    """The 5 acceptance steps (exception-safe: tool methods return error strings; probe_identity catches)."""
    user_id = env["YTM_USER_ID"]
    results: list[tuple[str, bool, str]] = []
    results.append(await _step_identity(tools, user_id))
    results.append(await _step_check_setup(tools, user_id))
    results.append(await _step_list_playlists(tools, user_id))
    results.append(await _step_gather(tools, user_id, "watch_later", log))
    results.append(await _step_gather(tools, user_id, "subscriptions", log))
    return results


def _render_report(results: list[tuple[str, bool, str]], log: list[dict]) -> str:
    lines = [f"{'PASS' if ok else 'FAIL'}  {name}  {detail}" for name, ok, detail in results]
    api_lines = [
        f"api: {entry['method']} user_id={entry['user_id']} items={entry['items']} params={entry['params']}"
        for entry in log
    ]
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
    results = asyncio.run(run_acceptance(tools, env, log))
    report = _render_report(results, log)
    print(report)
    (data_dir / "live-run.log").write_text(report)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
