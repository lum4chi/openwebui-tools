"""T0-1: zero-candidate diagnostics for the Data API per-channel subscriptions path."""

from .conftest import api_fake, guard_urlopen, idless_playlist_item, playlist_item, sub_channel, uploads_channel_reply


class TestZeroCandidateDiagnostics:
    """T0-1: deterministic headline suffixes when the Data API path yields no candidates."""

    # T0-1.6 · workflow — every uploads list empty produces the zero-entries suffix.
    #   Given _fetch_subscriptions sees 2 ok channels and 0 failed channels
    #   And every uploads list contains no playlist items
    #   And candidate_count is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 2 ok, 0 failed, 0 candidates (feeds returned zero entries)"
    def test_zero_entries_diagnostic(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={"PU0": [{"items": []}], "PU1": [{"items": []}]},
            subscription_pages=[{"items": [sub_channel("UC0"), sub_channel("UC1")]}],
            channels_by_id={"UC0": uploads_channel_reply("PU0"), "UC1": uploads_channel_reply("PU1")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == ["subscriptions: 2 ok, 0 failed, 0 candidates (feeds returned zero entries)"]

    # T0-1.6 · workflow — playlist items without resolvable video ids produce the id suffix.
    #   Given _fetch_subscriptions sees 2 ok channels and 0 failed channels
    #   And the uploads lists contain 3 items without a usable video id
    #   And candidate_count is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 2 ok, 0 failed, 0 candidates (feeds returned 3 entry(s) with no usable video id)"
    def test_no_usable_video_id_diagnostic(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={
                "PU0": [{"items": [idless_playlist_item(), idless_playlist_item()]}],
                "PU1": [{"items": [idless_playlist_item()]}],
            },
            subscription_pages=[{"items": [sub_channel("UC0"), sub_channel("UC1")]}],
            channels_by_id={"UC0": uploads_channel_reply("PU0"), "UC1": uploads_channel_reply("PU1")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(20, notes)

        assert cands == []
        assert notes == [
            "subscriptions: 2 ok, 0 failed, 0 candidates (feeds returned 3 entry(s) with no usable video id)"
        ]

    # T0-1.6 · workflow — a per-source cap of zero produces the capped suffix.
    #   Given _fetch_subscriptions sees 2 ok channels and 0 failed channels
    #   And each uploads list contains 1 usable item
    #   And max_per_source is 0
    #   When the subscriptions note is generated
    #   Then the note is exactly "subscriptions: 2 ok, 0 failed, 0 candidates (capped entries produced no candidates)"
    def test_capped_zero_produces_capped_diagnostic(self, tools, monkeypatch):
        api_fake(
            monkeypatch,
            pages={
                "PU0": [{"items": [playlist_item("V0", "V0", "C0", "2026-09-03T00:00:00Z")]}],
                "PU1": [{"items": [playlist_item("V1", "V1", "C1", "2026-09-01T00:00:00Z")]}],
            },
            subscription_pages=[{"items": [sub_channel("UC0"), sub_channel("UC1")]}],
            channels_by_id={"UC0": uploads_channel_reply("PU0"), "UC1": uploads_channel_reply("PU1")},
            videos={},
        )
        guard_urlopen(monkeypatch)
        notes: list[str] = []

        cands = tools._fetch_subscriptions(0, notes)

        assert cands == []
        assert notes == ["subscriptions: 2 ok, 0 failed, 0 candidates (capped entries produced no candidates)"]
