"""Regenerate docs/index.html (the dashboard) from the tweet archive.

The page is fully static and self-contained: tweets from the last
`dashboard_days` days are embedded as JSON; filtering happens client-side.
"""
import html
import json
import os
from datetime import timedelta

from common import (DOCS_DIR, load_accounts, load_settings, load_archive,
                    load_status, parse_created, now_utc)

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>My X Digest</title>
<style>
:root {
  --bg:#f7f7f5; --card:#ffffff; --ink:#1a1a18; --muted:#6b6b66;
  --accent:#3d5a80; --line:#e4e4df; --warn:#9a3412; --chipbg:#ecece8;
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#131312; --card:#1d1d1b; --ink:#e8e8e4; --muted:#98988f;
          --accent:#8fb3d9; --line:#2c2c29; --warn:#fca5a5; --chipbg:#262623; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width:640px; margin:0 auto; padding:16px 12px 80px; }
header h1 { font-size:1.35rem; margin:8px 0 2px; }
.sub { color:var(--muted); font-size:.82rem; margin-bottom:14px; }
.controls { position:sticky; top:0; background:var(--bg); padding:8px 0 10px;
  z-index:5; border-bottom:1px solid var(--line); }
.row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
button.tog { border:1px solid var(--line); background:var(--card); color:var(--ink);
  border-radius:999px; padding:5px 14px; font-size:.85rem; cursor:pointer; }
button.tog.on { background:var(--accent); color:#fff; border-color:var(--accent); }
input#q { flex:1; min-width:140px; border:1px solid var(--line); background:var(--card);
  color:var(--ink); border-radius:999px; padding:6px 14px; font-size:.85rem; }
.chips { margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; }
.chip { font-size:.75rem; padding:3px 10px; border-radius:999px; background:var(--chipbg);
  color:var(--muted); cursor:pointer; border:1px solid transparent; }
.chip.on { color:var(--ink); border-color:var(--accent); }
.warns { color:var(--warn); font-size:.78rem; margin:10px 0 0; }
.day { margin:22px 0 6px; font-size:.8rem; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); }
.tweet { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; margin:10px 0; }
.tw-head { display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
.tw-name { font-weight:600; font-size:.92rem; }
.tw-handle, .tw-time { color:var(--muted); font-size:.8rem; text-decoration:none; }
.tw-text { margin:6px 0 4px; white-space:pre-wrap; word-wrap:break-word; }
.tw-text a { color:var(--accent); }
.quote { border-left:3px solid var(--line); margin:6px 0; padding:2px 10px;
  color:var(--muted); font-size:.88rem; }
.media { color:var(--accent); font-size:.8rem; }
.rt { color:var(--muted); font-size:.75rem; }
.stats { color:var(--muted); font-size:.75rem; margin-top:4px; }
.empty { text-align:center; color:var(--muted); margin:60px 0; }
a.orig { color:var(--muted); font-size:.75rem; text-decoration:none; }
footer { margin-top:40px; color:var(--muted); font-size:.75rem; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>My X Digest</h1>
  <div class="sub">__COUNT__ tweets from __NACC__ accounts · updated __UPDATED__ UTC</div>
</header>
<div class="controls">
  <div class="row">
    <button class="tog" id="t24">Last 24 h</button>
    <button class="tog on" id="t7d">Last 7 days</button>
    <button class="tog" id="tgrp">Group by account</button>
    <input id="q" type="search" placeholder="Search text or @handle">
  </div>
  <div class="chips" id="chips"></div>
  __WARNS__
</div>
<main id="feed"></main>
<footer>Static page — no algorithm, no tracking, nothing infinite.
  Edit accounts in <code>config/accounts.txt</code>.</footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const tweets = JSON.parse(document.getElementById('data').textContent);
tweets.forEach(t => t.ts = Date.parse(t.created_at));
tweets.sort((a,b) => b.ts - a.ts);
const state = { hours: 168, group: true, q: '', acct: null };
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const linkify = s => esc(s)
  .replace(/(https?:\\/\\/[^\\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
  .replace(/(^|\\s)@([A-Za-z0-9_]{1,15})/g, '$1<a href="https://x.com/$2" target="_blank" rel="noopener">@$2</a>');
const fmtT = ts => new Date(ts).toLocaleString('en-GB',
  {hour:'2-digit', minute:'2-digit'});
const fmtD = ts => new Date(ts).toLocaleDateString('en-GB',
  {weekday:'long', day:'numeric', month:'long'});

function chips() {
  const handles = [...new Set(tweets.map(t => t.author_handle))].sort(
    (a,b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  $('chips').innerHTML = handles.map(h =>
    `<span class="chip${state.acct===h?' on':''}" data-h="${h}">@${h}</span>`).join('');
  document.querySelectorAll('.chip').forEach(c => c.onclick = () => {
    state.acct = state.acct === c.dataset.h ? null : c.dataset.h; render();
  });
}

function card(t) {
  const rt = t.is_retweet ? '<div class="rt">reposted</div>' : '';
  const q = t.quoted && t.quoted.text ?
    `<div class="quote">@${esc(t.quoted.author)}: ${linkify(t.quoted.text)}</div>` : '';
  const med = t.media && t.media.length ?
    `<div class="media">${t.media.map((m,i) =>
      `<a href="${m.url}" target="_blank" rel="noopener">[${m.type} ${i+1}]</a>`).join(' ')}</div>` : '';
  return `<article class="tweet">
    <div class="tw-head">
      <span class="tw-name">${esc(t.author_name || t.author_handle)}</span>
      <a class="tw-handle" href="https://x.com/${t.author_handle}" target="_blank" rel="noopener">@${t.author_handle}</a>
      <span class="tw-time">${fmtT(t.ts)}</span>
      <a class="orig" href="${t.url}" target="_blank" rel="noopener">open ↗</a>
    </div>
    ${rt}<div class="tw-text">${linkify(t.text)}</div>${q}${med}
    <div class="stats">♥ ${t.likes||0} · ⇄ ${t.retweets||0}</div>
  </article>`;
}

function render() {
  const cutoff = Date.now() - state.hours*3600*1000;
  let list = tweets.filter(t => t.ts >= cutoff);
  if (state.acct) list = list.filter(t => t.author_handle === state.acct);
  if (state.q) {
    const q = state.q.toLowerCase();
    list = list.filter(t => (t.text + ' @' + t.author_handle + ' ' +
      (t.author_name||'')).toLowerCase().includes(q));
  }
  $('t24').classList.toggle('on', state.hours === 24);
  $('t7d').classList.toggle('on', state.hours === 168);
  $('tgrp').classList.toggle('on', state.group);
  chips();
  if (!list.length) {
    $('feed').innerHTML = '<div class="empty">Nothing here — quiet timeline or filters too tight.</div>';
    return;
  }
  let out = '';
  if (state.group) {
    const by = {};
    list.forEach(t => (by[t.author_handle] = by[t.author_handle] || []).push(t));
    Object.keys(by).sort((a,b)=>a.toLowerCase().localeCompare(b.toLowerCase()))
      .forEach(h => {
        const nm = by[h][0].author_name || h;
        out += `<div class="day">${esc(nm)} (@${h}) — ${by[h].length}</div>` +
               by[h].map(card).join('');
      });
  } else {
    let day = '';
    list.forEach(t => {
      const d = fmtD(t.ts);
      if (d !== day) { out += `<div class="day">${d}</div>`; day = d; }
      out += card(t);
    });
  }
  $('feed').innerHTML = out;
}

$('t24').onclick = () => { state.hours = 24; render(); };
$('t7d').onclick = () => { state.hours = 168; render(); };
$('tgrp').onclick = () => { state.group = !state.group; render(); };
$('q').oninput = e => { state.q = e.target.value.trim(); render(); };
render();
</script>
</body>
</html>
"""


def main():
    settings = load_settings()
    accounts = load_accounts()
    cutoff = now_utc() - timedelta(days=settings.get("dashboard_days", 7))

    recent = []
    for handle in accounts:
        arch = load_archive(handle)
        for t in arch["tweets"].values():
            dt = parse_created(t["created_at"])
            if dt and dt >= cutoff:
                t = dict(t)
                t["created_at"] = dt.isoformat()
                recent.append(t)

    status = load_status()
    warns = []
    last = status.get("last_run", {})
    for h, s in last.get("accounts", {}).items():
        if not s.get("ok"):
            warns.append(f"@{h}: fetch failed last run")
    warns_html = (
        '<div class="warns">⚠ ' + html.escape(" · ".join(warns)) + "</div>"
    ) if warns else ""

    data = json.dumps(recent, ensure_ascii=False).replace("</", "<\\/")
    page = (TEMPLATE
            .replace("__DATA__", data)
            .replace("__COUNT__", str(len(recent)))
            .replace("__NACC__", str(len(accounts)))
            .replace("__UPDATED__", now_utc().strftime("%d %b %Y, %H:%M"))
            .replace("__WARNS__", warns_html))

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    open(os.path.join(DOCS_DIR, ".nojekyll"), "w").close()
    print(f"Dashboard rebuilt: {len(recent)} tweets in window.")


if __name__ == "__main__":
    main()
