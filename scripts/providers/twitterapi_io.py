"""Provider: twitterapi.io — read-only third-party X API.

This is the ONLY file that talks to the tweet-data service. If twitterapi.io
ever degrades or raises prices, write a sibling module exposing the same two
functions and switch config/settings.json "provider" to its name.

Auth: X-API-Key header, key from env TWITTERAPI_KEY.
Docs: https://docs.twitterapi.io
"""
import os
import time
import requests

BASE = "https://api.twitterapi.io"
KEY = os.environ.get("TWITTERAPI_KEY", "")


def _get(path, params, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(
                BASE + path,
                params=params,
                headers={"X-API-Key": KEY},
                timeout=30,
            )
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — fail-soft, caller logs
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"twitterapi.io request failed after {retries} tries: {last_err}")


def _norm_tweet(t, fallback_handle=""):
    """Normalise one tweet object defensively across schema variants."""
    author = t.get("author") or {}
    handle = author.get("userName") or author.get("username") or fallback_handle
    text = t.get("text") or t.get("fullText") or t.get("full_text") or ""
    tid = str(t.get("id") or t.get("id_str") or "")
    url = t.get("url") or t.get("twitterUrl") or (
        f"https://x.com/{handle}/status/{tid}" if tid else ""
    )
    created = t.get("createdAt") or t.get("created_at") or ""
    media = []
    ent = t.get("extendedEntities") or t.get("extended_entities") or {}
    for m in ent.get("media", []) or []:
        media.append({
            "type": m.get("type", "photo"),
            "url": m.get("media_url_https") or m.get("url") or "",
        })
    quoted = t.get("quoted_tweet") or t.get("quotedTweet") or t.get("quoted") or None
    return {
        "id": tid,
        "url": url,
        "text": text,
        "created_at": created,
        "author_handle": handle,
        "author_name": author.get("name") or "",
        "is_reply": bool(t.get("isReply") or t.get("in_reply_to_status_id")
                         or t.get("inReplyToId")),
        "is_retweet": bool(t.get("retweeted_tweet") or t.get("retweetedTweet")
                           or text.startswith("RT @")),
        "likes": t.get("likeCount") or t.get("favorite_count") or 0,
        "retweets": t.get("retweetCount") or t.get("retweet_count") or 0,
        "media": media,
        "quoted": {
            "author": ((quoted.get("author") or {}).get("userName") or ""),
            "text": quoted.get("text") or quoted.get("fullText") or "",
        } if isinstance(quoted, dict) else None,
    }


def _extract_tweets(payload):
    """Find the tweet list wherever this schema version put it."""
    if isinstance(payload, list):
        return payload
    for key in ("tweets", "data"):
        v = payload.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = v.get("tweets")
            if isinstance(inner, list):
                return inner
    return []


def fetch_user_tweets(handle, max_pages=3, newer_than_id=None):
    """Return normalised recent tweets for one user, newest first.

    Pages until max_pages, an empty page, or every tweet on a page is older
    than newer_than_id (tweet IDs are chronological).
    """
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"userName": handle}
        if cursor:
            params["cursor"] = cursor
        payload = _get("/twitter/user/last_tweets", params)
        raw = _extract_tweets(payload)
        if not raw:
            break
        page = [_norm_tweet(t, handle) for t in raw]
        out.extend(page)
        if newer_than_id and all(
            t["id"] and int(t["id"]) <= int(newer_than_id) for t in page if t["id"]
        ):
            break
        cursor = payload.get("next_cursor") or payload.get("cursor")
        if not cursor or not (payload.get("has_next_page") or payload.get("hasNextPage") or cursor):
            break
    return out


def fetch_followings(handle, max_pages=10):
    """Return the accounts `handle` follows, with profile metadata."""
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"userName": handle, "pageSize": 200}
        if cursor:
            params["cursor"] = cursor
        payload = _get("/twitter/user/followings", params)
        users = payload.get("followings") or payload.get("users") or _extract_tweets(payload)
        if not users:
            break
        for u in users:
            out.append({
                "handle": u.get("userName") or u.get("username") or "",
                "name": u.get("name") or "",
                "bio": (u.get("description") or "").replace("\n", " "),
                "followers": u.get("followers") or u.get("followersCount") or 0,
                "following": u.get("following") or u.get("followingCount") or 0,
                "tweets": u.get("statusesCount") or u.get("tweetsCount") or 0,
                "created_at": u.get("createdAt") or u.get("created_at") or "",
                "verified": bool(u.get("isBlueVerified") or u.get("verified")),
            })
        cursor = payload.get("next_cursor") or payload.get("cursor")
        if not cursor:
            break
    return out
