import unittest
from datetime import date
from unittest.mock import Mock, patch

from cluster_articles import edition_window_utc, load_articles


class EditionWindowTests(unittest.TestCase):
    def test_window_uses_eight_am_ist_and_is_one_day_long(self):
        start, end = edition_window_utc(date(2026, 7, 12))

        self.assertEqual(start, "2026-07-11 02:30:00")
        self.assertEqual(end, "2026-07-12 02:30:00")

    @patch("cluster_articles.connect_database")
    def test_article_query_is_start_inclusive_and_end_exclusive(self, connect_database):
        cursor = Mock()
        cursor.fetchall.return_value = []
        connect_database.return_value.cursor.return_value = cursor

        load_articles("2026-07-11 02:30:00", "2026-07-12 02:30:00")

        query, parameters = cursor.execute.call_args.args
        self.assertIn("processed_at >= ?", query)
        self.assertIn("processed_at < ?", query)
        self.assertEqual(
            parameters,
            ("2026-07-11 02:30:00", "2026-07-12 02:30:00"),
        )


if __name__ == "__main__":
    unittest.main()
