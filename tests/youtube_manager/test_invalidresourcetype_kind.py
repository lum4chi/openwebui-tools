"""T1-1 BDD: the playlistItems.insert body carries a well-formed resourceId with kind.

Root cause of the 400 `invalidResourceType` on `playlistItems.insert`: the insert body's
`snippet.resourceId` omitted the required `kind` field. The YouTube Data API v3 contract
requires `snippet.resourceId.kind == "youtube#video"` for a normal video. This scenario
drives `add_to_playlist` over the real offline youtube v3 service (transport-only stubbed,
via the shared `_real_service` harness) and locks the reconstructed outgoing body.
"""

from unittest.mock import patch

import youtube_manager

from .test_resolution import _real_service


class TestInvalidResourceTypeKind:
    """add_to_playlist builds a playlistItems.insert body whose resourceId carries kind."""

    # @unit
    # Scenario: The playlistItems.insert body carries a well-formed resourceId with kind
    #   Given a tool whose add_to_playlist path performs an insert for video "v1" into playlist "PL-1"
    #   When the code builds the playlistItems.insert request body
    #   Then the body equals {"snippet": {"playlistId": "PL-1", "resourceId": {"kind": "youtube#video", "videoId": "v1"}}}
    #   And body["snippet"]["resourceId"]["kind"] is "youtube#video"
    #   And body["snippet"]["resourceId"]["videoId"] is "v1"
    async def test_insert_body_carries_well_formed_resourceid_with_kind(self, tools, fake_store):
        routes = {
            "playlists.list": {"items": [{"id": "PL-1", "snippet": {"title": "Open WebUI Digest"}}]},
            "playlistItems.list": {"items": []},
            "playlistItems.insert": {"snippet": {"title": "New Video"}},
        }
        with (
            _real_service(routes) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = await tools.add_to_playlist("v1")

        assert result.startswith("OK")
        inserts = [params for method, params in calls if method == "playlistItems.insert"]
        assert len(inserts) == 1  # the video is added exactly once
        body = inserts[0]["body"]
        assert body == {"snippet": {"playlistId": "PL-1", "resourceId": {"kind": "youtube#video", "videoId": "v1"}}}
        assert body["snippet"]["resourceId"]["kind"] == "youtube#video"
        assert body["snippet"]["resourceId"]["videoId"] == "v1"
