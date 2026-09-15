"""T1-1 Data-API resolution under googleapiclient 2.200 (`__is_resource__` bound-method nodes).

The service under test is the REAL youtube v3 service built offline from the discovery
doc bundled with google-api-python-client. Only the transport
(`googleapiclient.http.HttpRequest.execute`) is stubbed, so the real `Resource`/`Method`
classes perform the real argmap kwarg validation: a pre-fix `resource=`-keyed insert
raises `TypeError: Got an unexpected keyword argument resource`, a `body=`-keyed insert
passes. That is exactly the contract the production bug (and this suite) must honour.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import googleapiclient
import httplib2
import pytest
from googleapiclient import discovery
from googleapiclient.http import HttpRequest

import youtube_manager
from youtube_manager import _data_api_request

# The google-api-python-client wheel bundles the discovery docs inside the package.
_YT_DOC = Path(googleapiclient.__file__).parent / "discovery_cache" / "documents" / "youtube.v3.json"
_HTTP_TO_METHOD = {"GET": "list", "POST": "insert", "DELETE": "delete"}


@contextmanager
def _real_service(routes: dict[str, object]):
    """Build the real 2.200-shaped youtube v3 service; only `HttpRequest.execute` is stubbed.

    Yields `(service, calls)`. Every request that reaches the transport is recorded as
    `(method path, params)` where `params` is reconstructed from the outgoing request
    (query params + JSON body; the client-added `alt` param is dropped) — i.e. exactly
    what the tool is about to send on the wire.
    """
    doc = json.loads(_YT_DOC.read_text())
    service = discovery.build_from_document(doc, http=httplib2.Http())
    calls: list[tuple[str, dict]] = []

    def execute(self):
        split = urlsplit(str(self.uri))
        path = split.path.rsplit("/", 1)[-1]
        method = _HTTP_TO_METHOD[str(self.method)]
        params = {k: v[0] for k, v in parse_qs(split.query, keep_blank_values=True).items() if k != "alt"}
        if self.body is not None:
            params["body"] = json.loads(self.body)
        calls.append((f"{path}.{method}", params))
        return routes.get(f"{path}.{method}", {})

    with patch.object(HttpRequest, "execute", execute):
        yield service, calls


def _valves():
    v = youtube_manager.Tools().Valves()
    v.google_client_id = "client-id"
    v.google_client_secret = "client-secret"
    v.google_refresh_token = "refresh-token"
    return v


class TestResolveOrCreate:
    """add_to_playlist over a real 2.200 youtube v3 service (resolution end-to-end)."""

    # @unit
    # Scenario: add_to_playlist resolves a 2.200 __is_resource__ service and adds (AC1)
    #   Given a tools instance with oauth set and an empty playlist store
    #   And a real youtube v3 service (discovery doc; only the transport is stubbed)
    #   When add_to_playlist(video_id="v1") is called
    #   Then a playlist is created and the video added
    #   And it returns the created playlist id (no exception)
    #   And playlists.insert and playlistItems.insert were reached via .execute() with a body= kwarg
    async def test_add_to_playlist_creates_playlist_and_adds(self, tools, fake_store):
        routes = {
            "playlists.list": {"items": []},
            "playlists.insert": {"id": "PL-NEW"},
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
        assert "PL-NEW" in result  # the created playlist id is returned
        assert (
            "playlists.insert",
            {"part": "snippet", "body": {"snippet": {"title": "Open WebUI Digest"}}},
        ) in calls
        assert (
            "playlistItems.insert",
            {"part": "snippet", "body": {"snippet": {"playlistId": "PL-NEW", "videoId": "v1"}}},
        ) in calls  # both inserts were reached (leaf called -> .execute() answered)

    # @unit
    # Scenario: add_to_playlist is idempotent for an existing title (AC2)
    #   Given a real service whose playlists.list returns an existing "Open WebUI Digest" (id PL-1)
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
        with (
            _real_service(routes) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = await tools.add_to_playlist("v1")

        assert "PL-1" in result  # the existing playlist id is returned
        assert not any(method == "playlists.insert" for method, _ in calls)  # no duplicate playlist
        inserts = [params for method, params in calls if method == "playlistItems.insert"]
        assert len(inserts) == 1  # the video is added exactly once
        assert inserts[0]["body"] == {"snippet": {"playlistId": "PL-1", "videoId": "v1"}}


class TestResourceKwargLock:
    """Regression lock: the pre-fix `resource=` kwarg must be rejected by the real client."""

    # @unit
    # Scenario: the real youtube v3 service rejects the pre-fix resource=-keyed inserts
    #   Given a real youtube v3 service (discovery doc built offline; only the transport stubbed)
    #   When playlists.insert / playlistItems.insert is called with the pre-fix params
    #        {"part": "snippet", "resource": {...}}
    #   Then TypeError("Got an unexpected keyword argument resource") is raised
    #   (the old contract is now caught; the fixed body= contract is proven green in
    #    TestResolveOrCreate, which fails with this TypeError against the pre-fix code)
    @pytest.mark.parametrize(
        ("collection", "body"),
        [
            ("playlists", {"snippet": {"title": "Open WebUI Digest"}}),
            ("playlistItems", {"snippet": {"playlistId": "PL-NEW", "videoId": "v1"}}),
        ],
    )
    def test_insert_rejects_resource_kwarg(self, collection, body):
        with _real_service({}) as (service, _calls):
            node = getattr(service, collection)
            if getattr(node, "__is_resource__", False) is True:
                node = node()  # 2.200: nested resource is a bound method
            with pytest.raises(TypeError, match="Got an unexpected keyword argument resource"):
                node.insert(part="snippet", resource=body)


class TestDeletePlannedWire:
    """The prune remove path's delete shape on a REAL 2.200 service (guards youtube_manager.py:1182).

    The discovery doc defines playlistItems.delete as an HTTP DELETE with a single required
    ``id`` query param and NO request body. The production remove path already sends
    ``{"id": item.item_id}`` — so :1182 is the correct contract (unlike the insert paths,
    which needed resource= -> body=). Driving the real client proves a regression to an
    insert-style shape (``body=``/``resource=``) surfaces as a TypeError, not a silent 400.
    """

    # @unit
    # Scenario: the prune remove path's delete(id=...) shape is the real contract and reaches the wire
    #   Given a real youtube v3 service (discovery doc; only the transport stubbed)
    #   And a prune plan of one tool-added item (item_id="it123")
    #   When _delete_planned(plan) is called (the method that holds the production delete at :1182)
    #   Then the delete succeeds and the wire request is DELETE .../playlistItems?id=it123 with NO body
    def test_delete_reaches_wire_with_id(self, tools):
        item = youtube_manager.PruneItem("it123", "v1", "Stale video", "2026-01-01")
        with (
            _real_service({}) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            removed, failure = tools._delete_planned([(item, "policy")])
        assert failure is None
        assert [i.item_id for i, _ in removed] == ["it123"]
        assert calls == [("playlistItems.delete", {"id": "it123"})]  # query param on the wire, no body

    # @unit
    # Scenario: the real client rejects the insert-style delete shapes (bug class locked)
    #   Given a real youtube v3 service (discovery doc; only the transport stubbed)
    #   When playlistItems.delete is called with {"body": {...}} or {"resource": {...}}
    #   Then TypeError("Got an unexpected keyword argument <name>") is raised
    #   (the insert-style shapes are NOT the delete contract; a body-style "fix" of :1182 is caught)
    @pytest.mark.parametrize("bad_kwarg", ["body", "resource"])
    def test_delete_rejects_insert_style_kwarg(self, bad_kwarg):
        with _real_service({}) as (service, _calls):
            node = service.playlistItems
            if getattr(node, "__is_resource__", False) is True:
                node = node()
            with pytest.raises(TypeError, match=f"Got an unexpected keyword argument {bad_kwarg}"):
                node.delete(**{bad_kwarg: {"id": "it123"}})


class TestDataApiRequest:
    """_data_api_request walks a 2.200 nested resource to a callable method."""

    # @unit
    # Scenario: _data_api_request walks a 2.200 nested resource to a callable method (AC4)
    #   Given a real service (channels is an __is_resource__ bound method; channels.list is a method)
    #   When _data_api_request(valves, "channels.list", {...}) is called
    #   Then channels.list(**params).execute() is reached and the json result is returned
    def test_walks_nested_resource_to_callable_method(self):
        reply = {"items": [{"id": "me"}]}
        with (
            _real_service({"channels.list": reply}) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = _data_api_request(_valves(), "channels.list", {"part": "contentDetails", "mine": "true"})
        assert result is reply  # the .execute() payload is returned
        assert calls == [("channels.list", {"part": "contentDetails", "mine": "true"})]

    # @unit
    # Scenario: a json-string .execute() answer is parsed to a dict
    #   Given a real service whose channels.list Request answers with a JSON string
    #   When _data_api_request is called
    #   Then the string is parsed and the dict is returned
    def test_execute_json_string_is_parsed(self):
        reply = '{"items": []}'
        with (
            _real_service({"channels.list": reply}) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
        ):
            result = _data_api_request(_valves(), "channels.list", {"part": "contentDetails"})
        assert result == {"items": []}
        assert calls == [("channels.list", {"part": "contentDetails"})]

    # @unit
    # Scenario: a genuinely missing segment raises AttributeError (local bug stays visible)
    #   Given a real service with no "widgets" node
    #   When _data_api_request(valves, "widgets.list", {...}) is called
    #   Then AttributeError is raised (not swallowed, not mislabelled)
    def test_missing_segment_raises_attribute_error(self):
        with (
            _real_service({}) as (service, calls),
            patch.object(youtube_manager, "_oauth_token", return_value={"access_token": "AT"}),
            patch("youtube_manager.discovery.build", return_value=service),
            pytest.raises(AttributeError),
        ):
            _data_api_request(_valves(), "widgets.list", {"part": "snippet"})
        assert calls == []
