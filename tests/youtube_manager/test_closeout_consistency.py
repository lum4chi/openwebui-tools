"""
T8-1 — Close-out: backlog-doc status + final consistency pass.

Scenarios T8-1-S1 (backlog doc marks implemented items DONE), S2 (tool version
line is exactly the final 2.2.1), S3 (no plan-internal task-ID label leaks into
the tool file). S4 (do-not-regress full suite) is the package acceptance
command, not a nested test.

The backlog doc (.opencode/plans/yt-manager-deferred.md) is disk-only/untracked
(never committed), so S1 skips on fresh clones where it is absent.
"""

import re
from pathlib import Path

import pytest

import youtube_manager

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / ".opencode" / "plans" / "yt-manager-deferred.md"
DATE = r"\d{4}-\d{2}-\d{2}"

# frozen per-item work-package commit subjects (from the T8-1 contract)
ITEM_SUBJECTS = {
    1: "fix: gather_candidates skips unknown source tokens with a warning note",
    2: "docs: record_feedback intentionally keeps non-standard video ids (append-only feedback log)",
    3: "fix: digest reports taste-profile changes observed during the run",
    4: "feat: transcript supports chunked reads via max_lines/offset",
    5: "feat: key durable state files by requesting user (data/<user_id>/)",
    7: "feat: list_playlists() playlist enumeration (mine=true, maxResults 50)",
}

# frozen item-6 line (byte-identical; scope OUT, kept as-is by design)
ITEM6_LINE = (
    "6. **Transcript language fallback** — already transparent: "
    "`Notice: transcript language fallback: requested de, used en`. Keep."
)


class TestCloseoutConsistency:
    # @unit
    # Scenario: T8-1-S1 the backlog doc marks implemented items DONE with date and commit pointer
    #   Given the backlog doc .opencode/plans/yt-manager-deferred.md after close-out
    #   Then its global Status line reads "Status: DONE" with a YYYY-MM-DD date
    #   And each of items 1, 2, 3, 4, 5, 7 heading lines ends with " — DONE <YYYY-MM-DD> (<frozen commit subject>)"
    #   And item 6's line is byte-identical to its pre-close-out text
    #   And no other line in the doc changed (verified by the package diff — status lines only)
    def test_backlog_doc_items_done(self):
        if not DOC.exists():
            pytest.skip("yt-manager-deferred.md is untracked; absent on fresh clones")
        lines = DOC.read_text().split("\n")
        # global Status line
        status_lines = [line for line in lines if line.startswith("Status: DONE ")]
        assert status_lines, "missing the global 'Status: DONE' line"
        assert re.match(
            rf"^Status: DONE {DATE} — items 1–5, 7 implemented \(per-item commit subjects below\); "
            r"item 6 kept as-is by design \(scope OUT\)\.$",
            status_lines[0],
        ), f"global Status line is not the exact close-out text: {status_lines[0]!r}"
        # six per-item DONE suffixes
        for num, subject in ITEM_SUBJECTS.items():
            marker = re.compile(rf"^{num}\. .* — DONE {DATE} \({re.escape(subject)}\)$")
            assert any(marker.match(line) for line in lines), f"item {num} not marked DONE with its frozen subject"
        # frozen item-6 line byte-identical
        assert ITEM6_LINE in lines, "item 6 line changed (must be byte-identical)"

    # @unit
    # Scenario: T8-1-S2 the tool docstring version is exactly the final 2.2.1
    #   Given youtube_manager.py
    #   Then its docstring contains exactly one line "version: 2.2.1"
    def test_tool_version_line_final(self):
        doc = youtube_manager.__doc__ or ""
        version_lines = [line for line in doc.split("\n") if line.strip() == "version: 2.2.1"]
        assert version_lines == ["version: 2.2.1"], f"expected exactly one 'version: 2.2.1' line, got {version_lines!r}"

    # @unit
    # Scenario: T8-1-S3 no plan-internal task-ID labels leak into the tool's user-facing strings
    #   Given youtube_manager.py
    #   Then no line matches the pattern T[0-9]+-[0-9]+
    #   # test files are exempt: their Gherkin comments carry T<group>-<id> labels by the repo rule
    def test_no_task_id_labels_in_tool(self):
        src = Path(youtube_manager.__file__).read_text()
        assert not re.search(r"T[0-9]+-[0-9]+", src), "plan-internal task-ID label leaked into the tool file"
