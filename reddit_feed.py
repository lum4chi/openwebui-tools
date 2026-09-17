"""
title: Reddit Feed Digest
author: lum4chi
author_url: https://github.com/lum4chi/openwebui-tools
description: Read-only Reddit home-feed digester. Authenticates via Reddit OAuth (script app), fetches the personal home feed, deep-crawls each post's comment thread (bounded, ranked by score), and returns structured JSON.
requirements: requests>=2.31.0
version: 1.0.0
licence: MIT
required_open_webui_version: 0.5.0

Agent instructions:
- get_home_feed() returns a JSON digest of the user's Reddit home feed for the configured time window.
- Present it as a HUMAN-READABLE DIGEST SUMMARY, not raw JSON:
  * Group posts by subreddit.
  * For each post: title as a markdown link to the permalink, score, comment count, one-line gist from selftext.
  * Highlight the top comment threads — the thread is often the real gold, not the post: quote the best 1-2 comments per post with author, and link the thread.
  * End with "worth your time" picks: the 3-5 posts whose threads deserve a full read.
"""

import json
import time
from datetime import UTC, datetime

import requests
from pydantic import BaseModel, Field

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
LIST_LIMIT = 100  # hard API max per page
MAX_FEED_PAGES = 5  # pagination bound (500 items max scanned)
TIMEOUT = 30  # seconds, every requests call


def rank_comment_tree(children: list[dict], max_depth: int, max_total: int) -> list[dict]:
    """Rank top-level t1 comments by score desc; keep total node count <= max_total,
    nesting depth <= max_depth; 'more' stubs and null replies stop the crawl."""
    top_level = [child for child in children if child["kind"] == "t1"]
    top_level.sort(key=lambda child: child["data"]["score"], reverse=True)
    ranked: list[dict] = []
    used = 0
    for child in top_level:
        if used >= max_total:
            break
        node, count = _comment_node(child["data"], max_depth - 1, max_total - used)
        ranked.append(node)
        used += count
    return ranked


def _comment_node(data: dict, depth: int, budget: int) -> tuple[dict, int]:
    """Builds one comment node + returns (node, nodes_used_incl_self). Replies ranked by
    score desc; budget exhausted → truncate remaining; depth 0 → leaf."""
    node = {
        "author": f"u/{data['author']}",
        "score": data["score"],
        "created_utc": data["created_utc"],
        "body": data["body"][:500],
        "replies": [],
    }
    if depth <= 0:
        return node, 1
    replies = data.get("replies")
    children = replies["data"]["children"] if isinstance(replies, dict) else []
    ranked = [child for child in children if child["kind"] == "t1"]
    ranked.sort(key=lambda child: child["data"]["score"], reverse=True)
    used = 1
    for child in ranked:
        if used >= budget:
            break
        reply, count = _comment_node(child["data"], depth - 1, budget - used)
        node["replies"].append(reply)
        used += count
    return node, used


def _http_error_detail(error: requests.HTTPError) -> tuple[int, str]:
    """(status, reason) of the failed response, (0, '') when it carries none —
    pinned None-safe: robust to any stub interpretation of HTTPError.response."""
    response = error.response
    if response is None:
        return 0, ""
    return response.status_code, response.reason


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        self.citation = False

    class Valves(BaseModel):
        client_id: str = Field(default="", description="Reddit OAuth client id (script app)")
        client_secret: str = Field(default="", description="Reddit OAuth client secret (script app)")
        username: str = Field(default="", description="Reddit username")
        password: str = Field(default="", description="Reddit password (app password if 2FA is on)")
        pinned_subreddits: str = Field(
            default="", description="Comma-separated extra subreddits to include, e.g. 'gaming,science'"
        )
        time_window_hours: int = Field(default=24, description="Only include posts newer than this many hours")
        item_cap: int = Field(default=25, description="Maximum feed items in the digest")
        comment_depth: int = Field(default=2, description="Maximum reply nesting depth crawled per thread")
        comments_per_thread: int = Field(default=15, description="Maximum comments kept per thread")

    async def get_home_feed(self) -> str:
        """
        Fetch the user's Reddit home feed and return a structured JSON digest for the configured time window.

        Present the result as a HUMAN-READABLE DIGEST SUMMARY, not raw JSON:
        - Group posts by subreddit.
        - For each post: title as a markdown link to the permalink, score, comment count, one-line gist from selftext.
        - Highlight the top comment threads — the thread is often the real gold, not the post: quote the best 1-2 comments per post with author, and link the thread.
        - End with "worth your time" picks: the 3-5 posts whose threads deserve a full read.
        """
        if not (self.valves.client_id and self.valves.client_secret and self.valves.username and self.valves.password):
            return "Reddit OAuth valves are not configured. Set client id, client secret, username and password."
        try:
            token = self._fetch_token()
        except requests.HTTPError as e:
            status, _ = _http_error_detail(e)
            return f"Reddit authentication failed ({status}): check the OAuth valves."
        except requests.RequestException as e:
            return f"Reddit request failed: {e}"
        try:
            subs = self._subscribed_subreddits(token)
            for name in self.valves.pinned_subreddits.split(","):
                name = name.strip()
                if name and name not in subs:
                    subs.append(name)
            if not subs:
                return json.dumps(self._digest([]), indent=2)
            items = self._fetch_feed_items(token, subs)
            for item in items:
                item["comments"] = self._fetch_comments(token, item)
            return json.dumps(self._digest(items), indent=2)
        except requests.HTTPError as e:
            status, reason = _http_error_detail(e)
            return f"Reddit API error ({status}): {reason}"
        except requests.RequestException as e:
            return f"Reddit request failed: {e}"

    def _user_agent(self) -> str:
        return f"openwebui:reddit-feed-digest:1.0.0 (by /u/{self.valves.username})"

    def _fetch_token(self) -> str:
        resp = requests.post(
            TOKEN_URL,
            auth=(self.valves.client_id, self.valves.client_secret),
            data={"grant_type": "password", "username": self.valves.username, "password": self.valves.password},
            headers={"User-Agent": self._user_agent()},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _request(self, token: str, url: str, params: dict | None = None) -> requests.Response:
        headers = {"User-Agent": self._user_agent(), "Authorization": f"Bearer {token}"}
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 429:
            delay = min(int(resp.headers.get("Retry-After") or 0), 30)
            time.sleep(delay)
            resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp

    def _subscribed_subreddits(self, token: str) -> list[str]:
        resp = self._request(token, f"{API}/subreddits/mine/subscriber", {"limit": LIST_LIMIT, "raw_json": 1})
        children = resp.json()["data"]["children"]
        return [child["data"]["display_name"] for child in children if child["kind"] == "t2"]

    def _fetch_feed_items(self, token: str, subs: list[str]) -> list[dict]:
        url = f"{API}/r/{'+'.join(subs)}/new"
        cutoff = time.time() - self.valves.time_window_hours * 3600
        items: list[dict] = []
        seen: set[str] = set()
        after: str | None = None
        for _ in range(MAX_FEED_PAGES):
            params: dict[str, int | str] = {"limit": LIST_LIMIT, "raw_json": 1}
            if after:
                params["after"] = after
            listing = self._request(token, url, params).json()["data"]
            children = [child["data"] for child in listing["children"] if child["kind"] == "t3"]
            for item in children:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
            if not listing.get("after") or (children and children[-1]["created_utc"] < cutoff):
                break
            after = listing["after"]
        fresh = [item for item in items if item["created_utc"] >= cutoff]
        return fresh[: self.valves.item_cap]

    def _fetch_comments(self, token: str, item: dict) -> list[dict]:
        url = f"{API}/r/{item['subreddit']}/comments/{item['id']}"
        params = {
            "limit": self.valves.comments_per_thread,
            "depth": self.valves.comment_depth,
            "sort": "top",
            "raw_json": 1,
        }
        tree = self._request(token, url, params).json()
        children = tree[1]["data"]["children"] if isinstance(tree, list) and len(tree) > 1 else []
        return rank_comment_tree(children, self.valves.comment_depth, self.valves.comments_per_thread)

    def _digest(self, items: list[dict]) -> dict:
        return {
            "window_hours": self.valves.time_window_hours,
            "generated_utc": datetime.now(UTC).isoformat(),
            "item_count": len(items),
            "items": [self._shape_item(item) for item in items],
        }

    def _shape_item(self, raw: dict) -> dict:
        return {
            "subreddit": raw["subreddit"],
            "title": raw["title"],
            "author": f"u/{raw['author']}",
            "score": raw["score"],
            "num_comments": raw["num_comments"],
            "created_utc": raw["created_utc"],
            "permalink": raw["permalink"],
            "url": raw["url"],
            "selftext": raw["selftext"][:500],
            "comments": raw["comments"],
        }
