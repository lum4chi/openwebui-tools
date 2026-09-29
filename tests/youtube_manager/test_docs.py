"""
T2-1 — stale repo docs: AGENTS.md + README.md describe the YouTube Manager tool (POST-FIX final behavior).

Scenario T2-1-S1 (unit): docs are current
  Given the repository documentation
  When checked
  Then AGENTS.md "Existing tools" lists youtube_manager.py with a one-line capability summary
  And README.md has a "YouTube Manager" section with the features list, a table covering all 8 valves,
    usage examples, and the live-harness section naming `uv run python dev/youtube_live.py`
     plus the "tool reads Valves, not env vars" note
     and the re-auth note (delete `.data-live/<user_id>/google-refresh-token.md` to force a new browser auth)
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS = (REPO_ROOT / "AGENTS.md").read_text()
README = (REPO_ROOT / "README.md").read_text()

AGENTS_HEADER = "Existing tools (importable as separate tools):"
AGENTS_LINE = (
    "- `youtube_manager.py` — YouTube digest: gathers candidates from Watch Later + subscriptions "
    "via Google OAuth (per-user file token), digest playlist management, transcript with yt-dlp fallback"
)

SECTION_START = "### YouTube Manager"
SECTION_END = "## Development"

FEATURES = (
    "check_setup",
    "start_auth",
    "finish_auth",
    "gather_candidates",
    "digest",
    "list_playlists",
    "add_to_playlist",
    "prune_playlist",
    "transcript",
    "save_taste_profile",
    "record_feedback",
)

# valve name -> default, exactly as declared in youtube_manager.Tools.Valves
VALVE_DEFAULTS = {
    "google_client_id": '""',
    "google_client_secret": '""',
    "google_refresh_token": '""',
    "digest_playlist_title": "Open WebUI Digest",
    "watch_later_playlist_title": "Watch Later",
    "digest_max_items": "50",
    "digest_max_age_days": "30",
    "verbose": "False",
}

USAGE_EXAMPLES = ("check_setup", "start_auth", "finish_auth", "gather_candidates", "list_playlists", "transcript")

HARNESS_NOTES = (
    pytest.param("cp env.template .env", id="env-template-copy"),
    pytest.param("uv run python dev/youtube_live.py", id="live-command"),
    pytest.param("reads Valves, never env vars", id="valves-not-env-vars"),
    pytest.param("token-reuse guard", id="token-reuse-guard"),
)

CREDENTIAL_FILE = "data/<user_id>/google-refresh-token.md"
REAUTH_FILE = ".data-live/<user_id>/google-refresh-token.md"


def _section() -> str:
    if SECTION_START not in README:
        pytest.fail("README.md is missing the '### YouTube Manager' section")
    start = README.index(SECTION_START)
    return README[start : README.index(SECTION_END, start)]


def _usage_examples() -> str:
    section = _section()
    start = section.index("#### Usage Examples")
    return section[start : section.index("#### Live acceptance harness")]


def _fenced(text: str) -> str:
    parts = text.split("```")
    return "\n".join(parts[1::2])


class TestAgentsExistingTools:
    # Scenario T2-1-S1 (unit): docs are current
    #   Given the repository documentation
    #   When checked
    #   Then AGENTS.md "Existing tools" lists youtube_manager.py with a one-line capability summary
    def test_agents_existing_tools_lists_youtube_manager(self):
        header_at = AGENTS.index(AGENTS_HEADER)
        listing = AGENTS[header_at : AGENTS.index("\n## ", header_at)]
        assert AGENTS_LINE in listing.split("\n")


class TestReadmeYouTubeManager:
    # Scenario T2-1-S1 (unit): docs are current
    #   And README.md has a "YouTube Manager" section with the features list, a table covering all 8 valves,
    #     usage examples, and the live-harness section naming `uv run python dev/youtube_live.py`
    #      plus the "tool reads Valves, not env vars" note
    #      and the re-auth note (delete `.data-live/<user_id>/google-refresh-token.md` to force a new browser auth)
    def test_section_present_before_development(self):
        assert SECTION_START in README, "README.md is missing the '### YouTube Manager' section"
        assert README.index(SECTION_START) < README.index(SECTION_END)

    @pytest.mark.parametrize("feature", FEATURES)
    def test_features_list(self, feature):
        assert feature in _section(), f"feature {feature!r} missing from the YouTube Manager section"

    @pytest.mark.parametrize("valve, default", list(VALVE_DEFAULTS.items()))
    def test_valves_table_covers_all_8_with_defaults(self, valve, default):
        rows = [line for line in _section().split("\n") if line.lstrip().startswith("|")]
        for line in rows:
            cells = [cell.strip() for cell in line.split("|")]
            if cells[1] == f"`{valve}`":
                assert cells[2] == f"`{default}`", f"default for {valve!r} is not {default!r}"
                return
        pytest.fail(f"valve {valve!r} missing from the Valves table")

    def test_credential_file_note(self):
        section = _section()
        assert CREDENTIAL_FILE in section, "per-user credential file path missing"
        assert "the `google_refresh_token` valve is the fallback" in section, "valve-fallback note missing"

    @pytest.mark.parametrize("example", USAGE_EXAMPLES)
    def test_usage_examples(self, example):
        assert example in _fenced(_usage_examples()), f"usage example {example!r} missing"

    @pytest.mark.parametrize("note", HARNESS_NOTES)
    def test_live_harness_notes(self, note):
        assert note in _section(), f"live-harness note missing: {note!r}"

    def test_reauth_delete_note(self):
        lines = [line for line in _section().split("\n") if REAUTH_FILE in line]
        assert lines, "re-auth note missing the .data-live token file path"
        assert any("delete" in line and "re-run" in line for line in lines)
