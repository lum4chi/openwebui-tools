"""Feed-structure, docstring-contract, pagination, read-only-surface, and pinning tests (S1, S2, S6, S7, S8)."""

import inspect
import json
import time
from unittest.mock import patch

import pytest

from reddit_feed import API, Tools

_ITEM_KEYS = {
    "subreddit",
    "title",
    "author",
    "score",
    "num_comments",
    "created_utc",
    "permalink",
    "url",
    "selftext",
    "comments",
}


# @unit
# Scenario: T1-1-S1 Home feed digest is structured for model presentation
#   # Provenance: AC-1 "digest my feed and present me a summary"
#   Given a tool with valid script-app OAuth valves
#   And the subscribed-subreddit union is non-empty
#   And the compound listing returns N posts, all within the last 24 hours
#   When get_home_feed() is called
#   Then the response parses as a JSON digest with window_hours 24
#   And it carries min(N, item_cap) items, newest first
#   And each item carries subreddit, title, author, score, num_comments, created_utc, permalink, url and selftext truncated to 500 characters
#   # parametrize (happy path): N=30 -> 25 items, N=5 -> 5 items
#   # SEPARATE deterministic case (owns the step-3 early return — NOT an empty listing):
#   # union EMPTY (subscriber endpoint returns no t2 children AND pinned_subreddits
#   # empty) -> empty digest AND the compound feed URL is NEVER requested.
#   # Mapping owner: test_feed.py::test_digest_structure[0]
@pytest.mark.parametrize("n_posts", [0, 30, 5], ids=["0", "30", "5"])
async def test_digest_structure(tools, make_response, subs_listing, feed_listing, comment_tree, n_posts):
    now = time.time()
    subs_payload = subs_listing([]) if n_posts == 0 else subs_listing(["python"])
    responses = [make_response(200, subs_payload)]
    if n_posts:
        posts = [(i, i * 30) for i in range(n_posts)]
        responses.append(make_response(200, feed_listing(now, posts)))
        for _ in range(min(n_posts, 25)):
            responses.append(make_response(200, comment_tree()))
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=responses) as mock_get,
    ):
        raw = await tools.get_home_feed()
    digest = json.loads(raw)
    assert digest["window_hours"] == 24
    assert digest["item_count"] == min(n_posts, 25)
    if n_posts == 0:
        assert digest["items"] == []
        assert mock_get.call_count == 1
    elif n_posts == 30:
        assert len(digest["items"]) == 25
        assert digest["items"][0]["title"] == "Post 0"
        assert digest["items"][24]["title"] == "Post 24"
        assert len(digest["items"][0]["selftext"]) == 50
        assert len(digest["items"][5]["selftext"]) == 500
        for item in digest["items"]:
            assert set(item.keys()) == _ITEM_KEYS
        assert digest["items"][0]["author"] == "u/author0"
        assert mock_get.call_count == 27
    else:
        assert len(digest["items"]) == 5
        assert mock_get.call_count == 7


# @unit
# Scenario: T1-1-S6 Time window and item cap bound the digest
#   # Provenance: AC-1; locked scope 1 knobs (time window default 24 h, item cap ~25)
#   Given a feed with 30 posts spanning 0 to 48 hours old
#   When the digest is built with a 24 hour window and item cap 25
#   Then posts older than 24 hours are excluded
#   And at most 25 items are returned
#   And pagination stops at the window boundary, at the page cap, or when the listing is exhausted
@pytest.mark.parametrize("mode", ["window-boundary", "page-cap"])
async def test_window_and_cap_filter(tools, make_response, subs_listing, feed_listing, comment_tree, mode):
    now = time.time()
    subs = make_response(200, subs_listing(["python"]))
    if mode == "window-boundary":
        page1 = make_response(200, feed_listing(now, [(0, 60), (1, 120)], after="a1"))
        page2 = make_response(200, feed_listing(now, [(2, 1380), (3, 1500)], after="a2"))
        pages = [page1, page2]
        n_comments = 3
        expected_titles = ["Post 0", "Post 1", "Post 2"]
        expected_calls = 6
    else:
        pages = []
        for k in range(5):
            posts = [(k * 3 + j, (k * 3 + j) * 30) for j in range(3)]
            pages.append(make_response(200, feed_listing(now, posts, after=f"a{k}")))
        n_comments = 15
        expected_titles = [f"Post {i}" for i in range(15)]
        expected_calls = 21
    comments = [make_response(200, comment_tree()) for _ in range(n_comments)]
    side_effect = [subs] + pages + comments
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=side_effect) as mock_get,
    ):
        raw = await tools.get_home_feed()
    digest = json.loads(raw)
    titles = [item["title"] for item in digest["items"]]
    assert titles == expected_titles
    assert mock_get.call_count == expected_calls


# @unit
# Scenario: T1-1-S8 Pinned subreddits are additively merged into the digest
#   # Provenance: locked scope 1 knob "pinned subreddits to include"; user-confirmed ADDITIVE —
#   # OPEN-1 resolved, user verbatim: "Additive" (pinned subreddits are added to the home feed; empty = plain home feed)
#   Given pinned_subreddits is set to "gaming,science"
#   When the digest is built
#   Then the feed listing includes r/gaming and r/science alongside the subscribed feed
#   And duplicate posts are removed by id
async def test_pinned_subreddits_merged(tools, make_response, subs_listing, feed_listing, comment_tree):
    tools.valves.pinned_subreddits = "gaming,science"
    now = time.time()
    subs = make_response(200, subs_listing(["python"]))
    feed = make_response(200, feed_listing(now, [(0, 60), (1, 120), (0, 180)]))
    comments = [make_response(200, comment_tree()) for _ in range(2)]
    side_effect = [subs, feed] + comments
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=side_effect) as mock_get,
    ):
        raw = await tools.get_home_feed()
    digest = json.loads(raw)
    assert digest["item_count"] == 2
    assert mock_get.call_args_list[1].args[0] == f"{API}/r/python+gaming+science/new"


# @unit
# Scenario: T1-1-S7 Read-only surface
#   # Provenance: locked scope 4 "Read-only, period"
#   Given the tool module
#   Then the only public tool method is get_home_feed
#   And no posting, commenting, voting or messaging operation exists
def test_read_only_surface():
    classes = [name for name, obj in vars(Tools).items() if inspect.isclass(obj) and not name.startswith("_")]
    functions = [name for name, obj in vars(Tools).items() if inspect.isfunction(obj) and not name.startswith("_")]
    assert classes == ["Valves"]
    assert functions == ["get_home_feed"]
    write_ops = {"post", "comment", "vote", "message", "delete", "submit"}
    assert not (write_ops & set(vars(Tools)))


# @unit
# Scenario: T1-1-S2 Digest presentation contract
#   # Provenance: AC-1 "…present me a summary"; locked scope 2 (docstring is the UX contract)
#   Given the get_home_feed tool method
#   When its docstring is inspected
#   Then it instructs the model to present a human-readable digest grouped by subreddit
#   And it mentions markdown links to permalinks, scores, top-comment highlights and "worth your time" picks
def test_docstring_contract():
    doc = Tools.get_home_feed.__doc__ or ""
    for phrase in [
        "HUMAN-READABLE DIGEST SUMMARY",
        "Group posts by subreddit",
        "markdown link to the permalink",
        "score, comment count",
        "top comment threads",
        "worth your time",
    ]:
        assert phrase in doc
