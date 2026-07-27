import unittest
from datetime import date
from pathlib import Path
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

        main.run_ingestion(date(2026, 7, 27))

        self.assertEqual(main.RSS_ENTRY_LIMIT, 5)
        self.assertEqual(get_latest_urls.call_count, 6)
        for source in RSS_SOURCES:
            get_latest_urls.assert_any_call(source.url, 5)
        self.assertEqual(cursor.execute.call_count, 30)
        get_article_text.assert_not_called()
        extract_structured_data.assert_not_called()
        connection.close.assert_called_once_with()

    @patch("main.time.sleep")
    @patch("main.find_semantic_match", return_value=None)
    @patch("main.get_embedding", return_value=[0.1, 0.2])
    @patch("main.extract_structured_data")
    @patch("main.get_article_text", return_value="Article text")
    @patch("main.get_latest_urls", return_value=["https://example.com/new"])
    @patch("main.connect_database")
    @patch("main.setup_database")
    @patch("main.RSS_SOURCES", [RSS_SOURCES[0]])
    def test_delayed_run_saves_requested_edition_date(
        self,
        setup_database,
        connect_database,
        _get_latest_urls,
        _get_article_text,
        extract_structured_data,
        _get_embedding,
        _find_semantic_match,
        _sleep,
    ):
        cursor = Mock()
        cursor.fetchone.return_value = None
        connection = Mock()
        connection.cursor.return_value = cursor
        connect_database.return_value = connection
        extract_structured_data.return_value = {
            "headline": "Example headline",
            "summary": "Example summary",
            "entities": [],
            "key_facts": [],
            "category": "ai",
            "importance_score": 8,
        }

        main.run_ingestion(date(2026, 7, 26))

        insert_query, insert_parameters = cursor.execute.call_args_list[-1].args
        self.assertIn("edition_date", insert_query)
        self.assertEqual(insert_parameters[-1], "2026-07-26")
        connection.commit.assert_called_once_with()

    def test_workflow_passes_same_resolved_date_to_ingestion_and_generation(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily.yml"
        ).read_text(encoding="utf-8")

        resolved_date = '"${{ steps.edition.outputs.date }}"'
        self.assertIn(
            f"python main.py --edition-date {resolved_date}",
            workflow,
        )
        self.assertIn(
            f'python run_daily.py --edition-date {resolved_date}',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
