from dataclasses import dataclass


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str
    category: str
    enabled: bool = True


RSS_SOURCES = [
    NewsSource(
        name="The Verge AI",
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        category="ai",
    ),
    NewsSource(
        name="Ars Technica Technology Lab",
        url="https://feeds.arstechnica.com/arstechnica/technology-lab",
        category="technology",
    ),
    NewsSource(
        name="TechCrunch AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        category="ai",
    ),
    NewsSource(
        name="VentureBeat AI",
        url="https://venturebeat.com/category/ai/feed/",
        category="ai",
    ),
    NewsSource(
        name="OpenAI News",
        url="https://openai.com/news/rss.xml",
        category="ai",
    ),
    NewsSource(
        name="Google DeepMind",
        url="https://deepmind.google/blog/rss.xml",
        category="ai",
    ),
    NewsSource(
        name="Google AI",
        url="https://blog.google/technology/ai/rss/",
        category="ai",
    ),
    NewsSource(
        name="Hugging Face",
        url="https://huggingface.co/blog/feed.xml",
        category="ai",
    ),
    NewsSource(
        name="Berkeley AI Research",
        url="https://bair.berkeley.edu/blog/feed.xml",
        category="ai",
    ),
    NewsSource(
        name="The Gradient",
        url="https://thegradient.pub/rss/",
        category="ai",
    ),
]


YOUTUBE_SOURCE = NewsSource(
    name="ThePrimeTime",
    url="https://www.youtube.com/@ThePrimeTimeagen/videos",
    category="technology",
)
