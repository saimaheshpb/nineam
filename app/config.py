from dataclasses import dataclass


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str
    category: str
    enabled: bool = True


RSS_SOURCES = [
    NewsSource(
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        category="ai",
    ),
    NewsSource(
        name="The Verge",
        url="https://www.theverge.com/rss/index.xml",
        category="technology",
    ),
    NewsSource(
        name="MIT Technology Review",
        url="https://www.technologyreview.com/feed/",
        category="technology",
    ),
    NewsSource(
        name="VentureBeat AI",
        url="https://venturebeat.com/category/ai/feed/",
        category="ai",
    ),
    NewsSource(
        name="Ars Technica",
        url="https://feeds.arstechnica.com/arstechnica/index",
        category="technology",
    ),
]
