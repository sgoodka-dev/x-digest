"""Make recent tweets readable without visiting X.

For every tweet from the last few days (runs after fetch.py):
  * every t.co short link gets its real destination (from the API's entities,
    or failing that by asking t.co where it redirects), so the digest can link
    straight to the article instead of through twitter's redirector;
  * any link to another tweet (that isn't already the quoted tweet) is fetched
    and stored under "linked", so the digest can show it inline;
  * a reply gets the tweet it answers, stored under "parent";
  * a post or repost that starts a thread (🧵 / "1/" / the author replied to
    it themselves) gets the author's follow-on tweets, stored under "thread".

Fail-soft: anything that goes wrong is logged and skipped; the next run retries.
"""
import importlib
import re
import sys
from datetime import timedelta

import requests

from common import (load_accounts, load_settings, load_archive, save_archive,
                    parse_created, now_utc)

TCO = re.compile(r"https?://t\.co/\w+")
STATUS = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status(?:es)?/(\d+)")
THREAD_HINT = re.compile(r"🧵|👇|\ba thread\b|^thread\b|(?:^|\s)\(?1\s?/\s?\d*\)?(?=\s|$)",
                         re.I | re.M)
DAYS = 6
MAX_RESOLVE = 600      # t.co lookups per run
MAX_FETCH = 300        # linked + parent tweets fetched per run
MAX_THREADS = 20       # threads walked per run
MAX_THREAD_CALLS = 12  # API calls per thread (one per post, roughly)
MAX_THREAD_LEN = 25
VERSION = 3

_cache = {}


def resolve(u):
    """Where a t.co link points, without following it any further."""
    if u in _cache:
        return _cache[u]
    dest = None
    try:
        r = requests.get(u, allow_redirects=False, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 (digest link check)"})
        dest = r.headers.get("Location")
        if not dest and r.ok:
            m = (re.search(r'URL=([^"\'>]+)', r.text, re.I)
                 or re.search(r'location\.replace\("([^"]+)"\)', r.text))
            dest = m.group(1).replace("\\/", "/") if m else None
    except Exception as e:  # noqa: BLE001
        print(f"  resolve failed {u}: {e}", file=sys.stderr)
    _cache[u] = dest
    return dest


def fill_links(text, links, budget):
    for u in TCO.findall(text or ""):
        if u in links or budget[0] <= 0:
            continue
        budget[0] -= 1
        dest = resolve(u)
        if dest:
            # a link to the tweet's own photo/video: image is shown already
            links[u] = "" if re.search(r"/(photo|video)/\d+$", dest) else dest


def slim(t):
    """The parts of a fetched tweet the digest shows inline."""
    return {k: t.get(k) for k in ("id", "author_handle", "author_name", "text",
                                  "links", "media", "url", "created_at")}


def _next_post(pool, cur, author, seen):
    """The author's own reply to tweet `cur`, if we've seen one."""
    cands = [t for t in pool.values()
             if (t.get("author_handle") or "").lower() == author
             and t.get("reply_to_id") == cur and t["id"] not in seen]
    cands.sort(key=lambda t: parse_created(t.get("created_at")) or now_utc())
    return cands[0] if cands else None


def author_chain(provider, root_id, author):
    """Walk down the author's own replies from root_id: the thread.
    The API returns a tweet's direct replies, so we step one post at a time."""
    author = (author or "").lower()
    pool, chain, cur, seen, calls = {}, [], root_id, {root_id}, 0
    while len(chain) < MAX_THREAD_LEN:
        nxt = _next_post(pool, cur, author, seen)
        if not nxt:
            if calls >= MAX_THREAD_CALLS:
                break
            calls += 1
            for t in provider.fetch_thread(cur, max_pages=2):
                if t.get("id"):
                    pool.setdefault(t["id"], t)
            nxt = _next_post(pool, cur, author, seen)
            if not nxt:
                break
        chain.append(slim(nxt))
        cur = nxt["id"]
        seen.add(cur)
    print(f"  thread {root_id} @{author}: {len(chain)} more posts "
          f"({calls} calls, {len(pool)} tweets seen)")
    return chain


def main():
    settings = load_settings()
    provider = importlib.import_module(f"providers.{settings['provider']}")
    cutoff = now_utc() - timedelta(days=DAYS)
    budget = [MAX_RESOLVE]
    archives, todo = {}, []
    self_replied = set()          # (author, tweet id) the author replied to

    for handle in load_accounts():
        arch = load_archive(handle)
        archives[handle] = arch
        for t in arch["tweets"].values():
            if (t.get("is_reply") and t.get("reply_to_id")
                    and (t.get("reply_to") or "").lower() == handle.lower()):
                self_replied.add((handle.lower(), t["reply_to_id"]))
            dt = parse_created(t.get("created_at"))
            if dt and dt >= cutoff and t.get("enriched") != VERSION:
                todo.append(t)

    failed = set()                # tweet ids whose work didn't finish
    wanted = {}                   # tweet id to fetch -> [(tweet, kind)]
    for t in todo:
        links = t.setdefault("links", {})
        fill_links(t.get("text"), links, budget)
        q = t.get("quoted")
        if q:
            fill_links(q.get("text"), q.setdefault("links", {}), budget)
        if TCO.search(t.get("text") or "") and any(
                u not in links for u in TCO.findall(t.get("text") or "")):
            failed.add(t["id"])
        own = {t.get("id"), t.get("rt_id"), (q or {}).get("id")}
        for dest in links.values():
            m = STATUS.match(dest or "")
            if m and m.group(1) not in own:
                wanted.setdefault(m.group(1), []).append((t, "linked"))
        if (t.get("is_reply") and not t.get("is_retweet") and t.get("reply_to_id")
                and not t.get("parent")):
            wanted.setdefault(t["reply_to_id"], []).append((t, "parent"))

    # linked tweets and reply parents, fetched in batches
    ids = list(wanted)[:MAX_FETCH]
    fetched = {}
    if ids:
        try:
            fetched = provider.fetch_tweets_by_ids(ids)
        except Exception as e:  # noqa: BLE001
            print(f"  tweet fetch failed: {e}", file=sys.stderr)
            for i in ids:
                failed.update(t["id"] for t, _ in wanted[i])
    for i, uses in wanted.items():
        if i not in ids:
            failed.update(t["id"] for t, _ in uses)
            continue
        ft = fetched.get(i)
        if not ft:
            continue                          # deleted / private: nothing to show
        item = slim(ft)
        for t, kind in uses:
            if kind == "parent":
                t["parent"] = item
            elif not any(x.get("id") == i for x in t.setdefault("linked", [])):
                t["linked"].append(item)

    # threads
    threads, chains = 0, {}
    for t in todo:
        if t.get("is_reply") and not t.get("is_retweet"):
            continue
        root = t.get("rt_id") if t.get("is_retweet") else t.get("id")
        author = t.get("rt_author") if t.get("is_retweet") else t.get("author_handle")
        if not root:
            continue
        if not (THREAD_HINT.search(t.get("text") or "")
                or ((author or "").lower(), root) in self_replied):
            continue
        if root in chains:                 # same thread reposted by someone else
            t["thread"] = chains[root]
            continue
        if threads >= MAX_THREADS:
            failed.add(t["id"])
            continue
        threads += 1
        try:
            chain = chains[root] = author_chain(provider, root, author)
            for c in chain:
                fill_links(c.get("text"), c.setdefault("links", {}) or {}, budget)
            t["thread"] = chain
        except Exception as e:  # noqa: BLE001
            print(f"  thread fetch failed for {root}: {e}", file=sys.stderr)
            failed.add(t["id"])

    done = 0
    for t in todo:
        if t["id"] not in failed:
            t["enriched"] = VERSION
            done += 1
    for handle, arch in archives.items():
        save_archive(handle, arch)
    print(f"Enriched {done}/{len(todo)} tweets; {MAX_RESOLVE - budget[0]} t.co lookups; "
          f"{len(fetched)}/{len(ids)} linked/parent tweets; {threads} threads.")


if __name__ == "__main__":
    main()
