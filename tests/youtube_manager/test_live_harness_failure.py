"""T0-1 S5 failure-evidence unit mirrors: the live harness logs per-call FAILURE evidence.

Extends the S5 instrumentation-log contract: when a wrapped Data API call raises, the harness logs a
failure entry ({method, params, user_id, error: {class, status, reason}}) carrying the cleaned reason
(no raw secrets — the tool's own maskers are reused), re-raises the exception unchanged, and the report
renders a per-call failure line. The success entry shape and the success `api:` line are unchanged.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import youtube_manager as ym
from youtube_manager import QuotaError, ReauthNeeded

from .conftest import api_fake

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = _REPO_ROOT / "dev" / "youtube_live.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("dev_youtube_live_failure", _HARNESS)
    if spec is None or spec.loader is None:
        raise AssertionError("harness spec/loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hl = _load_harness()


class TestFailureDetail:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): _failure_detail reuses the tool's maskers
    #   Given an exception (ReauthNeeded / QuotaError / a generic error / an HttpError with a status)
    #   When _failure_detail builds the failure evidence
    #   Then it carries the exception class name, the HTTP status (when present, else None),
    #     and the cleaned reason from youtube_manager._clean_exception (no raw secrets)
    @pytest.mark.parametrize(
        ("err", "expected"),
        [
            (
                ReauthNeeded("boom"),
                {"class": "ReauthNeeded", "status": None, "reason": "reauthentication required", "detail": "boom"},
            ),
            (QuotaError("boom"), {"class": "QuotaError", "status": None, "reason": "quota reached", "detail": "boom"}),
            (
                RuntimeError("boom"),
                {"class": "RuntimeError", "status": None, "reason": "unexpected error", "detail": "boom"},
            ),
        ],
    )
    def test_failure_detail_reuses_tool_maskers(self, err, expected):
        assert hl._failure_detail(err) == expected

    def test_failure_detail_carries_http_status(self):
        err = HttpError(MagicMock(status=404, reason="Not Found"), b'{"error": {"message": "notFound"}}')

        assert hl._failure_detail(err) == {
            "class": "HttpError",
            "status": 404,
            "reason": "not found - the resource no longer exists",
            "detail": str(err)[:200],
        }


class TestFailedLineDetail:
    # @unit
    # Scenario T1-5-S2 (unit): a failed api line logs the exception message, not only class and the generic reason
    #   # trace: dispatch task 3 — "FAILED lines must log the exception message (str(exc)), not only class + the generic 'unexpected error'"
    #   Given an instrumented _data_api_execute that raises TypeError("Got an unexpected keyword argument ids")
    #   When the api line is rendered for that failure
    #   Then the line carries class=TypeError and the masked reason from the tool masker
    #   And the line carries detail= with the exception's str(exc) text
    #   And a detail longer than 200 characters is truncated
    #   # clock seam: the injected fixed clock flows into the log entry ts and the rendered [ts] prefix
    def test_failed_line_carries_str_exc_detail(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, raise_for={"videos.list": TypeError("Got an unexpected keyword argument ids")})
        monkeypatch.setattr(hl, "_clock", lambda: "2026-09-30T12:00:00")
        log = hl.instrument()

        with pytest.raises(TypeError):
            ym._data_api_execute(tools.valves, "videos.list", {"part": "snippet", "id": "v1"}, user_id="u1")

        line = hl._render_api_line(log[0])

        assert line == (
            "[2026-09-30T12:00:00] api: videos.list user_id=u1 FAILED class=TypeError "
            "reason=unexpected error detail=Got an unexpected keyword argument ids params={'part': 'snippet', 'id': 'v1'}"
        )

    def test_failed_line_detail_capped_at_200_chars(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, raise_for={"videos.list": TypeError("x" * 250)})
        log = hl.instrument()

        with pytest.raises(TypeError):
            ym._data_api_execute(tools.valves, "videos.list", {"part": "snippet", "id": "v1"}, user_id="u1")

        line = hl._render_api_line(log[0])

        assert f"detail={'x' * 200}" in line
        assert "x" * 201 not in line


class TestInstrumentFailure:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): the instrumentation wrapper logs a failure entry and re-raises
    #   Given an instrumented youtube_manager._data_api_execute whose delegate raises ReauthNeeded
    #   When the wrapped call is made
    #   Then the log records one failure entry ({method, params, user_id, error: {class, status, reason}})
    #     and the original exception propagates unchanged
    def test_wrapper_logs_failure_entry_and_reraises(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, raise_for={"channels.list": ReauthNeeded("boom")})
        log = hl.instrument()

        with pytest.raises(ReauthNeeded):
            ym._data_api_execute(tools.valves, "channels.list", {"part": "snippet", "mine": True}, user_id="u1")

        assert len(log) == 1
        entry = log[0]
        assert set(entry) == {"method", "params", "user_id", "ts", "error"}  # T1-5 re-pin: + call-time ts
        assert entry["method"] == "channels.list"
        assert entry["params"] == {"part": "snippet", "mine": True}
        assert entry["user_id"] == "u1"
        assert entry["ts"]
        assert entry["error"] == {
            "class": "ReauthNeeded",
            "status": None,
            "reason": "reauthentication required",
            "detail": "boom",  # T1-5: str(err) capped at 200
        }


class TestCountsGuards:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): the WL/feed counters ignore failure entries
    #   Given an instrumentation log mixing success entries (items) and failure entries (error)
    #   And a playlists.list success entry whose row resolves the valve playlist id
    #   When _wl_raw_items / _feed_counts scan the log (deriving the valve id from the logged row)
    #   Then they count only success entries (a failure entry carries no items and is skipped)
    def test_wl_raw_items_ignores_failure_entries(self):
        log = [
            {
                "method": "playlists.list",
                "params": {},
                "user_id": "u1",
                "items": [{"id": "PLWL", "snippet": {"title": "Watch Later"}}],
            },
            {"method": "playlistItems.list", "params": {"playlistId": "PLWL"}, "user_id": "u1", "items": 3},
            {
                "method": "playlistItems.list",
                "params": {"playlistId": "PLWL"},
                "user_id": "u1",
                "error": {"class": "ReauthNeeded", "status": None, "reason": "reauthentication required"},
            },
        ]

        assert hl._wl_raw_items(log, "Watch Later") == 3

    def test_feed_counts_ignores_failure_entries(self):
        log = [
            {
                "method": "playlists.list",
                "params": {},
                "user_id": "u1",
                "items": [{"id": "PLWL", "snippet": {"title": "Watch Later"}}],
            },
            {"method": "playlistItems.list", "params": {"playlistId": "up1"}, "user_id": "u1", "items": 2},
            {
                "method": "playlistItems.list",
                "params": {"playlistId": "up2"},
                "user_id": "u1",
                "error": {"class": "ReauthNeeded", "status": None, "reason": "reauthentication required"},
            },
        ]

        assert hl._feed_counts(log, "Watch Later") == {"up1": 2}


class TestRenderApiLine:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): the report renders per-call failure lines
    #   Given a failure entry (with/without an HTTP status) and a success entry
    #   When _render_api_line renders each
    #   Then the failure line carries method, class, status (when present), cleaned reason, params,
    #     and the success line is byte-identical to the pre-fix format
    def test_failure_line_with_status(self):
        entry = {
            "method": "playlists.list",
            "params": {},
            "user_id": "u1",
            "ts": "2026-09-30T12:00:00",
            "error": {
                "class": "HttpError",
                "status": 404,
                "reason": "not found - the resource no longer exists",
                "detail": "boom",
            },
        }

        assert hl._render_api_line(entry) == (
            "[2026-09-30T12:00:00] api: playlists.list user_id=u1 FAILED class=HttpError status=404 "
            "reason=not found - the resource no longer exists detail=boom params={}"
        )

    def test_failure_line_without_status(self):
        entry = {
            "method": "channels.list",
            "params": {},
            "user_id": "u1",
            "ts": "2026-09-30T12:00:00",
            "error": {"class": "ReauthNeeded", "status": None, "reason": "reauthentication required", "detail": "boom"},
        }

        assert hl._render_api_line(entry) == (
            "[2026-09-30T12:00:00] api: channels.list user_id=u1 FAILED class=ReauthNeeded "
            "reason=reauthentication required detail=boom params={}"
        )

    def test_success_line_carries_timestamp(self):
        entry = {
            "method": "playlistItems.list",
            "params": {"playlistId": "WL"},
            "user_id": "u1",
            "ts": "2026-09-30T12:00:00",
            "items": 5,
        }

        assert hl._render_api_line(entry) == (
            "[2026-09-30T12:00:00] api: playlistItems.list user_id=u1 items=5 params={'playlistId': 'WL'}"
        )


class TestRenderReport:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): the report interleaves step results and per-call lines
    #   Given step results plus a log mixing a failure entry and a success entry
    #   When _render_report renders the report
    #   Then each step is a PASS/FAIL line and each call is an api: line (failure or success)
    def test_render_report_renders_failure_and_success_lines(self):
        # T1-5 re-pin: 4-tuple results, ts-carrying entries, run-start line + [ts] prefixes.
        results = [("identity", False, "no channel resolved: reauthentication required", "2026-09-30T12:00:01")]
        log = [
            {
                "method": "channels.list",
                "params": {"part": "snippet"},
                "user_id": "u1",
                "ts": "2026-09-30T12:00:02",
                "error": {
                    "class": "ReauthNeeded",
                    "status": None,
                    "reason": "reauthentication required",
                    "detail": "boom",
                },
            },
            {
                "method": "playlistItems.list",
                "params": {"playlistId": "WL"},
                "user_id": "u1",
                "ts": "2026-09-30T12:00:03",
                "items": 2,
            },
        ]

        lines = hl._render_report(results, log, "2026-09-30T12:00:00").splitlines()

        assert lines[0] == "live-run started 2026-09-30T12:00:00"
        assert lines[1] == "[2026-09-30T12:00:01] FAIL  identity  no channel resolved: reauthentication required"
        assert lines[2] == (
            "[2026-09-30T12:00:02] api: channels.list user_id=u1 FAILED class=ReauthNeeded "
            "reason=reauthentication required detail=boom params={'part': 'snippet'}"
        )
        assert (
            lines[3] == "[2026-09-30T12:00:03] api: playlistItems.list user_id=u1 items=2 params={'playlistId': 'WL'}"
        )


class TestStepIdentity:
    # @unit
    # Scenario: T0-1-S5 (failure evidence): the identity step carries the probe reason
    #   Given an identity probe whose channels.list call raises ReauthNeeded
    #   When _step_identity runs
    #   Then the step is FAIL and its detail carries the cleaned reason (not just "no channel resolved")
    async def test_api_error_carries_reason(self, tools, monkeypatch):
        api_fake(monkeypatch, pages={}, raise_for={"channels.list": ReauthNeeded("boom")})

        name, ok, detail = await hl._step_identity(tools, "u1")

        assert (name, ok) == ("identity", False)
        assert "reauthentication required" in detail


class TestAcceptanceRunFailure:
    # @unit
    # Scenario: T0-1-S5 (failure evidence, mocked seams, no network): acceptance run where the API always fails
    #   Given a harness run against mocked seams where every youtube_manager._data_api_execute call raises
    #     ReauthNeeded (the production reauth topology, without real credentials)
    #   When run_acceptance executes the 5 steps
    #   Then the run completes (tool methods are exception-safe), every step is FAIL, the identity detail
    #     carries the cleaned reason, and the instrumentation log records a failure entry for each call
    async def test_failure_run_logs_per_call_evidence(self, tools, monkeypatch):
        def reauth(valves, method, params, user_id=None):
            raise ReauthNeeded("Google credential rejected by the Data API")

        monkeypatch.setattr("youtube_manager._data_api_execute", reauth)
        monkeypatch.setattr(
            "youtube_manager._oauth_token", lambda valves, code=None, user_id=None: {"access_token": "tok"}
        )
        log = hl.instrument()

        results = await hl.run_acceptance(tools, {"YTM_USER_ID": "u1"}, log)

        assert [name for name, _, _, _ in results] == [
            "identity",
            "check_setup",
            "list_playlists",
            "watch_later",
            "subscriptions",
        ]
        assert all(not ok for _, ok, _, _ in results)
        assert "reauthentication required" in results[0][2]
        assert all(ts for _, _, _, ts in results)  # T1-5 re-pin: 4-tuple step results
        assert log
        for entry in log:
            assert set(entry) == {"method", "params", "user_id", "ts", "error"}  # T1-5 re-pin: + call-time ts
