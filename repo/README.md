# My X Digest

A personal, algorithm-free reading surface for chosen public X accounts.
Once a day this repo fetches their new tweets, archives them, rebuilds a
static dashboard on GitHub Pages, and emails a digest of the last 24 hours.
Nothing here talks to X when you read — no feed, no recommendations, no
infinite scroll.

## How it works

Every morning (05:45 UTC) the **Daily digest** workflow:

1. `scripts/fetch.py` — pulls new tweets for each account in
   `config/accounts.txt` via twitterapi.io and merges them into
   `data/tweets/*.json` (deduped by tweet ID; one failing account never
   breaks the run — it just shows a warning on the dashboard).
2. `scripts/build_site.py` — regenerates `docs/index.html`, the dashboard.
3. `scripts/send_email.py` — emails everything from the last 24 h
   (no tweets → no email).
4. Commits the updated archive + dashboard back to the repo.

## One-time setup (about 10 minutes)

1. **Create this repo** on GitHub (public — Pages is free on public repos;
   it only ever contains public tweets) and upload these files.
2. **Enable Pages**: repo → Settings → Pages → Source: *Deploy from a
   branch* → Branch: `main`, folder `/docs`. Your dashboard URL will be
   `https://<username>.github.io/<repo>/`.
3. **Add secrets**: repo → Settings → Secrets and variables → Actions →
   *New repository secret*, four times:
   - `TWITTERAPI_KEY` — your key from twitterapi.io
   - `SMTP_USER` — your full Yahoo address
   - `SMTP_PASS` — a Yahoo **app password**: Yahoo account →
     Security → Generate app password (your normal password won't work)
   - `EMAIL_TO` — where the digest goes (usually same as SMTP_USER)
4. **First run**: Actions tab → *Daily digest* → *Run workflow*. Check the
   dashboard URL and your inbox.
5. **(Optional) full following export**: Actions tab → *Export following
   list* → *Run workflow* → produces `data/following.csv` with follower
   counts and activity for every account you follow.

## Everyday use

- **Add/remove accounts**: edit `config/accounts.txt` on github.com
  (one username per line, no @). Takes effect next run.
- **Change behaviour**: `config/settings.json` — include replies/reposts,
  dashboard window, email hours, subject prefix.
- **Run on demand**: Actions tab → Daily digest → Run workflow.
- **If a run fails**: GitHub emails you automatically. The dashboard keeps
  its last good state; nothing is lost.

## Costs

- GitHub (hosting, scheduling, Pages): **£0**
- twitterapi.io at ~17 accounts once daily: roughly **£1–2/month**
  (pay-as-you-go, ~$0.15 per 1,000 tweets read). Top up from its dashboard;
  it stops (rather than overcharges) if credit runs out.

## Swapping the data provider

All twitterapi.io-specific code lives in
`scripts/providers/twitterapi_io.py`. To switch providers, add a sibling
module exposing `fetch_user_tweets()` and `fetch_followings()` with the
same signatures and change `"provider"` in `config/settings.json`.
Alternatives as of 2026: Apify, Bright Data, SocialCrawl, ScrapeCreators.
There is also a `mock` provider for testing the pipeline offline.

## Notes

- Schedule is UTC: 05:45 UTC ≈ 6:45–7:15 am UK in summer (GitHub cron can
  lag), an hour earlier in winter. Adjust in `.github/workflows/daily.yml`.
- The dashboard has `noindex` set and an obscure URL, but it is technically
  public — as are all the tweets on it.
