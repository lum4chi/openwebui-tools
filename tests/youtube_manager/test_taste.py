"""T1 taste-profile pure functions + write seam (scenarios T1-10, T1-11, T1-12)."""

import pytest

from youtube_manager import NOTE_TASTE, Candidate, filter_disliked, parse_taste_profile

DOC = "# Taste profile\n\n## Topics\n- rust async\n- postgres\n\n## Avoid\n- Cat Videos\n- clickbait"


def _cand(video_id: str, title: str) -> Candidate:
    return Candidate(video_id, title, "ch", None, None, None, None, None, [], ["search"])


class TestTaste:
    """parse_taste_profile / filter_disliked / save_taste_profile."""

    # @unit
    # Scenario: T1-10 parse taste profile
    #   Given a taste-profile doc with a "## Topics" bullet list and a "## Avoid" bullet list
    #   When parse_taste_profile is called
    #   Then topics is the Topics bullets in order
    #   And disliked is the lowercased Avoid bullets
    #   And text is the raw markdown
    #   And when the input is None or empty
    #   Then it returns an empty profile (no topics, no disliked)
    #   And when there is no "## Topics" heading it falls back to the first bullet list in the doc
    @pytest.mark.parametrize(
        ("md", "expect_topics", "expect_disliked"),
        [
            (DOC, ["rust async", "postgres"], {"cat videos", "clickbait"}),
            # None / empty -> empty profile
            (None, [], set()),
            ("", [], set()),
            ("   \n  ", [], set()),
            # no "## Topics" heading -> first bullet list in the doc
            ("- rust\n- postgres\n", ["rust", "postgres"], set()),
            # "## Topics" heading present but empty -> falls back to first bullet list (none before first ##)
            ("## Topics\n\n## Avoid\n- cat\n", [], {"cat"}),
        ],
        ids=["topics_and_avoid", "none", "empty", "whitespace", "fallback_first_list", "empty_topics_heading"],
    )
    def test_parse_profile(self, md, expect_topics, expect_disliked):
        profile = parse_taste_profile(md)

        assert profile.topics == expect_topics
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

        assert result.startswith("Error:")
