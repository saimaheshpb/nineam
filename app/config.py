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
        name="The Verge AI",
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        category="ai",
    ),
    NewsSource(
        name="VentureBeat AI",
        url="https://venturebeat.com/category/ai/feed/",
        category="ai",
    ),
    NewsSource(
        name="The Register AI + ML",
        url=(
            "https://api.theregister.com/api/v1/article"
            "?limit=25&orderBy=published"
            "&query=tag%3A%22ai+and+ml%22"
            "&remapper=rss&site_id=2"
        ),
        category="ai",
    ),
    NewsSource(
        name="WIRED AI",
        url="https://www.wired.com/feed/tag/ai/latest/rss",
        category="ai",
    ),
    NewsSource(
        name="The Decoder",
        url="https://the-decoder.com/feed/",
        category="ai",
    ),
]
