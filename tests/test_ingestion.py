import unittest
from unittest.mock import Mock, patch

import main
from app.config import RSS_SOURCES


class IngestionSourceTests(unittest.TestCase):
    def test_sources_are_six_ai_only_editorial_feeds(self):
        self.assertEqual(
            [(source.name, source.url) for source in RSS_SOURCES],
            [
                (
                    "TechCrunch AI",
                    "https://techcrunch.com/category/artificial-intelligence/feed/",
                ),
                (
                    "The Verge AI",
                    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
                ),
                (
                    "VentureBeat AI",
                    "https://venturebeat.com/category/ai/feed/",
                ),
                (
                    "The Register AI + ML",
                    (
                        "https://api.theregister.com/api/v1/article"
                        "?limit=25&orderBy=published"
                        "&query=tag%3A%22ai+and+ml%22"
                        "&remapper=rss&site_id=2"
                    ),
                ),
                (
                    "WIRED AI",
                    "https://www.wired.com/feed/tag/ai/latest/rss",
                ),
                (
                    "The Decoder",
                    "https://the-decoder.com/feed/",
                ),
            ],
        )
        self.assertTrue(all(source.enabled for source in RSS_SOURCES))
        self.assertTrue(all(source.category == "ai" for source in RSS_SOURCES))

    @patch("main.extract_structured_data")
    @patch("main.get_article_text")
    @patch("main.get_latest_urls")
    @patch("main.connect_database")
    @patch("main.setup_database")
    def test_requests_five_entries_per_feed_and_skips_exact_duplicates(
        self,
        setup_database,
        connect_database,
        get_latest_urls,
        get_article_text,
        extract_structured_data,
    ):
        cursor = Mock()
        cursor.fetchone.return_value = (1,)
        connection = Mock()
        connection.cursor.return_value = cursor
        connect_database.return_value = connection
        get_latest_urls.side_effect = lambda url, limit: [
            f"{url}article-{index}" for index in range(limit)
        ]

        main.run_ingestion()

        self.assertEqual(main.RSS_ENTRY_LIMIT, 5)
        self.assertEqual(get_latest_urls.call_count, 6)
        for source in RSS_SOURCES:
            get_latest_urls.assert_any_call(source.url, 5)
        self.assertEqual(cursor.execute.call_count, 30)
        get_article_text.assert_not_called()
        extract_structured_data.assert_not_called()
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
