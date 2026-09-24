"""T4-1: digest reports taste-profile changes observed during the run.

BDD: plan ``yt-deferred-backlog.md``, task T4-1 (scenarios T4-1-S1..S4).
"""

import youtube_manager
from youtube_manager import NOTE_TASTE, Tools

from .conftest import FakeStateStore, sample_taste_profile

PROFILE_A = sample_taste_profile(["rust async"], ["cat videos"])
PROFILE_B = sample_taste_profile(["go generics"], ["ads"])
TASTE_CHANGED_NOTICE = (
    "Notice: taste profile changed during this digest run; this output reflects the profile as of digest start."
)


def _clear_oauth(tools):
    tools.valves.google_client_id = ""
    tools.valves.google_client_secret = ""
    tools.valves.google_refresh_token = ""


class _ChangingTasteStore(FakeStateStore):
    """Store that serves profile A on the first taste-profile read and profile B on later reads (S2)."""

    def __init__(self, first: str, later: str) -> None:
        super().__init__()
        self._first = first
        self._later = later
        self._taste_reads = 0

    def read(self, title: str) -> str | None:
        if title == NOTE_TASTE:
            self._taste_reads += 1
            return self._first if self._taste_reads == 1 else self._later
        return super().read(title)


class TestDigestProfileNotice:
    async def test_unchanged_profile_no_notice(self, tools, monkeypatch):
        # @unit
        # Scenario: T4-1-S1 unchanged profile produces no notice (unit)
        #   Given a configured Tools instance whose store serves the same taste profile for every read
        #   When digest()
        #   Then the output contains the normal digest markers "=== Taste profile ===", "=== Feedback stats ===", "=== Sources ===", "=== Candidates"
        #   And the output contains no "taste profile changed" text
        _clear_oauth(tools)
        store = FakeStateStore({NOTE_TASTE: PROFILE_A})
        monkeypatch.setattr(youtube_manager, "_state_store", lambda request: store)

        payload = await tools.digest()

        for marker in ("=== Taste profile ===", "=== Feedback stats ===", "=== Sources ===", "=== Candidates"):
            assert marker in payload
        assert "taste profile changed" not in payload

    async def test_profile_changed_during_run_notice(self, tools, monkeypatch):
        # @unit
        # Scenario: T4-1-S2 a profile change during the run is surfaced as a Notice (unit)
        #   Given a configured Tools instance whose store returns profile A on the first taste-profile read and profile B on later reads
        #   When digest()
        #   Then the output was built from profile A
        #   And the output ends with the line
        #     "Notice: taste profile changed during this digest run; this output reflects the profile as of digest start."
        _clear_oauth(tools)
        store = _ChangingTasteStore(PROFILE_A, PROFILE_B)
        monkeypatch.setattr(youtube_manager, "_state_store", lambda request: store)

        payload = await tools.digest()

        assert "rust async" in payload
        assert "go generics" not in payload
        assert payload.splitlines()[-1] == TASTE_CHANGED_NOTICE

    async def test_save_before_digest_visible_no_notice(self, tools, monkeypatch):
        # @workflow
        # Scenario: T4-1-S3 a save that completes before digest is visible, with no notice (workflow)
        #   Given a configured Tools instance with no taste profile
        #   When save_taste_profile(md=starter) completes
        #   And digest() runs afterwards
        #   Then the digest output contains the starter profile content
        #   And the output contains no "taste profile changed" text
        #   # documents the ordering: digest reads the profile as of its own call
        _clear_oauth(tools)
        store = FakeStateStore()
        monkeypatch.setattr(youtube_manager, "_state_store", lambda request: store)

        saved = await tools.save_taste_profile(PROFILE_A)
        payload = await tools.digest()

        assert saved.startswith("OK - saved taste profile")
        assert "rust async" in payload
        assert "taste profile changed" not in payload

    def test_docstrings_document_call_time_read(self):
        # @unit
        # Scenario: T4-1-S4 the ordering is documented in the docstrings (unit)
        #   Given Tools.digest and Tools.save_taste_profile
        #   Then digest's docstring contains "The taste profile is read at call time"
        #   And save_taste_profile's docstring contains "after this save"
        digest_doc = Tools.digest.__doc__ or ""
        save_doc = Tools.save_taste_profile.__doc__ or ""
        assert "The taste profile is read at call time" in digest_doc
        assert "after this save" in save_doc
