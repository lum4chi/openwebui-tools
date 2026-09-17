"""Shared fixtures for the reddit_feed tool test suite.

The tool is read-only and talks to Reddit over ``requests``; every test patches
``requests.post`` / ``requests.get`` (source-module level, house style) and feeds
deterministic payloads through these fixtures.

Time-dependent boundaries (the 24 h window) are made deterministic by computing
``created_utc`` relative to a ``now`` captured at test time — no clock freezing.
"""

from unittest.mock import MagicMock

import pytest
import requests

from reddit_feed import Tools


def _reason(status_code: int) -> str:
    if status_code == 401:
        return "Unauthorized"
    if status_code == 429:
        return "Too Many Requests"
    return "OK"


def _t3_data(index: int, now: float, age_minutes: int) -> dict:
    return {
        "id": f"p{index}",
        "title": f"Post {index}",
        "author": f"author{index}",
        "score": 1000 - index,
        "num_comments": 42,
        "created_utc": int(now - age_minutes * 60),
        "selftext": "x" * (50 + index * 100),
        "url": f"https://example.com/post/{index}",
        "permalink": f"https://reddit.com/comments/p{index}",
        "subreddit": "python",
    }


def _t1_data(tag: str, score: int, levels: int, now: float, n_replies: int = 6) -> dict:
    data = {
        "id": f"c{tag}",
        "author": f"commenter{tag}",
        "score": score,
        "created_utc": int(now) - score,
        "body": "b" * (100 + len(tag) * 3),
    }
    if levels > 0:
        replies = [
            {"kind": "t1", "data": _t1_data(f"{tag}.r{j}", score - j, levels - 1, now, n_replies)}
            for j in range(n_replies)
        ]
        data["replies"] = {"kind": "Listing", "data": {"children": replies, "after": None}}
    else:
        data["replies"] = None
    return data


@pytest.fixture
def tools():
    tool = Tools()
    tool.valves.client_id = "client-id"
    tool.valves.client_secret = "client-secret"
    tool.valves.username = "testuser"
    tool.valves.password = "testpass"
    return tool


@pytest.fixture
def make_response():
    def _make(status_code, payload, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.reason = _reason(status_code)
        resp.json.return_value = payload
        resp.headers = dict(headers or {})
        if status_code >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    return _make


@pytest.fixture
def subs_listing():
    def _make(names):
        return {
            "kind": "Listing",
            "data": {
                "children": [{"kind": "t2", "data": {"display_name": n}} for n in names],
                "after": None,
            },
        }

    return _make


@pytest.fixture
def feed_listing():
    def _make(now, posts, after=None):
        children = [{"kind": "t3", "data": _t3_data(i, now, age)} for i, age in posts]
        return {"kind": "Listing", "data": {"children": children, "after": after}}

    return _make


@pytest.fixture
def comment_tree():
    def _make(children=None):
        return [
            {"kind": "Listing", "data": {"children": []}},
            {"kind": "Listing", "data": {"children": children or []}},
        ]

    return _make


@pytest.fixture
def t1_child():
    def _make(tag, score, levels, now, n_replies=6):
        return _t1_data(tag, score, levels, now, n_replies)

    return _make


@pytest.fixture
def thread_children(t1_child):
    def _make(n_top, levels, now, n_replies=6):
        children = [{"kind": "t1", "data": t1_child(str(i), i + 1, levels, now, n_replies)} for i in range(n_top)]
        children.append({"kind": "more", "data": {"children": ["stub-1", "stub-2"]}})
        return children

    return _make
