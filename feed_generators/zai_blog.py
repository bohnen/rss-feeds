"""Generate RSS feed for the Z.ai (Zhipu AI / GLM) release notes.

Source: https://docs.z.ai/release-notes/new-released — Z.ai's official
changelog of GLM model releases. The listing is rendered server-side in
``<div class="update">`` elements (each with ``data-component-part``
attributes for the label/date, description/title, and content), so a plain
``requests`` fetch works. There is no dedicated z.ai blog (z.ai/blog is a
404); this release-notes page is the official announcement stream.
"""

import argparse
import contextlib
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

FEED_NAME = "zai"
BLOG_URL = "https://docs.z.ai/release-notes/new-released"
FEED_TITLE = "Z.ai Release Notes"
FEED_DESCRIPTION = "GLM model releases and announcements from Z.ai (Zhipu AI)"
AUTHOR = "Z.ai"


def parse(html_content: str) -> list[dict]:
    """Extract release entries from the Z.ai release-notes page."""
    soup = BeautifulSoup(html_content, "html.parser")
    articles = []
    seen_links = set()

    for update in soup.select("div.update"):
        date = None

        # The anchor id of each update block is the release date (YYYY-MM-DD).
        update_id = update.get("id", "")
        if update_id:
            with contextlib.suppress(ValueError):
                date = datetime.strptime(update_id, "%Y-%m-%d").replace(tzinfo=pytz.UTC)

        if date is None:
            label = update.select_one('[data-component-part="update-label"]')
            if label:
                with contextlib.suppress(ValueError):
                    date = datetime.strptime(label.get_text(strip=True), "%Y-%m-%d").replace(tzinfo=pytz.UTC)

        title_elem = update.select_one('[data-component-part="update-description"]')
        if not title_elem:
            continue
        title = title_elem.get_text(strip=True)
        if not title:
            continue

        # Build a description from the update content bullets/text.
        content_elem = update.select_one('[data-component-part="update-content"]')
        if content_elem:
            description = " ".join(content_elem.get_text(separator=" ", strip=True).split())
        else:
            description = title

        link = f"{BLOG_URL}#{update_id}" if update_id else BLOG_URL
        if link in seen_links:
            continue
        seen_links.add(link)

        if date is None:
            date = stable_fallback_date(link)

        articles.append(
            {
                "title": title,
                "link": link,
                "date": date,
                "description": description,
            }
        )

    logger.info(f"Parsed {len(articles)} release entries")
    return articles


def generate_rss_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.description(FEED_DESCRIPTION)
    fg.language("en")
    fg.author({"name": AUTHOR})
    fg.subtitle("GLM model releases from Z.ai")
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
    parser.add_argument("--full", action="store_true", help="No-op (Z.ai has no cache)")
    parser.parse_args()
    main()
