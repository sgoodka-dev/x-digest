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
            # Don't waste retries on a definitive client answer (e.g. 402/401/404)
            if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                r.raise_for_status()
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            if code and 400 <= code < 500 and code not in (408, 429):
                raise RuntimeError(f"twitterapi.io {code} for {path}: {str(e)[:150]}")
            last_err = e
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 — fail-soft, caller logs
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"twitterapi.io request failed after {retries} tries: {last_err}")


def _text(t):
    return t.get("text") or t.get("fullText") or t.get("full_text") or ""


def _media(t):
    out = []
    for container in (t.get("extendedEntities"), t.get("extended_entities"),
                      t.get("entities")):
        if isinstance(container, dict):
            for m in container.get("media", []) or []:
                out.append({"type": m.get("type", "photo"),
                            "url": m.get("media_url_https") or m.get("url") or ""})
    return out


def _norm_tweet(t, fallback_handle=""):
    """Normalise one tweet defensively. For reposts, store the FULL original
    text and the original author so the digest can show it in full."""
    author = t.get("author") or {}
    handle = author.get("userName") or author.get("username") or fallback_handle
    tid = str(t.get("id") or t.get("id_str") or "")
    url = t.get("url") or t.get("twitterUrl") or (
        f"https://x.com/{handle}/status/{tid}" if tid else "")

    rt = t.get("retweeted_tweet") or t.get("retweetedTweet")
    quoted = t.get("quoted_tweet") or t.get("quotedTweet") or t.get("quoted")

    is_retweet = bool(rt) or _text(t).startswith("RT @")
    if isinstance(rt, dict):
        # Full text + original author from the nested tweet
        rt_author_obj = rt.get("author") or {}
        rt_author = rt_author_obj.get("userName") or rt_author_obj.get("username") or ""
        rt_author_name = rt_author_obj.get("name") or ""
        display_text = _text(rt)
        media = _media(rt) or _media(t)
    else:
        rt_author = rt_author_name = ""
        display_text = _text(t)
        media = _media(t)

    return {
        "id": tid,
        "url": url,
        "text": display_text,
        "created_at": t.get("createdAt") or t.get("created_at") or "",
        "author_handle": handle,
        "author_name": author.get("name") or "",
        "is_reply": bool(t.get("isReply") or t.get("in_reply_to_status_id")
                         or t.get("inReplyToId")),
        "reply_to": t.get("inReplyToUsername") or "",
        "is_retweet": is_retweet,
        "rt_author": rt_author,
        "rt_author_name": rt_author_name,
        "likes": t.get("likeCount") or t.get("favorite_count") or 0,
        "retweets": t.get("retweetCount") or t.get("retweet_count") or 0,
        "media": media,
        "quoted": {
            "author": ((quoted.get("author") or {}).get("userName")
                       or (quoted.get("author") or {}).get("username") or ""),
            "text": _text(quoted),
        } if isinstance(quoted, dict) else None,
    }


def _extract_tweets(payload):
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


def fetch_user_tweets(handle, max_pages=3, newer_than_id=None,
                      include_replies=False):
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"userName": handle}
        if include_replies:
            params["includeReplies"] = "true"
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
        if not cursor or not (payload.get("has_next_page")
                              or payload.get("hasNextPage")):
            break
    return out


def fetch_followings(handle, max_pages=10):
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
