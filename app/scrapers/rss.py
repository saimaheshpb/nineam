import feedparser


def get_latest_urls(rss_url: str, limit: int) -> list[str]:
    urls = []

    try:
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:limit]:
            urls.append(entry.link)

        return urls

    except Exception as e:
        print(f"Oops. No fetch RSS feed from {rss_url}. Error: {e}")
        return []
