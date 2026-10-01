"""Send the daily email: all tweets from the last `email_hours` hours.

Skips silently (exit 0) when there is nothing to send. SMTP credentials come
from env: SMTP_USER, SMTP_PASS, EMAIL_TO (defaults to SMTP_USER).
"""
import html
import os
import smtplib
import ssl
import sys
from datetime import timedelta
from email.mime.text import MIMEText

from common import (load_accounts, load_settings, load_archive,
                    parse_created, now_utc)


def tweet_html(t):
    text = html.escape(t["text"]).replace("\n", "<br>")
    quoted = ""
    if t.get("quoted") and t["quoted"].get("text"):
        quoted = (f"<blockquote style='border-left:3px solid #ccc;margin:6px 0;"
                  f"padding:2px 10px;color:#555'>@{html.escape(t['quoted']['author'])}: "
                  f"{html.escape(t['quoted']['text'])}</blockquote>")
    rt = "<span style='color:#888;font-size:12px'>[repost] </span>" if t["is_retweet"] else ""
    dt = parse_created(t["created_at"])
    when = dt.strftime("%H:%M") if dt else ""
    return (f"<div style='margin:0 0 14px;padding:10px 12px;border:1px solid #e2e2e2;"
            f"border-radius:8px'>{rt}<div style='margin:2px 0'>{text}</div>{quoted}"
            f"<div style='font-size:12px;color:#888'>{when} UTC · "
            f"<a href='{t['url']}' style='color:#3d5a80'>open on X</a></div></div>")


def main():
    settings = load_settings()
    hours = settings.get("email_hours", 24)
    cutoff = now_utc() - timedelta(hours=hours)

    sections, total = [], 0
    for handle in load_accounts():
        arch = load_archive(handle)
        ts = [t for t in arch["tweets"].values()
              if (parse_created(t["created_at"]) or cutoff) > cutoff
              and parse_created(t["created_at"])]
        ts.sort(key=lambda t: parse_created(t["created_at"]), reverse=True)
        if ts:
            name = html.escape(ts[0].get("author_name") or handle)
            sections.append(
                f"<h3 style='margin:22px 0 8px;font-size:15px'>{name} "
                f"<a href='https://x.com/{handle}' style='color:#888;"
                f"font-weight:normal;text-decoration:none'>@{handle}</a> "
                f"<span style='color:#888;font-weight:normal'>({len(ts)})</span></h3>"
                + "".join(tweet_html(t) for t in ts))
            total += len(ts)

    if total == 0:
        print("No tweets in window — no email sent.")
        return

    user = os.environ["SMTP_USER"]
    to = os.environ.get("EMAIL_TO", user)
    date_str = now_utc().strftime("%a %d %b")
    body = (f"<html><body style='font-family:-apple-system,Segoe UI,Roboto,"
            f"sans-serif;max-width:620px;margin:0 auto;color:#1a1a18'>"
            f"<h2 style='font-size:18px'>Your X digest — {date_str}</h2>"
            f"<p style='color:#888;font-size:13px'>{total} tweets in the last "
            f"{hours} hours. Dashboard: see repo README for your URL.</p>"
            + "".join(sections) + "</body></html>")

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = f"{settings.get('email_subject_prefix', 'X digest')}: {total} tweets — {date_str}"
    msg["From"] = user
    msg["To"] = to

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.get("smtp_host", "smtp.mail.yahoo.com"),
                          settings.get("smtp_port", 465), context=ctx) as s:
        s.login(user, os.environ["SMTP_PASS"])
        s.sendmail(user, [to], msg.as_string())
    print(f"Email sent to {to}: {total} tweets.")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"Missing env var {e} — skipping email.", file=sys.stderr)
        sys.exit(0)  # email failure should not fail the whole run
    except Exception as e:  # noqa: BLE001
        print(f"Email failed: {e}", file=sys.stderr)
        sys.exit(0)
