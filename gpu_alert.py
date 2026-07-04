#!/usr/bin/env python3
"""
Craigslist Baltimore GPU alerter — GitHub Actions edition.

Runs ONCE per invocation (no loop). GitHub Actions triggers it on a
schedule. State (already-seen listings) is kept in seen.json, which the
workflow commits back to the repo after each run so the next run remembers.

Email credentials come from GitHub Actions "secrets" (encrypted), exposed
as environment variables — never hardcoded here.
"""

import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from urllib.request import Request, urlopen

import feedparser

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
FEEDS = [
    "https://baltimore.craigslist.org/search/sop?query=graphics+card+gpu+rtx+gtx+radeon&format=rss",
    "https://baltimore.craigslist.org/search/syp?query=gpu+graphics+card&format=rss",
]

KEYWORDS = [
    r"\brtx\b", r"\bgtx\b", r"\brx\s?\d{3,4}\b", r"\bradeon\b",
    r"\bgeforce\b", r"\bnvidia\b", r"\bgraphics card\b", r"\bgpu\b",
    r"\barc\b", r"\b(30|40|50)\d0\b",
]

STATE_FILE = "seen.json"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
EMAIL_FROM = os.environ["GPU_EMAIL_FROM"]   # from GitHub secret
EMAIL_PASS = os.environ["GPU_EMAIL_PASS"]   # from GitHub secret
EMAIL_TO   = os.environ["GPU_EMAIL_TO"]     # from GitHub secret
# ----------------------------------------------------------------------

PATTERNS = [re.compile(k, re.IGNORECASE) for k in KEYWORDS]


def matches(text):
    return any(p.search(text) for p in PATTERNS)


def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen(seen):
    # keep the file from growing forever; last ~2000 ids is plenty
    trimmed = sorted(seen)[-2000:]
    with open(STATE_FILE, "w") as f:
        json.dump(trimmed, f, indent=0)


def send_email(subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(EMAIL_FROM, EMAIL_PASS)
        s.send_message(msg)


def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (gpu-alert)"})
    with urlopen(req, timeout=30) as r:
        return feedparser.parse(r.read())


def main():
    seen = load_seen()
    first_run = len(seen) == 0
    new_hits = []

    for url in FEEDS:
        try:
            feed = fetch(url)
        except Exception as e:
            print(f"[warn] fetch failed for {url}: {e}")
            continue
        for entry in feed.entries:
            uid = entry.get("link") or entry.get("title")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if matches(title + " " + summary):
                new_hits.append((title, entry.get("link", "")))

    # On the very first run, baseline everything silently (no email blast).
    if first_run:
        save_seen(seen)
        print(f"[init] baselined {len(seen)} listings, no email sent")
        return

    for title, link in new_hits:
        body = f"New Craigslist GPU listing:\n\n{title}\n{link}"
        try:
            send_email(f"[GPU] {title[:80]}", body)
            print(f"[alert] {title}")
        except Exception as e:
            print(f"[error] email failed: {e}")

    save_seen(seen)
    print(f"[done] {len(new_hits)} new alert(s) this run")


if __name__ == "__main__":
    main()
