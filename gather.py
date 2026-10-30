# Fills the news side of the pool.
#
# Reads every source in feeds.yaml, keeps the items we haven't seen before,
# and adds them to news.json. The team's own ideas live in ideas/ instead; this file
# only answers "what's new that might be worth a take?"

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

HERE = Path(__file__).parent
FEEDS_FILE = HERE / "feeds.yaml"
NEWS_FILE = HERE / "news.json"
SEEN_FILE = HERE / "seen.json"

# Only items published in the last two weeks enter the pool. This is also what
# stops the first run from dumping OpenAI's entire 1,200-post archive in.
MAX_AGE = timedelta(days=14)

# How much of each item's summary to keep. Enough to judge it, not the article.
MAX_SUMMARY_CHARS = 500

# Some sites turn away requests that don't look like a browser.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) content-machine/0.1"}


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def plain_text(raw):
    """Strip HTML tags and entities, and squash whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def matches_keywords(text, keywords):
    """True if any keyword appears as a whole word (so "ad" won't match "add")."""
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            return True
    return False


def published_at(entry):
    """The item's publish time, or None if the feed doesn't give one."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def entry_link(entry):
    """The item's page, or for a podcast with no page, its audio file."""
    if entry.get("link"):
        return entry["link"]
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("href"):
            return link["href"]
    return ""


def gather_feed(feed, keywords, seen, now):
    """Return new idea-pool items from one RSS/Atom feed."""
    response = requests.get(feed["url"], headers=HEADERS, timeout=30)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)

    items = []
    for entry in parsed.entries:
        item_id = entry.get("id") or entry_link(entry)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)

        published = published_at(entry)
        if published and now - published > MAX_AGE:
            continue

        link = entry_link(entry)
        if any(pattern in link for pattern in feed.get("exclude_links", [])):
            continue

        title = plain_text(entry.get("title"))
        summary = plain_text(entry.get("summary"))
        if feed.get("filter") and not matches_keywords(f"{title} {summary}", keywords):
            continue

        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS].rstrip() + "…"

        items.append({
            "id": item_id,
            "source": feed["name"],
            "category": feed["category"],
            "title": title,
            "link": link or None,
            "published": published.isoformat() if published else None,
            "summary": summary,
            "added": now.isoformat(),
        })
    return items


def sitemap_urls(url):
    """Every page URL in a sitemap, following a sitemap index to its children."""
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    text = response.text
    locs = re.findall(r"<loc>([^<]+)</loc>", text)
    if "<sitemapindex" in text:
        urls = set()
        for child in locs:
            urls |= sitemap_urls(child)
        return urls
    return set(locs)


def page_title(url):
    """The page's <title>, for sitemap entries that arrive with only a URL."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        match = re.search(r"<title[^>]*>([^<]+)</title>", response.text)
        if match:
            return html.unescape(match.group(1)).strip()
    except requests.RequestException:
        pass
    # Fall back to the slug: ".../meridian-marketing-mix-model/" -> "meridian marketing mix model"
    return url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")


def gather_sitemap(site, seen, now):
    """Return new idea-pool items from a site that only has a sitemap.

    A sitemap has no publish dates we can trust, so "new" means "a URL we
    haven't recorded before". The first run records everything and adds
    nothing; otherwise we'd drop a thousand old articles into the pool.
    """
    prefix = site["prefix"]
    # Only articles: skip section index pages like ".../think/ai-excellence/".
    urls = {
        u for u in sitemap_urls(site["url"])
        if u.startswith(prefix) and u[len(prefix):].strip("/").count("/") >= 1
    }

    first_run = not any(u.startswith(prefix) for u in seen)
    new_urls = sorted(urls - seen)
    seen |= urls
    if first_run:
        print(f"{site['name']}: first run, recorded {len(urls)} existing article(s).")
        return []

    return [{
        "id": url,
        "source": site["name"],
        "category": site["category"],
        "title": page_title(url),
        "link": url,
        "published": None,
        "summary": "",
        "added": now.isoformat(),
    } for url in new_urls]


def main():
    config = yaml.safe_load(FEEDS_FILE.read_text())
    keywords = config.get("keywords", [])
    news = load_json(NEWS_FILE, [])
    seen = set(load_json(SEEN_FILE, []))
    now = datetime.now(timezone.utc)

    new_items = []
    # One broken source shouldn't stop the rest, so each gets its own try.
    for feed in config.get("feeds", []):
        try:
            items = gather_feed(feed, keywords, seen, now)
            print(f"{feed['name']}: {len(items)} new")
            new_items += items
        except Exception as error:
            print(f"{feed['name']}: FAILED ({error})")

    for site in config.get("sitemaps", []):
        try:
            items = gather_sitemap(site, seen, now)
            print(f"{site['name']}: {len(items)} new")
            new_items += items
        except Exception as error:
            print(f"{site['name']}: FAILED ({error})")

    news += new_items
    save_json(NEWS_FILE, news)
    save_json(SEEN_FILE, sorted(seen))
    print(f"\n{len(new_items)} item(s) added; the pool now holds {len(news)}.")


if __name__ == "__main__":
    main()
