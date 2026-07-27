import unittest
from unittest.mock import Mock, patch

from cluster_articles import load_articles


class EditionAssignmentTests(unittest.TestCase):
    @patch("cluster_articles.connect_database")
    def test_article_query_uses_requested_edition_date(self, connect_database):
        cursor = Mock()
        cursor.fetchall.return_value = []
        connect_database.return_value.cursor.return_value = cursor

        load_articles("2026-07-12")

        query, parameters = cursor.execute.call_args.args
        self.assertIn("edition_date = ?", query)
        self.assertNotIn("processed_at", query)
        self.assertEqual(parameters, ("2026-07-12",))


if __name__ == "__main__":
    unittest.main()
