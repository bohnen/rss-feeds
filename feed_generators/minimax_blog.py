"""Generate an RSS feed for MiniMax news and blog posts (https://www.minimax.io/news).

MiniMax's Next.js listing pages (``/news`` and ``/blog``) render article links
(``/news/<slug>``, ``/blog/<slug>``) server-side but without dates. Each article
page embeds an ``application/ld+json`` block whose ``@graph`` contains a
``BlogPosting``/``Article`` node with ``headline`` and ``datePublished``. So the
generators collect links from both listing pages, then fetch each article once
to resolve its title, date, and description. Articles without a parseable date
fall back to a stable hash date (see ``stable_fallback_date``).
"""

import argparse
import json
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

BASE_URL = "https://www.minimax.io"
FEED_NAME = "minimax"
BLOG_URL = f"{BASE_URL}/news"
LISTING_URLS = [f"{BASE_URL}/news", f"{BASE_URL}/blog"]
FEED_TITLE = "MiniMax News"
FEED_DESCRIPTION = "Product updates, research, and blog posts from MiniMax"
AUTHOR = "MiniMax"


def parse_iso_date(date_text: str | None) -> datetime | None:
    """Parse an ISO 8601 date string into a UTC datetime, or ``None``."""
    if not date_text:
        return None
    try:
        date = datetime.fromisoformat(date_text.strip().replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=pytz.UTC)
        return date
    except ValueError:
        logger.warning(f"Could not parse date: {date_text!r}")
        return None


def collect_article_links() -> list[str]:
    """Collect unique article URLs from the /news and /blog listing pages."""
    links = []
    seen = set()
    for listing_url in LISTING_URLS:
        try:
            html = fetch_page(listing_url)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch listing {listing_url}: {e}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if href.startswith("/") and ("/news/" in href or "/blog/" in href):
                link = f"{BASE_URL}{href.split('?')[0]}"
                if link not in seen:
                    seen.add(link)
                    links.append(link)
    logger.info(f"Found {len(links)} article links across listing pages")
    return links


def _ld_json_articles(soup: BeautifulSoup) -> list[dict]:
    """Return all mapping nodes from every ld+json block on the page."""
    nodes = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        graph = data.get("@graph", [data]) if isinstance(data, dict) else data
        if isinstance(graph, list):
            nodes.extend(node for node in graph if isinstance(node, dict))
    return nodes


def parse_article(html_content: str, link: str) -> dict:
    """Build a post dict from an article page's ld+json metadata."""
    soup = BeautifulSoup(html_content, "html.parser")
    title = None
    date = None
    description = None

    for node in _ld_json_articles(soup):
        if node.get("@type") in ("BlogPosting", "Article", "NewsArticle", "WebPage") and node.get("headline"):
            title = title or node.get("headline")
            date = date or parse_iso_date(node.get("datePublished"))
            description = description or node.get("description") or None

    if not title:
        og_title = soup.find("meta", property="og:title")
        title = og_title["content"].strip() if og_title and og_title.get("content") else link.rsplit("/", 1)[-1]
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc["content"].strip() if meta_desc and meta_desc.get("content") else title

    return {"title": title, "link": link, "date": date, "description": description}


def parse(html_content: str) -> list[dict]:
    """Extract article links from a MiniMax listing page (titles need per-article fetches)."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("/") and ("/news/" in href or "/blog/" in href):
            link = f"{BASE_URL}{href.split('?')[0]}"
            title = anchor.get_text(strip=True) or link.rsplit("/", 1)[-1]
            articles.append({"title": title, "link": link, "date": None, "description": title})
    return articles


def fetch_articles() -> list[dict]:
    """Collect links from all listing pages, then resolve metadata per article."""
    links = collect_article_links()
    articles = []
    for link in links:
        try:
            html = fetch_page(link)
            article = parse_article(html, link)
        except requests.RequestException as e:
            logger.warning(f"Could not fetch {link}: {e}")
            continue
        if article["date"] is None:
            logger.warning(f"No parseable date for {link}")
            article["date"] = stable_fallback_date(link)
        articles.append(article)

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
    parser.add_argument("--full", action="store_true", help="No-op (MiniMax has no cache)")
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
