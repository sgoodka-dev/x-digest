"""Build the X digest email (run by the scheduled Claude task, not by GitHub).

Usage: python3 digest_email.py IDX_HTML ACCOUNTS_TXT OUT_DIR [NOW_ISO]

Reads the tweets embedded in docs/index.html, keeps everything collected since
the previous digest, applies the per-person caps and writes OUT_DIR/body.html
and OUT_DIR/subj.txt. Prints COUNT= and WARN= lines for the task to act on.

Rules (Shahil's spec):
  * Digest goes out Sun, Tue, Fri (Substack digest covers Mon, Thu, Sat),
    so each digest covers everything since the previous digest day at 18:20.
  * Per person: at most 3 posts + 1 reply + 1 repost, each sorted by likes.
  * At most one reply per source tweet.
  * A repost of another followed account is dropped — the original shows
    under its own author instead.
"""
import datetime
import html
import json
import re
import sys
from zoneinfo import ZoneInfo

EXCLUDE = {"matthewclifford", "thezvi"}
RUN_WEEKDAYS = {6, 1, 4}             # Python weekday(): Sun, Tue, Fri
BOUNDARY = (18, 20)                  # UK time the digest window closes
CAP_POSTS, CAP_REPLIES, CAP_REPOSTS = 3, 1, 1

LON = ZoneInfo("Europe/London")
UTC = datetime.timezone.utc


def pd(s):
    try:
        d = datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        return None


def window(now):
    loc = now.astimezone(LON)
    end = loc.replace(hour=BOUNDARY[0], minute=BOUNDARY[1], second=0, microsecond=0)
    if end > loc:
        end -= datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=1)
    for _ in range(7):                       # back to the previous digest day
        if start.weekday() in RUN_WEEKDAYS:
            break
        start -= datetime.timedelta(days=1)
    start = start.replace(hour=BOUNDARY[0], minute=BOUNDARY[1])
    # Last daily-schedule digest went out Mon 2 Nov 2026; don't repeat it.
    start = max(start, datetime.datetime(2026, 11, 2, 18, 20, tzinfo=LON))
    return start.astimezone(UTC), end.astimezone(UTC)


def esc(s):
    return html.escape(s or "", quote=True)


URL_RE = re.compile(r"https?://[^\s<]+")
STATUS_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status(?:es)?/(\d+)")


def body_text(s, links=None, shown_ids=()):
    """Tweet text -> HTML. t.co links become their real destination; links to
    the tweet's own media or to tweets already shown inline are dropped."""
    links = links or {}
    out, last = [], 0
    for m in URL_RE.finditer(s or ""):
        out.append(esc(s[last:m.start()]))
        last = m.end()
        u = m.group(0)
        if u in links:
            dest = links[u]
            sm = STATUS_RE.match(dest or "")
            if not dest or (sm and sm.group(1) in shown_ids):
                continue
            u = dest
        shown = re.sub(r"^https?://(www\.)?", "", u)
        if len(shown) > 32:
            shown = shown[:30] + "…"
        out.append(f"<a href='{esc(u)}'>{esc(shown)}</a>")
    out.append(esc((s or "")[last:]))
    txt = "".join(out).strip()
    txt = re.sub(r"(?<![\w/'>])@(\w{1,15})",
                 r"<a href='https://x.com/\1'>@\1</a>", txt)
    return txt.replace("\n", "<br>")


def clip(s, n=280):
    s = s or ""
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


def num(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n/1000:.1f}K".replace(".0K", "K")
    return str(n)


PALETTE = ["#1d9bf0", "#7856ff", "#f91880", "#00ba7c", "#ff7a00", "#536471"]


def avatar(url, name):
    if url:
        return f"<img class=av src='{esc(url)}' width=40 height=40 alt=''>"
    initial = esc((name or "?").strip()[:1].upper() or "?")
    colour = PALETTE[sum(map(ord, name or "?")) % len(PALETTE)]
    return f"<div class=avl style='background:{colour}'>{initial}</div>"


def embed(e, cls="q"):
    """A quoted, linked or replied-to tweet, shown in full inside the card."""
    name = e.get("author_name")
    head = (f"<b>{esc(name)}</b> <span class=g>@{esc(e.get('author'))}</span>"
            if name else f"<b>@{esc(e.get('author'))}</b>")
    img = ""
    pics = [m for m in (e.get("media") or []) if m.get("url")]
    if pics:
        img = (f"<a href='{esc(pics[0]['url'])}'><img class=med "
               f"src='{esc(pics[0]['url'])}' alt=''></a>")
    return (f"<div class={cls}>{head}<br>{body_text(e.get('text'), e.get('links'))}"
            f"{img}</div>")


def as_embed(x):
    return {"id": x.get("id"), "author": x.get("author_handle"),
            "author_name": x.get("author_name"), "text": x.get("text"),
            "links": x.get("links"), "media": x.get("media")}


def thread_html(items):
    """The author's follow-on tweets, each in full, under the first one."""
    if not items:
        return ""
    parts = [f"<div class=thh>&#129525; Thread &#183; {len(items)} more "
             f"post{'s' if len(items) != 1 else ''}</div>"]
    for i, x in enumerate(items, 2):
        pics = [m for m in (x.get("media") or []) if m.get("url")]
        img = (f"<a href='{esc(pics[0]['url'])}'><img class=med "
               f"src='{esc(pics[0]['url'])}' alt=''></a>") if pics else ""
        parts.append(f"<div class=th><span class=g>{i}/</span> "
                     f"{body_text(x.get('text'), x.get('links'))}{img}</div>")
    return "".join(parts)


def card(t):
    rt = t.get("is_retweet")
    top = ""
    if rt:
        name = t.get("rt_author_name") or t.get("rt_author") or ""
        handle = t.get("rt_author") or ""
        av = avatar(t.get("rt_avatar"), name)
        top = f"<div class=lab>&#8635; {esc(t.get('author_name') or t.get('author_handle'))} reposted</div>"
    else:
        name = t.get("author_name") or t.get("author_handle")
        handle = t.get("author_handle")
        av = avatar(t.get("avatar"), name)
    when = pd(t["created_at"]).astimezone(LON).strftime("%a %-d %b · %H:%M")
    reply = ""
    if t.get("is_reply") and not rt:
        to = t.get("reply_to")
        reply = (f"<div class=rep>Replying to <span class=bl>@{esc(to)}</span></div>"
                 if to else "<div class=rep>Reply</div>")
        if t.get("parent") and t["parent"].get("text"):
            reply += embed(as_embed(t["parent"]), "pa")
    text = t.get("text") or ""
    if t.get("is_reply") and not rt:          # X hides the leading @handles
        text = re.sub(r"^(@\w{1,15}\s+)+", "", text) or text
    embeds = []
    if t.get("quoted") and t["quoted"].get("text"):
        embeds.append(t["quoted"])
    for lt in t.get("linked") or []:
        if lt.get("text") and all(lt.get("id") != e.get("id") for e in embeds):
            embeds.append(as_embed(lt))
    shown_ids = {e.get("id") for e in embeds if e.get("id")}
    q = "".join(embed(e) for e in embeds)
    media = ""
    imgs = [m for m in (t.get("media") or []) if m.get("url")]
    if imgs:
        m = imgs[0]
        tag = "&#9654; Video" if m.get("type") in ("video", "animated_gif") else ""
        more = f"+{len(imgs)-1} more" if len(imgs) > 1 else ""
        cap = " · ".join(x for x in (tag, more) if x)
        media = (f"<a href='{esc(m['url'])}'><img class=med src='{esc(m['url'])}' alt=''></a>"
                 + (f"<div class=mc>{cap}</div>" if cap else ""))
    return (
        f"<div class=t>{top}<table cellpadding=0 cellspacing=0 width='100%'><tr>"
        f"<td class=al valign=top>{av}</td><td valign=top>"
        f"<div class=hd><b class=nm>{esc(name)}</b> <span class=g>@{esc(handle)} · {when}</span></div>"
        f"{reply}<div class=tx>{body_text(text, t.get('links'), shown_ids)}</div>{media}{q}"
        f"{thread_html(t.get('thread'))}"
        f"<div class=ft><span class=lk>&#9829; {num(t.get('likes'))}</span>"
        f"<span class=rt>&#8635; {num(t.get('retweets'))}</span>"
        f"<a href='{esc(t.get('url'))}'>Open on X &#8599;</a></div>"
        f"</td></tr></table></div>"
    )


FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
LINK = "color:#1d9bf0;text-decoration:none"
BUDGET = 120_000   # max email size in bytes; lowest-liked items dropped beyond this

# Mail apps (Yahoo, Gmail) strip <style> blocks, so every style is inlined.
STYLES = {
    "d": f"font-family:{FONT};max-width:600px;margin:0 auto;padding:16px 12px;color:#0f1419",
    "sec": "margin:26px 0 10px;font-size:13px;color:#536471",
    "secb": "font-size:16px;color:#0f1419",
    "t": "background:#fff;border:1px solid #e1e8ed;border-radius:16px;"
         "padding:12px 16px;margin:0 0 10px;font-size:15px;line-height:21px;color:#0f1419",
    "lab": "font-size:13px;color:#536471;font-weight:600;margin:0 0 6px 52px",
    "al": "width:52px",
    "av": "width:40px;height:40px;border-radius:50%;display:block",
    "avl": "width:40px;height:40px;border-radius:50%;color:#fff;"
           "font-weight:700;font-size:18px;line-height:40px;text-align:center",
    "hd": "line-height:20px",
    "nm": "",
    "g": "color:#536471",
    "rep": "font-size:14px;color:#536471;margin-top:2px",
    "bl": "color:#1d9bf0",
    "tx": "margin-top:4px;word-wrap:break-word",
    "med": "display:block;width:100%;max-width:520px;border-radius:14px;margin-top:10px",
    "mc": "font-size:12px;color:#536471;margin-top:4px",
    "q": "border:1px solid #cfd9de;border-radius:14px;padding:10px 12px;margin-top:10px;"
         "font-size:14px;line-height:19px",
    "ft": "margin-top:10px;font-size:13px;color:#536471",
    "pa": "background:#f7f9f9;border:1px solid #e1e8ed;border-radius:14px;"
          "padding:10px 12px;margin:6px 0 8px;font-size:14px;line-height:19px;color:#536471",
    "thh": "margin-top:12px;font-size:13px;font-weight:600;color:#536471",
    "th": "border-top:1px solid #eff3f4;padding-top:8px;margin-top:8px;word-wrap:break-word",
    "lk": "color:#f91880;margin-right:16px",
    "rt": "color:#00ba7c;margin-right:16px",
    "op": LINK + ";font-size:13px",
}


def inline(body):
    def sub(m):
        css = STYLES.get(m.group(1), "")
        if not css and not m.group(2):
            return ""
        if m.group(2):
            css = css + ";" + m.group(2)
        return f"style=\"{css}\""
    body = re.sub(r"class=(\w+)(?: style='([^']*)')?", sub, body)
    # any link without its own style gets X blue (stops purple visited links)
    return re.sub(r"<a href=", f"<a style=\"{LINK}\" href=", body)


def main():
    idx, accounts_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    now = pd(sys.argv[4]) if len(sys.argv) > 4 else datetime.datetime.now(UTC)
    h = open(idx, encoding="utf-8").read()
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', h, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</")) if m else []
    followed = set()
    try:
        for line in open(accounts_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                followed.add(line.lstrip("@").lower())
    except OSError:
        pass
    followed |= {(t.get("author_handle") or "").lower() for t in data}

    start, end = window(now)

    def keep(t):
        if (t.get("author_handle") or "").lower() in EXCLUDE:
            return False
        c = pd(t.get("created_at"))
        if not c:
            return False
        f = pd(t.get("fetched_at"))
        if f:
            return start < f <= end and c >= now - datetime.timedelta(days=5)
        return start < c <= end

    seen, rows = set(), []
    for t in data:
        if keep(t) and t.get("id") not in seen:
            seen.add(t.get("id"))
            rows.append(t)

    by = {}
    for t in rows:
        by.setdefault(t["author_handle"], []).append(t)

    likes = lambda t: int(t.get("likes") or 0)  # noqa: E731
    in_threads = {x.get("id") for t in rows for x in (t.get("thread") or [])}
    order = sorted(by, key=lambda a: max(pd(t["created_at"]) for t in by[a]), reverse=True)
    picks = {}
    for hdl in order:
        ts = by[hdl]
        posts = [t for t in ts if not t.get("is_retweet") and not t.get("is_reply")]
        replies = [t for t in ts if t.get("is_reply") and not t.get("is_retweet")
                   and t.get("id") not in in_threads]
        reposts = [t for t in ts if t.get("is_retweet")
                   and (t.get("rt_author") or "").lower() not in followed]
        best = {}
        for r in sorted(replies, key=likes, reverse=True):
            key = r.get("reply_to_id") or ("@" + (r.get("reply_to") or r.get("id") or ""))
            best.setdefault(key, r)
        chosen = (sorted(posts, key=likes, reverse=True)[:CAP_POSTS]
                  + sorted(best.values(), key=likes, reverse=True)[:CAP_REPLIES]
                  + sorted(reposts, key=likes, reverse=True)[:CAP_REPOSTS])
        if chosen:
            picks[hdl] = chosen

    # Keep the email under BUDGET so it can be sent in one piece: drop the
    # lowest-liked reposts, then replies, then posts, until it fits.
    cards = {t["id"]: inline(card(t)) for ts in picks.values() for t in ts}
    size = sum(len(c.encode()) for c in cards.values()) + 400 * len(picks) + 2000
    rank = lambda t: (0 if t.get("is_retweet") else 1 if t.get("is_reply") else 2,  # noqa: E731
                      likes(t))
    pool = sorted((t for ts in picks.values() for t in ts), key=rank)
    while size > BUDGET and pool:
        t = pool.pop(0)
        picks[t["author_handle"]].remove(t)
        size -= len(cards[t["id"]].encode())
        if not picks[t["author_handle"]]:
            del picks[t["author_handle"]]
            size -= 400

    sections, shown_total, hidden_total = [], 0, 0
    for hdl in order:
        if hdl not in picks:
            hidden_total += len(by[hdl])
            continue
        ts, chosen = by[hdl], picks[hdl]
        hidden = len(ts) - len(chosen)
        shown_total += len(chosen)
        hidden_total += hidden
        nm = esc(ts[0].get("author_name") or hdl)
        extra = f" · {len(chosen)} of {len(ts)}" if hidden else ""
        sections.append(
            inline(f"<div class=sec><b class=secb>{nm}</b> <a href='https://x.com/{esc(hdl)}'>@{esc(hdl)}</a>{extra}</div>")
            + "".join(cards[t["id"]] for t in chosen))

    warn = ""
    um = re.search(r"updated (\d\d \w{3} \d{4}, \d\d:\d\d) UTC", h)
    upd = (datetime.datetime.strptime(um.group(1), "%d %b %Y, %H:%M").replace(tzinfo=UTC)
           if um else None)
    if not upd or (end - upd).total_seconds() > 10 * 3600:
        when = upd.astimezone(LON).strftime("%a %d %b %H:%M") if upd else "unknown"
        warn = ("<div class=t style='background:#fff4e5;color:#8a4b00;font-size:14px'>"
                f"Heads-up: tweet collection last ran {when} (UK). This digest may be "
                "incomplete &#8212; anything missed will appear in the next one.</div>")

    ds = end.astimezone(LON).strftime("%A %-d %B")
    since = start.astimezone(LON).strftime("%A")
    na = len(sections)
    tws = "tweet" if shown_total == 1 else "tweets"
    acc = "account" if na == 1 else "accounts"
    trimmed = f" · {hidden_total} lower-liked hidden" if hidden_total else ""
    body = (
        "<table role=presentation width='100%' cellpadding=0 cellspacing=0 "
        "bgcolor='#f7f9f9' style='background:#f7f9f9'><tr><td>"
        f"<div class=d>"
        f"<div style='font-size:22px;font-weight:800'>Your X digest</div>"
        f"<div style='font-size:13px;color:#536471;margin-top:2px'>{ds} &#183; "
        f"{shown_total} {tws} from {na} {acc} since {since} evening{trimmed}</div>"
        + warn + "".join(sections)
        + "<div style='color:#8b98a5;font-size:11px;margin-top:28px;text-align:center'>"
        "Top posts by likes from your chosen accounts. No algorithm, no scroll.</div></div>"
        "</td></tr></table>"
    )
    body = inline(body)
    body = re.sub(r"\s+", " ", body).strip()
    open(f"{out}/body.html", "w", encoding="utf-8").write(body)
    open(f"{out}/subj.txt", "w", encoding="utf-8").write(
        f"X digest: {shown_total} {tws} \u2014 {ds}")
    print(f"COUNT={shown_total}")
    print("WARN=" + ("yes" if warn else "no"))
    print(f"BYTES={len(body.encode())}")


if __name__ == "__main__":
    main()
