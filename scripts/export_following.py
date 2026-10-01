"""One-off: export the full list of accounts you follow to data/following.csv.

Run from the 'Export following list' workflow in the Actions tab.
"""
import csv
import importlib
import os

from common import DATA_DIR, load_settings


def main():
    settings = load_settings()
    provider = importlib.import_module(f"providers.{settings['provider']}")
    users = provider.fetch_followings(settings["owner_handle"])
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "following.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["handle", "name", "bio", "followers",
                                          "following", "tweets", "created_at",
                                          "verified"])
        w.writeheader()
        w.writerows(users)
    print(f"Exported {len(users)} followed accounts to {path}")


if __name__ == "__main__":
    main()
