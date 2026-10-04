"""Generate RSS feed for the Qwen Blog.

https://qwen.ai/blog is a fully client-rendered SPA (ICE/React, renderMode:
"CSR"): the raw HTML contains no article links, and its internal article API
(/api/v2/article/retrieval) returns an empty list without runtime parameters
we cannot reproduce with plain requests.

The official Qwen team blog is, however, published on GitHub Pages at
https://qwenlm.github.io/blog/ (linked from qwen.ai/research), which provides
a first-party RSS feed at https://qwenlm.github.io/blog/index.xml. This
generator wraps that source feed into the repo-style feed output.
"""

import argparse
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import pytz
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

FEED_NAME = "qwen"
SOURCE_FEED_URL = "https://qwenlm.github.io/blog/index.xml"
BLOG_URL = "https://qwen.ai/blog"


def parse_source_feed(xml_content: str) -> list[dict]:
    """Extract articles from the QwenLM GitHub Pages RSS feed."""
    root = ElementTree.fromstring(xml_content)
    articles = []
    seen_links = set()

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None or not (title_el.text or "").strip():
            continue

        link = (link_el.text or "").strip()
        if not link or link in seen_links:
            continue
        seen_links.add(link)

        title = title_el.text.strip()
        description_el = item.find("description")

        date = None
        pub_date_el = item.find("pubDate")
        if pub_date_el is not None and pub_date_el.text:
            try:
                date = parsedate_to_datetime(pub_date_el.text.strip())
                if date.tzinfo is None:
                    date = date.replace(tzinfo=pytz.UTC)
            except (TypeError, ValueError):
                logger.warning(f"Could not parse pubDate: {pub_date_el.text!r}")
        if not date:
            date = stable_fallback_date(link)

        articles.append(
            {
                "title": title,
                "link": link,
                "date": date,
                "description": (description_el.text or title).strip() if description_el is not None else title,
            }
        )

    logger.info(f"Parsed {len(articles)} articles")
    return articles


def generate_rss_feed(articles: list[dict]) -> FeedGenerator:
    fg = FeedGenerator()
    fg.title("Qwen Blog")
    fg.description("Latest research and updates from the Qwen team")
    fg.language("en")
    fg.author({"name": "Qwen"})
    fg.subtitle("Qwen model releases, research, and open-source updates")
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
    logger.info(f"Fetching {SOURCE_FEED_URL}")
    xml_content = fetch_page(SOURCE_FEED_URL)
    articles = parse_source_feed(xml_content)

    if not articles:
        logger.warning("No articles found. Check the source feed structure.")
        return False

    feed = generate_rss_feed(articles)
    save_rss_feed(feed, FEED_NAME)
    logger.info("Done!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Qwen Blog RSS feed")
    # --full is accepted for orchestrator compatibility even though the generator has no cache.
    parser.add_argument("--full", action="store_true", help="No-op (Qwen has no cache)")
    parser.parse_args()
    main()
