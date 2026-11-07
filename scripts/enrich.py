"""Make recent tweets readable without visiting X.

For every tweet from the last few days (runs after fetch.py):
  * every t.co short link gets its real destination (from the API's entities,
    or failing that by asking t.co where it redirects), so the digest can link
    straight to the article instead of through twitter's redirector;
  * any link to another tweet (that isn't already the quoted tweet) is fetched
    and stored under "linked", so the digest can show it inline.

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
DAYS = 6
MAX_RESOLVE = 600      # t.co lookups per run
MAX_FETCH = 200        # linked tweets fetched per run
VERSION = 1

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


def main():
    settings = load_settings()
    provider = importlib.import_module(f"providers.{settings['provider']}")
    cutoff = now_utc() - timedelta(days=DAYS)
    budget = [MAX_RESOLVE]
    todo = []                                   # (archive, tweet) needing work
    archives = {}

    for handle in load_accounts():
        arch = load_archive(handle)
        archives[handle] = arch
        for t in arch["tweets"].values():
            dt = parse_created(t.get("created_at"))
            if not dt or dt < cutoff or t.get("enriched") == VERSION:
                continue
            todo.append((handle, t))

    wanted = {}
    for handle, t in todo:
        links = t.setdefault("links", {})
        fill_links(t.get("text"), links, budget)
        q = t.get("quoted")
        if q:
            fill_links(q.get("text"), q.setdefault("links", {}), budget)
        own = {t.get("id"), t.get("rt_id"), (q or {}).get("id")}
        for dest in links.values():
            m = STATUS.match(dest or "")
            if m and m.group(1) not in own:
                wanted.setdefault(m.group(1), []).append(t)

    fetched, fetch_ok = {}, True
    ids = list(wanted)[:MAX_FETCH]
    if ids:
        try:
            fetched = provider.fetch_tweets_by_ids(ids)
        except Exception as e:  # noqa: BLE001
            fetch_ok = False
            print(f"  linked-tweet fetch failed: {e}", file=sys.stderr)

    for tid, tweets in wanted.items():
        lt = fetched.get(tid)
        if not lt:
            continue
        item = {k: lt.get(k) for k in ("id", "author_handle", "author_name",
                                        "text", "links", "media", "url")}
        for t in tweets:
            linked = t.setdefault("linked", [])
            if not any(x.get("id") == tid for x in linked):
                linked.append(item)

    done = 0
    for handle, t in todo:
        unresolved = [u for u in TCO.findall(t.get("text") or "")
                      if u not in t.get("links", {})]
        pending = [i for i, ts in wanted.items() if t in ts and i not in ids]
        if not unresolved and fetch_ok and not pending:
            t["enriched"] = VERSION
            done += 1
    for handle, arch in archives.items():
        save_archive(handle, arch)
    print(f"Enriched {done}/{len(todo)} tweets; {MAX_RESOLVE - budget[0]} t.co lookups; "
          f"{len(fetched)}/{len(ids)} linked tweets fetched.")


if __name__ == "__main__":
    main()
