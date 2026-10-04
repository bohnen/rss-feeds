"""Generate RSS feed for the Nous Research Blog (https://nousresearch.com/blog).

The blog listing is server-rendered Next.js HTML: each post card has an
``a.nw-catalogue-link`` (title + link) and a sibling ``p.nw-blog-excerpt``
(description). The listing itself carries no dates, so each article page is
fetched and its ``article:published_time`` meta tag is used. No JavaScript
rendering required.
"""

import argparse
import time
from datetime import datetime

import pytz
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

FEED_NAME = "nous"
BLOG_URL = "https://nousresearch.com/blog"
BASE_URL = "https://nousresearch.com"
DETAIL_REQUEST_DELAY_SECONDS = 0.5


def parse_blog_html(html_content: str) -> list[dict]:
    """Extract articles from the Nous Research blog listing page."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    seen_links = set()

    for title_link in soup.select("a.nw-catalogue-link"):
        href = title_link.get("href", "")
        if not href or href.rstrip("/") == BLOG_URL:
            continue

        link = href if href.startswith("http") else f"{BASE_URL}{href}"
        if link in seen_links:
            continue
        seen_links.add(link)

        title = title_link.get_text(strip=True)
        if not title:
            continue

        # The excerpt <p> sits in a sibling container of the title's card.
        container = title_link.find_parent("article") or title_link.find_parent("div")
        description = ""
        if container:
            excerpt = container.select_one("p.nw-blog-excerpt")
            if excerpt:
                description = excerpt.get_text(strip=True)

        articles.append(
            {
                "title": title,
                "link": link,
                "date": None,
                "description": description or title,
            }
        )

    logger.info(f"Parsed {len(articles)} articles")
    return articles


def fetch_article_date(link: str) -> datetime | None:
    """Fetch an article page and parse its article:published_time meta tag."""
    try:
        html = fetch_page(link)
    except Exception as exc:
        logger.warning(f"Could not fetch {link}: {exc}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta:
        content = meta.get("content", "")
        try:
            date = datetime.fromisoformat(content.replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=pytz.UTC)
            return date
        except ValueError:
            logger.warning(f"Could not parse published_time {content!r} for {link}")
    return None


def generate_rss_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title("Nous Research Blog")
    fg.description("Latest news and updates from Nous Research")
    fg.language("en")
    fg.author({"name": "Nous Research"})
    fg.subtitle("Open-source frontier models, Hermes, Psyche, and distributed training research")
    setup_feed_links(fg, blog_url=BLOG_URL, feed_name=FEED_NAME)

    for article in sort_posts_for_feed(articles, date_field="date"):
        fe = fg.add_entry()
        fe.title(article["title"])
        fe.description(article["description"])
        fe.link(href=article["link"])
        fe.id(article["link"])
        if article.get("date"):
            fe.published(article["date"])

    logger.info(f"Generated RSS feed with {len(articles)} entries")
    return fg


def main() -> bool:
    logger.info(f"Fetching {BLOG_URL}")
    html = fetch_page(BLOG_URL)
    articles = parse_blog_html(html)

    if not articles:
        logger.warning("No articles found. Check the HTML structure.")
        return False

    for article in articles:
        article["date"] = fetch_article_date(article["link"]) or stable_fallback_date(article["link"])
        time.sleep(DETAIL_REQUEST_DELAY_SECONDS)

    feed = generate_rss_feed(articles)
    save_rss_feed(feed, FEED_NAME)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Nous Research Blog RSS feed")
    # --full is accepted for orchestrator compatibility even though the generator has no cache.
    parser.add_argument("--full", action="store_true", help="No-op (Nous has no cache)")
    parser.parse_args()
    main()
