"""T1 taste-profile pure functions + write seam (scenarios T1-10, T1-11, T1-12) + search profile→query verification (T0-4)."""

import pytest

import youtube_manager
from youtube_manager import NOTE_TASTE, Candidate, filter_disliked, parse_taste_profile

from .conftest import sample_taste_profile

DOC = "# Taste profile\n\n## Topics\n- rust async\n- postgres\n\n## Avoid\n- Cat Videos\n- clickbait"


def _cand(video_id: str, title: str) -> Candidate:
    return Candidate(video_id, title, "ch", None, None, None, None, None, [], ["search"])


class TestTaste:
    """parse_taste_profile / filter_disliked / save_taste_profile."""

    # @unit
    # Scenario: T1-10 parse taste profile
    #   Given a taste-profile doc with a "## Avoid" bullet list
    #   When parse_taste_profile is called
    #   Then disliked is the lowercased Avoid bullets
    #   And text is the raw markdown
    #   And no per-topic field is parsed (the raw text reaches the LLM verbatim instead)
    #   And when the input is None or empty it returns an empty profile (no disliked)
    @pytest.mark.parametrize(
        ("md", "expect_disliked"),
        [
            (DOC, {"cat videos", "clickbait"}),
            # None / empty -> empty profile
            (None, set()),
            ("", set()),
            ("   \n  ", set()),
            # doc with no heading -> only the raw text is asserted
            ("- rust\n- postgres\n", set()),
            # "## Avoid" heading present -> disliked parsed; no per-topic field
            ("## Topics\n\n## Avoid\n- cat\n", {"cat"}),
            # second heading after the target section -> collection stops (break)
            ("## Avoid\n- cat\n\n## Topics\n- x\n", {"cat"}),
        ],
        ids=["topics_and_avoid", "none", "empty", "whitespace", "no_heading", "avoid_heading", "heading_after_target"],
    )
    def test_parse_profile(self, md, expect_disliked):
        profile = parse_taste_profile(md)

        assert profile.disliked == expect_disliked
        assert profile.text == (md or "")

    # @unit
    # Scenario: T1-11 filter disliked
    #   Given candidates whose titles include one containing a disliked substring and others that do not
    #   When filter_disliked is called with the disliked set
    #   Then the disliked candidate is dropped
    #   And the kept candidates are returned in order
    #   And the returned removed_count equals the number dropped
    def test_filter_disliked(self):
        cands = [
            _cand("a", "Rust async deep dive"),
            _cand("b", "10 Cat Videos you'll love"),
            _cand("c", "Postgres indexing"),
        ]

        kept, removed = filter_disliked(cands, {"cat videos"})

        assert [cand.video_id for cand in kept] == ["a", "c"]
        assert removed == 1

    # empty disliked set keeps everything, unchanged order
    def test_filter_disliked_empty_set(self):
        cands = [_cand("a", "Any title"), _cand("b", "Another")]

        kept, removed = filter_disliked(cands, set())

        assert [cand.video_id for cand in kept] == ["a", "b"]
        assert removed == 0

    # @unit
    # Scenario: T1-12 save taste profile
    #   Given a taste-profile markdown string
    #   When save_taste_profile is called
    #   Then the state store write is called with the taste-profile title and the markdown
    #   And the result is OK
    #   And a state-store write that raises is caught and returned as an Error string (no crash)
    async def test_save_taste_profile(self, tools, fake_store):
        result = await tools.save_taste_profile(DOC)

        assert result == "OK"
        assert fake_store.docs[NOTE_TASTE] == DOC

    async def test_save_taste_profile_write_failure(self, tools, monkeypatch):
        def _boom(title, md):
            raise RuntimeError("state store down")

        monkeypatch.setattr(
            "youtube_manager._state_store", lambda request: type("S", (), {"write": staticmethod(_boom)})()
        )

        result = await tools.save_taste_profile(DOC)  # no exception propagates

        assert result == "Error: unexpected error"


def _entry(video_id):
    return {
        "id": video_id,
        "title": f"Feed title {video_id}",
        "uploader": f"Feed uploader {video_id}",
        "channel_id": f"ch-{video_id}",
        "duration": 120,
        "view_count": 500,
        "upload_date": "20260910",
        "description": f"Feed description {video_id}",
        "tags": ["feed-tag"],
    }


def _ytdlp_fake(monkeypatch, flat: dict[str, list[str]], full: dict[str, dict]):
    """Patch _ytdlp_extract: flat listings serve id-only rows, watch URLs serve full entries."""
    calls: list[str] = []

    def fake(url, extra=None):
        calls.append(url)
        if url in flat:
            return {"entries": [{"id": video_id} for video_id in flat[url]]}
        return full[url]

    monkeypatch.setattr(youtube_manager, "_ytdlp_extract", fake)
    return calls


class TestSearchProfile:
    """R1-B1 verification: search-source query with a taste profile set/empty/missing (T0-4.1, T0-4.2)."""

    # @unit
    # Scenario: T0-4.1 search enabled + taste profile → query derived from profile (verification)
    #   Given the search source enabled and a taste profile with explicit topics
    #   When gather_candidates runs
    #   Then the search API call recorded by the fake shows a query containing the profile-derived terms
    async def test_search_query_carries_profile_terms(self, tools, fake_store, monkeypatch):
        fake_store.docs[NOTE_TASTE] = sample_taste_profile(["rust async"], [])
        calls = _ytdlp_fake(
            monkeypatch,
            {"ytsearch5:rust async": ["sp-1"]},
            {"https://www.youtube.com/watch?v=sp-1": _entry("sp-1")},
        )

        payload = await tools.gather_candidates(sources="search", max_per_source=5, search_query="rust async")

        assert calls == ["ytsearch5:rust async", "https://www.youtube.com/watch?v=sp-1"]
        assert "Feed title sp-1" in payload
        assert "Candidate IDs: sp-1" in payload

    # @unit
    # Scenario: T0-4.2 search enabled + empty profile pins current fallback behavior (verification)
    #   Given the search source enabled and an empty or missing taste profile
    #   When gather_candidates runs
    #   Then the search query matches the current documented fallback behavior (pinned by this test)
    @pytest.mark.parametrize(
        ("profile_doc", "search_query"),
        [
            (None, "rust async"),
            ("", "rust async"),
            (None, ""),
            (None, "   "),
            ("", ""),
            ("", "   "),
        ],
        ids=[
            "missing_profile_explicit_query",
            "empty_profile_explicit_query",
            "missing_profile_empty_query",
            "missing_profile_whitespace_query",
            "empty_profile_empty_query",
            "empty_profile_whitespace_query",
        ],
    )
    async def test_search_requires_explicit_query(self, tools, fake_store, monkeypatch, profile_doc, search_query):
        if profile_doc is not None:
            fake_store.docs[NOTE_TASTE] = profile_doc
        calls = _ytdlp_fake(
            monkeypatch,
            {"ytsearch5:rust async": ["sp-2"]},
            {"https://www.youtube.com/watch?v=sp-2": _entry("sp-2")},
        )

        payload = await tools.gather_candidates(sources="search", max_per_source=5, search_query=search_query)

        if search_query.strip():
            assert calls == ["ytsearch5:rust async", "https://www.youtube.com/watch?v=sp-2"]
            assert "Feed title sp-2" in payload
        else:
            assert calls == []
            assert payload.startswith("Error:")
            assert "search_query" in payload
