"""T1-1 Data-API resolution under googleapiclient 2.200 (`__is_resource__` bound-method nodes)."""

import types
from unittest.mock import patch

import pytest

import youtube_manager
from youtube_manager import _data_api_request


class _Request:
    """Stand-in for a googleapiclient Request: `.execute()` yields the routed reply."""

    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


def _shaped_service(routes: dict[str, object]):
    """Build a googleapiclient 2.200-shaped service + a (method path, params) call log.

    Root collections (playlists/playlistItems/channels/videos) are callables tagged
    `__is_resource__ is True` (the bool, not a truthy non-bool); calling one returns
    a Resource whose list/insert/delete leaf methods answer with a Request whose
    `.execute()` yields the reply routed by full method path ("channels.list" -> dict).
    """
    calls: list[tuple[str, dict]] = []

    def leaf(collection: str, method: str):
        def call(**params):
            calls.append((f"{collection}.{method}", params))
            return _Request(routes.get(f"{collection}.{method}", {}))

        return call

    def resource(collection: str):
        ns = types.SimpleNamespace()
        for method in ("list", "insert", "delete"):
            setattr(ns, method, leaf(collection, method))
        return ns

    service = types.SimpleNamespace()
    for collection in ("playlists", "playlistItems", "channels", "videos"):

        def node(col=collection):
            return resource(col)

        node.__is_resource__ = True  # type: ignore[attr-defined]
        setattr(service, collection, node)
    return service, calls


def _valves():
    v = youtube_manager.Tools().Valves()
    v.google_client_id = "client-id"
    v.google_client_secret = "client-secret"
    v.google_refresh_token = "refresh-token"
    return v


class TestResolveOrCreate:
    """add_to_playlist over a real 2.200-shaped service (resolution end-to-end)."""

    # @unit
    # Scenario: add_to_playlist resolves a 2.200 __is_resource__ service and adds (AC1)
    #   Given a tools instance with oauth set and an empty playlist store
    #   And a shaped service whose playlists/playlistItems are __is_resource__ bound methods
    #   When add_to_playlist(video_id="v1") is called
    #   Then a playlist is created and the video added
    #   And it returns the created playlist id (no exception)
    #   And playlists.insert and playlistItems.insert were reached via .execute()
    async def test_add_to_playlist_creates_playlist_and_adds(self, tools, fake_store):
        routes = {
            "playlists.list": {"items": []},
            "playlists.insert": {"id": "PL-NEW"},
            "playlistItems.list": {"items": []},
            "playlistItems.insert": {"snippet": {"title": "New Video"}},
        }
        service, calls = _shaped_service(routes)
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = await tools.add_to_playlist("v1")

        assert result.startswith("OK")
        assert "PL-NEW" in result  # the created playlist id is returned
        assert (
            "playlists.insert",
            {"part": "snippet", "resource": {"snippet": {"title": "Open WebUI Digest"}}},
        ) in calls
        assert (
            "playlistItems.insert",
            {"part": "snippet", "resource": {"snippet": {"playlistId": "PL-NEW", "videoId": "v1"}}},
        ) in calls  # both inserts were reached (leaf called -> .execute() answered)

    # @unit
    # Scenario: add_to_playlist is idempotent for an existing title (AC2)
    #   Given a shaped service whose playlists.list returns an existing "My Playlist" (id PL-1)
    #   And a playlistItems.list with no matching video
    #   When add_to_playlist(video_id="v1") is called
    #   Then the video is added to PL-1 exactly once (no duplicate insert)
    #   And it returns PL-1
    async def test_add_to_playlist_idempotent_for_existing_title(self, tools, fake_store):
        routes = {
            "playlists.list": {"items": [{"id": "PL-1", "snippet": {"title": "Open WebUI Digest"}}]},
            "playlistItems.list": {"items": []},
            "playlistItems.insert": {"snippet": {"title": "New Video"}},
        }
        service, calls = _shaped_service(routes)
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = await tools.add_to_playlist("v1")

        assert "PL-1" in result  # the existing playlist id is returned
        assert not any(method == "playlists.insert" for method, _ in calls)  # no duplicate playlist
        inserts = [params for method, params in calls if method == "playlistItems.insert"]
        assert len(inserts) == 1  # the video is added exactly once
        assert inserts[0]["resource"] == {"snippet": {"playlistId": "PL-1", "videoId": "v1"}}


class TestDataApiRequest:
    """_data_api_request walks a 2.200 nested resource to a callable method."""

    # @unit
    # Scenario: _data_api_request walks a 2.200 nested resource to a callable method (AC4)
    #   Given a shaped service (channels is an __is_resource__ bound method; channels.list is a method)
    #   When _data_api_request(valves, "channels.list", {...}) is called
    #   Then channels.list(**params).execute() is reached and the json result is returned
    def test_walks_nested_resource_to_callable_method(self):
        reply = {"items": [{"id": "me"}]}
        service, calls = _shaped_service({"channels.list": reply})
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = _data_api_request(_valves(), "channels.list", {"part": "contentDetails", "mine": "true"})
        assert result is reply  # the .execute() payload is returned
        assert calls == [("channels.list", {"part": "contentDetails", "mine": "true"})]

    # @unit
    # Scenario: a json-string .execute() answer is parsed to a dict
    #   Given a shaped service whose channels.list Request answers with a JSON string
    #   When _data_api_request is called
    #   Then the string is parsed and the dict is returned
    def test_execute_json_string_is_parsed(self):
        reply = '{"items": []}'
        service, calls = _shaped_service({"channels.list": reply})
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = _data_api_request(_valves(), "channels.list", {"part": "contentDetails"})
        assert result == {"items": []}
        assert calls == [("channels.list", {"part": "contentDetails"})]

    # @unit
    # Scenario: a genuinely missing segment raises AttributeError (local bug stays visible)
    #   Given a shaped service with no "widgets" node
    #   When _data_api_request(valves, "widgets.list", {...}) is called
    #   Then AttributeError is raised (not swallowed, not mislabelled)
    def test_missing_segment_raises_attribute_error(self):
        service, calls = _shaped_service({})
        with (
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
            pytest.raises(AttributeError),
        ):
            _data_api_request(_valves(), "widgets.list", {"part": "snippet"})
        assert calls == []
