"""Generate RSS feed for the Kimi (Moonshot AI) research blog.

Source: https://www.kimi.com/en/blog/ — Moonshot AI's official English blog
listing (model releases, research posts). The listing is rendered
server-side as cards: each card contains an overlay ``<a aria-label=...>``
pointing to ``/en/blog/<slug>``, an ``h4.card-title`` and a ``p.card-date``
(YYYY-MM-DD), so a plain ``requests`` fetch works. moonshot.ai itself is a
JS shell with no scrapeable news listing.
"""

import argparse
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

FEED_NAME = "moonshot"
BLOG_URL = "https://www.kimi.com/en/blog/"
FEED_TITLE = "Kimi Blog (Moonshot AI)"
FEED_DESCRIPTION = "Model releases and research posts from Moonshot AI (Kimi)"
AUTHOR = "Moonshot AI"


def parse(html_content: str) -> list[dict]:
    """Extract blog cards from the Kimi blog listing page."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    seen_links = set()

    # Each card has an overlay link with an aria-label; nav/footer links to
    # /en/blog/ have no aria-label, so this filters to actual post cards.
    for card_link in soup.select('a[aria-label][href^="/en/blog/"]'):
        href = card_link.get("href", "")
        if not href or href.rstrip("/") == "/en/blog":
            continue

        link = f"https://www.kimi.com{href}"
        if link in seen_links:
            continue

        card = card_link.find_parent("div")
        title_elem = card.select_one(".card-title") if card else None
        title = title_elem.get_text(strip=True) if title_elem else card_link.get("aria-label", "").strip()
        if not title:
            continue
        seen_links.add(link)

        date = None
        date_elem = card.select_one(".card-date") if card else None
        if date_elem:
            try:
                date = datetime.strptime(date_elem.get_text(strip=True), "%Y-%m-%d").replace(tzinfo=pytz.UTC)
            except ValueError:
                logger.warning(f"Could not parse date: {date_elem.get_text(strip=True)!r}")

        if date is None:
            date = stable_fallback_date(link)

        articles.append(
            {
                "title": title,
                "link": link,
                "date": date,
                "description": title,
            }
        )

    logger.info(f"Parsed {len(articles)} blog posts")
    return articles


def generate_rss_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.description(FEED_DESCRIPTION)
    fg.language("en")
    fg.author({"name": AUTHOR})
    fg.subtitle("Kimi model releases and research from Moonshot AI")
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
    try:
        html = fetch_page(BLOG_URL)
        articles = parse(html)

        if not articles:
            logger.warning("No articles found. Check the HTML structure.")
            return False

        feed = generate_rss_feed(articles)
        save_rss_feed(feed, FEED_NAME)
        logger.info("Done!")
        return True
    except Exception as e:
        logger.error(f"Failed to generate {FEED_NAME} feed: {e!s}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Generate the {FEED_TITLE} RSS feed")
    # --full is accepted for orchestrator compatibility even though the generator has no cache.
    parser.add_argument("--full", action="store_true", help="No-op (Kimi has no cache)")
    parser.parse_args()
    main()
