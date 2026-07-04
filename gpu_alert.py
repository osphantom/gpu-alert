#!/usr/bin/env python3
"""
Craigslist Baltimore GPU alerter — GitHub Actions edition (full-page scan).

For each NEW listing in the Baltimore computer-parts and systems feeds, this
opens the listing's own page and scans the ENTIRE description text — not just
the short RSS snippet — so it catches sellers who bury the model ("RTX 3080",
"Radeon", etc.) deep in the description under a generic title like
"graphics card" or "gaming pc".

Only emails when a real GPU keyword appears somewhere in the title or body.

State (already-seen listings) lives in seen.json, committed back by the
workflow. Email creds come from GitHub Actions secrets (env vars).
"""

import html
import json
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.request import Request, urlopen

import feedparser

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# Pull broadly from the feeds (no query) so we don't rely on the title.
# We do the real filtering ourselves against the full page text.
FEEDS = [
    "https://baltimore.craigslist.org/search/sop?format=rss",   # computer parts - by owner
    "https://baltimore.craigslist.org/search/spo?format=rss",   # computer parts - by dealer
    "https://baltimore.craigslist.org/search/syp?format=rss",   # systems - by owner
    "https://baltimore.craigslist.org/search/sys?format=rss",   # systems - by dealer
]

# Real GPU keywords. Word-boundary matched so "rx" won't fire on "box"
# and "arc" won't fire on "search".
KEYWORDS = [
    r"\brtx\b", r"\bgtx\b", r"\brx\s?\d{3,4}\b", r"\bradeon\b",
    r"\bgeforce\b", r"\bnvidia\b", r"\bgraphics\s+card\b", r"\bvideo\s+card\b",
    r"\bgpu\b", r"\bintel\s+arc\b",
    r"\b(30|40|50)\d0\b",             # 3080, 4090, 5070, etc.
    r"\b(10|16|20)\d0\b",             # 1080, 1660, 2070, etc.
    r"\brx\s?(5|6|7)\d00\b",          # RX 5700, 6600, 7900...
]

STATE_FILE = "seen.json"
PAGE_FETCH_DELAY = 1.0   # seconds between listing-page fetches (be polite)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
EMAIL_FROM = os.environ["GPU_EMAIL_FROM"]
EMAIL_PASS = os.environ["GPU_EMAIL_PASS"]
EMAIL_TO   = os.environ["GPU_EMAIL_TO"]
# ----------------------------------------------------------------------

PATTERNS = [re.compile(k, re.IGNORECASE) for k in KEYWORDS]

# Only bother opening the full page for listings that plausibly involve a
# computer/electronics item. Keeps us from fetching every unrelated post.
PLAUSIBLE = re.compile(
    r"(comput|pc\b|gpu|graphics|video card|gaming|nvidia|radeon|geforce|"
    r"rtx|gtx|\brx\b|desktop|tower|rig|motherboard)", re.IGNORECASE
)


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
    trimmed = sorted(seen)[-3000:]
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


def http_get(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (gpu-alert)"})
    with urlopen(req, timeout=30) as r:
        return r.read()


def fetch_feed(url):
    return feedparser.parse(http_get(url))


def fetch_listing_text(url):
    """Download a listing page and pull out the human-readable description."""
    try:
        raw = http_get(url).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[warn] could not fetch listing {url}: {e}")
        return ""
    # Craigslist puts the body in <section id="postingbody">...</section>
    m = re.search(r'id="postingbody".*?>(.*?)</section>', raw, re.DOTALL | re.IGNORECASE)
    body = m.group(1) if m else raw
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    return re.sub(r"\s+", " ", body)


def main():
    seen = load_seen()
    first_run = len(seen) == 0
    new_hits = []

    fresh_entries = []
    for url in FEEDS:
        try:
            feed = fetch_feed(url)
        except Exception as e:
            print(f"[warn] fetch failed for {url}: {e}")
            continue
        for entry in feed.entries:
            uid = entry.get("link") or entry.get("title")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            fresh_entries.append(entry)

    if first_run:
        save_seen(seen)
        print(f"[init] baselined {len(seen)} listings, no email sent")
        return

    print(f"[info] {len(fresh_entries)} new listing(s) to examine")

    for entry in fresh_entries:
        link = entry.get("link", "")
        title = entry.get("title", "")
        snippet = entry.get("summary", "")
        head = f"{title} {snippet}"

        if matches(head):
            new_hits.append((title, link))
            continue

        if PLAUSIBLE.search(head):
            time.sleep(PAGE_FETCH_DELAY)
            body = fetch_listing_text(link)
            if matches(body):
                new_hits.append((title, link))

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
