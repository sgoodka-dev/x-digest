"""Shared helpers: config, archive IO, time parsing."""
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")
TWEETS_DIR = os.path.join(DATA_DIR, "tweets")
DOCS_DIR = os.path.join(ROOT, "docs")


def load_settings():
    with open(os.path.join(CONFIG_DIR, "settings.json"), encoding="utf-8") as f:
        return json.load(f)


def load_accounts():
    out = []
    with open(os.path.join(CONFIG_DIR, "accounts.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("@")
            if line and not line.startswith("#"):
                out.append(line)
    return out


def parse_created(s):
    """Parse the various date formats tweets arrive with -> aware UTC datetime."""
    if not s:
        return None
    try:  # ISO 8601
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        pass
    try:  # Twitter classic: 'Wed Oct 10 20:19:24 +0000 2018'
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc)
    except ValueError:
        pass
    try:  # RFC 2822
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def archive_path(handle):
    safe = re.sub(r"[^A-Za-z0-9_]", "_", handle)
    return os.path.join(TWEETS_DIR, f"{safe}.json")


def load_archive(handle):
    p = archive_path(handle)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"handle": handle, "tweets": {}}


def save_archive(handle, arch):
    os.makedirs(TWEETS_DIR, exist_ok=True)
    with open(archive_path(handle), "w", encoding="utf-8") as f:
        json.dump(arch, f, ensure_ascii=False, indent=1)


def load_status():
    p = os.path.join(DATA_DIR, "status.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_status(status):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


def now_utc():
    return datetime.now(timezone.utc)
