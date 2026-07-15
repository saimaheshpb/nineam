import unittest
from unittest.mock import patch

from generate_article import GENERATION_CLUSTER_LIMIT, generate_edition


class GenerationClusterSelectionTests(unittest.TestCase):
    @patch("generate_article.load_top_clusters", return_value=[])
    def test_generation_selects_five_ranked_clusters(self, load_top_clusters):
        self.assertEqual(GENERATION_CLUSTER_LIMIT, 5)

        self.assertIsNone(generate_edition("2026-07-15"))

        load_top_clusters.assert_called_once_with(
            "2026-07-15",
            limit=5,
        )


if __name__ == "__main__":
    unittest.main()
