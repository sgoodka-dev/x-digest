"""Fetch new tweets for every account in config/accounts.txt into data/tweets/.

Fail-soft: one account erroring never stops the run. Errors land in
data/status.json and surface on the dashboard.
"""
import importlib
import sys
import traceback

from common import (load_accounts, load_settings, load_archive, save_archive,
                    load_status, save_status, parse_created, now_utc)


def main():
    settings = load_settings()
    provider = importlib.import_module(f"providers.{settings['provider']}")
    accounts = load_accounts()
    status = load_status()
    run = {"started": now_utc().isoformat(), "accounts": {}, "new_tweets": 0}

    for handle in accounts:
        try:
            arch = load_archive(handle)
            known = arch["tweets"]
            newest_known = max(
                (int(i) for i in known.keys() if i.isdigit()), default=None
            )
            tweets = provider.fetch_user_tweets(
                handle,
                max_pages=settings.get("max_pages_per_account", 3),
                newer_than_id=newest_known,
                include_replies=bool(settings.get("include_replies")),
            )
            added = 0
            for t in tweets:
                # When we first saw it: lets the email include everything
                # collected since the last digest, even if a run ran late.
                t["fetched_at"] = run["started"]
                if not t["id"] or t["id"] in known:
                    continue
                if t["is_reply"] and not settings.get("include_replies"):
                    continue
                if t["is_retweet"] and not settings.get("include_retweets", True):
                    continue
                if not parse_created(t["created_at"]):
                    continue
                known[t["id"]] = t
                added += 1
            save_archive(handle, arch)
            run["accounts"][handle] = {"ok": True, "new": added,
                                       "total": len(known)}
            run["new_tweets"] += added
            print(f"  {handle}: +{added} (total {len(known)})")
        except Exception as e:  # noqa: BLE001
            run["accounts"][handle] = {"ok": False, "error": str(e)[:300]}
            print(f"  {handle}: FAILED — {e}", file=sys.stderr)
            traceback.print_exc()

    run["finished"] = now_utc().isoformat()
    status["last_run"] = run
    save_status(status)

    ok = sum(1 for a in run["accounts"].values() if a.get("ok"))
    print(f"Done: {ok}/{len(accounts)} accounts ok, {run['new_tweets']} new tweets.")
    if ok == 0 and accounts:
        sys.exit(1)  # total failure -> fail the workflow so GitHub emails you


if __name__ == "__main__":
    main()
