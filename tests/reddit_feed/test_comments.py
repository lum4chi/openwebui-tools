"""Comment-crawl tests for the reddit_feed tool (S3, S4)."""

import json
import time
from unittest.mock import patch

import pytest


def _flatten(comments):
    nodes = []
    for comment in comments:
        nodes.append(comment)
        nodes.extend(_flatten(comment["replies"]))
    return nodes


def _node_count(comments):
    return len(_flatten(comments))


def _max_depth(comments):
    def depth(comment):
        return 1 + max((depth(reply) for reply in comment["replies"]), default=0)

    return max((depth(comment) for comment in comments), default=0)


# @unit
# Scenario: T1-1-S3 Comment threads are crawled bounded and ranked
#   # Provenance: AC-2 "deep comment-thread crawling: very often is the thread the real gold, rather than just first post."
#   Given a post whose thread has 20 top-level comments, each with 3 levels of replies
#   When the digest is built with comment_depth 2 and comments_per_thread 5
#   Then the post carries at most 5 comments in total
#   And the top-level comments are ranked by score descending
#   And no comment nests deeper than 2 levels
#   And every comment node carries author, score, created_utc, body and replies
#   And "more" stubs are not followed
async def test_crawl_bounded_ranked(tools, make_response, subs_listing, feed_listing, comment_tree, thread_children):
    tools.valves.comment_depth = 2
    tools.valves.comments_per_thread = 5
    now = time.time()
    subs = make_response(200, subs_listing(["python"]))
    feed = make_response(200, feed_listing(now, [(0, 60)]))
    tree = comment_tree(thread_children(20, 3, now))
    comment = make_response(200, tree)
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=[subs, feed, comment]),
    ):
        raw = await tools.get_home_feed()
    comments = json.loads(raw)["items"][0]["comments"]
    assert len(comments) == 1
    top = comments[0]
    assert top["score"] == 20
    assert [reply["score"] for reply in top["replies"]] == [20, 19, 18, 17]
    assert _node_count(comments) == 5
    assert _max_depth(comments) == 2
    for node in _flatten(comments):
        assert set(node.keys()) == {"author", "score", "created_utc", "body", "replies"}
        assert node["author"].startswith("u/")
    assert not any("stub" in node["author"] for node in _flatten(comments))


# @unit
# Scenario: T1-1-S4 Threads without comments degrade cleanly
#   # Provenance: AC-2 (edge: a post whose thread has no gold)
#   Given a post whose comment tree is empty
#   When the digest is built
#   Then the post's comments list is empty and the digest succeeds
#   # parametrize: empty forest; defensive 1-element response; null replies on every comment
@pytest.mark.parametrize("mode", ["empty-forest", "one-element", "null-replies"])
async def test_empty_thread(tools, make_response, subs_listing, feed_listing, comment_tree, t1_child, mode):
    now = time.time()
    if mode == "empty-forest":
        tree = comment_tree()
    elif mode == "one-element":
        tree = [{"kind": "Listing", "data": {"children": []}}]
    else:
        children = [{"kind": "t1", "data": t1_child(str(i), i + 1, 0, now)} for i in range(3)]
        tree = comment_tree(children)
    subs = make_response(200, subs_listing(["python"]))
    feed = make_response(200, feed_listing(now, [(0, 60)]))
    comment = make_response(200, tree)
    with (
        patch("requests.post", return_value=make_response(200, {"access_token": "tok-1"})),
        patch("requests.get", side_effect=[subs, feed, comment]),
    ):
        raw = await tools.get_home_feed()
    comments = json.loads(raw)["items"][0]["comments"]
    if mode in ("empty-forest", "one-element"):
        assert comments == []
    else:
        assert len(comments) == 3
        for node in comments:
            assert node["replies"] == []
