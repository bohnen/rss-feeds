"""Generate an RSS feed for DeepSeek API news (https://api-docs.deepseek.com/news/).

The ``/news/`` URL itself redirects to the docs homepage; there is no dedicated
listing page. Instead, each news article page (Docusaurus) renders a sidebar
listing every news item as ``<a href="/news/<slug>"><Title> <YYYY/MM/DD></a>``.
The article slugs are discovered from ``sitemap.xml``; the sidebar of any news
page then provides titles and dates for all of them (missing slugs are fetched
individually and fall back to their ``<h1>`` title and a stable hash date).
"""

import argparse
import re
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

from utils import (
    fetch_page,
    save_rss_feed,
    setup_feed_links,
    setup_logging,
    sort_posts_for_feed,
    stable_fallback_date,
)

logger = setup_logging()

BASE_URL = "https://api-docs.deepseek.com"
FEED_NAME = "deepseek"
BLOG_URL = f"{BASE_URL}/news/"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
FEED_TITLE = "DeepSeek News"
FEED_DESCRIPTION = "News and release announcements from DeepSeek"
AUTHOR = "DeepSeek"

DATE_SUFFIX_RE = re.compile(r"^(.*?)\s+(\d{4}/\d{2}/\d{2})$")


def discover_news_slugs() -> list[str]:
    """Return all ``/news/<slug>`` paths found in the sitemap."""
    try:
        xml = fetch_page(SITEMAP_URL)
    except requests.RequestException as e:
        logger.warning(f"Could not fetch sitemap: {e}")
        return []
    slugs = re.findall(rf"<loc>{re.escape(BASE_URL)}(/news/[^<]+)</loc>", xml)
    logger.info(f"Sitemap lists {len(slugs)} news pages")
    return slugs


def parse_date(date_text: str) -> datetime | None:
    """Parse a ``YYYY/MM/DD`` date string into a UTC datetime."""
    try:
        return datetime.strptime(date_text.strip(), "%Y/%m/%d").replace(tzinfo=pytz.UTC)
    except ValueError:
        logger.warning(f"Could not parse date: {date_text!r}")
        return None


def parse(html_content: str) -> list[dict]:
    """Extract news entries (title, link, date) from a news article page.

    The Docusaurus sidebar of any news page lists all news items as
    ``<a href="/news/<slug>"><Title> <YYYY/MM/DD></a>``.
    """
    entries = {}
    soup = BeautifulSoup(html_content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith("/news/"):
            continue
        match = DATE_SUFFIX_RE.match(anchor.get_text(strip=True))
        if not match:
            continue
        title, date_text = match.groups()
        if not title:
            continue
        link = f"{BASE_URL}{href}"
        date = parse_date(date_text)
        entries.setdefault(
            link,
            {"title": title, "link": link, "date": date, "description": title},
        )
    return list(entries.values())


def parse_article_page(html_content: str, link: str) -> dict:
    """Build an entry from an individual article page (title from ``<h1>``)."""
    soup = BeautifulSoup(html_content, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else link.rsplit("/", 1)[-1]
    return {"title": title, "link": link, "date": None, "description": title}


def fetch_articles() -> list[dict]:
    """Discover slugs via the sitemap and resolve titles/dates for each."""
    slugs = discover_news_slugs()
    if not slugs:
        logger.warning("No news slugs found in sitemap; cannot build feed")
        return []

    # The sidebar of any single news page covers all items with dates.
    html = fetch_page(f"{BASE_URL}{slugs[-1]}/")
    entries = {e["link"]: e for e in parse(html)}

    for path in slugs:
        link = f"{BASE_URL}{path}" if path.startswith("/") else path
        if link in entries:
            continue
        logger.info(f"Fetching article page without sidebar entry: {link}")
        try:
            article_html = fetch_page(link if link.endswith("/") else f"{link}/")
            entry = parse_article_page(article_html, link)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch {link}: {e}")
            entry = {
                "title": link.rsplit("/", 1)[-1],
                "link": link,
                "date": None,
                "description": link.rsplit("/", 1)[-1],
            }
        if entry["date"] is None:
            entry["date"] = stable_fallback_date(link)
        entries[link] = entry

    articles = list(entries.values())
    logger.info(f"Parsed {len(articles)} articles")
    return articles


def generate_rss_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.description(FEED_DESCRIPTION)
    fg.language("en")
    fg.author({"name": AUTHOR})
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for post in sort_posts_for_feed(articles):
        fe = fg.add_entry()
        fe.title(post["title"])
        fe.description(post.get("description") or post["title"])
        fe.link(href=post["link"])
        fe.id(post["link"])
        if post.get("date"):
            fe.published(post["date"])

    return fg


def main() -> bool:
    parser = argparse.ArgumentParser(description=f"Generate the {FEED_TITLE} RSS feed")
    parser.add_argument("--full", action="store_true", help="No-op (DeepSeek has no cache)")
    parser.parse_args()

    try:
        articles = fetch_articles()
        if not articles:
            logger.warning("No articles found - skipping feed update to avoid overwriting with empty feed")
            return False
        fg = generate_rss_feed(articles)
        save_rss_feed(fg, FEED_NAME)
        logger.info(f"Generated {FEED_NAME} feed with {len(articles)} articles")
        return True
    except Exception as e:
        logger.error(f"Failed to generate {FEED_NAME} feed: {e!s}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
