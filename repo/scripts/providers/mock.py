"""Mock provider for local testing — set "provider": "mock" in settings.json.
Generates deterministic fake tweets so fetch/build/email can be tested
without network access or spending API credit.
"""
from datetime import datetime, timedelta, timezone


def fetch_user_tweets(handle, max_pages=3, newer_than_id=None):
    now = datetime.now(timezone.utc)
    out = []
    for i in range(5):
        dt = now - timedelta(hours=i * 9 + hash(handle) % 7)
        out.append({
            "id": str(1_000_000 + abs(hash(handle)) % 100_000 + i),
            "url": f"https://x.com/{handle}/status/{1_000_000 + i}",
            "text": f"Mock tweet #{i + 1} from @{handle} — testing the digest "
                    f"pipeline. Link: https://example.com/{i}",
            "created_at": dt.isoformat(),
            "author_handle": handle,
            "author_name": handle.title(),
            "is_reply": False,
            "is_retweet": i == 3,
            "likes": 12 * (i + 1),
            "retweets": 3 * i,
            "media": [{"type": "photo", "url": "https://example.com/p.jpg"}] if i == 2 else [],
            "quoted": {"author": "someone", "text": "the quoted take"} if i == 1 else None,
        })
    return out


def fetch_followings(handle, max_pages=10):
    return [{"handle": f"mockuser{i}", "name": f"Mock User {i}", "bio": "bio",
             "followers": 100 * i, "following": 50, "tweets": 1000,
             "created_at": "2020-01-01T00:00:00Z", "verified": i % 2 == 0}
            for i in range(5)]
