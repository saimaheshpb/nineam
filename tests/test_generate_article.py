import inspect
import json
import unittest
from unittest.mock import Mock, patch

import generate_article
from app.services import llm


class GenerationPromptTests(unittest.TestCase):
    @patch("app.services.llm._request_structured")
    def test_generation_requires_at_least_400_words_without_maximum(
        self,
        request_structured,
    ):
        request_structured.return_value = {
            "title": "Example title",
            "body": "Example body",
        }

        result = llm.generate_daily_article("Evidence brief")

        role, model, schema, prompt, brief = request_structured.call_args.args
        self.assertEqual(role, "article_generation")
        self.assertEqual(model, llm.GENERATOR_MODEL)
        self.assertIs(schema, llm.GeneratedArticle)
        self.assertEqual(brief, "Evidence brief")
        self.assertEqual(request_structured.call_args.kwargs["reasoning_effort"], "low")
        self.assertIn("at least 400 words", prompt)
        self.assertIn("no maximum word count", prompt)
        self.assertNotIn("1200", prompt)
        self.assertEqual(llm.GENERATION_PROMPT_VERSION, "citation-aware-v2")
        self.assertEqual(result["title"], "Example title")


class ClusterSelectionTests(unittest.TestCase):
    @patch("generate_article.connect_database")
    def test_top_clusters_default_to_three_in_descending_rank_order(
        self,
        connect_database,
    ):
        cursor = Mock()
        cursor.fetchall.return_value = []
        connect_database.return_value.cursor.return_value = cursor

        clusters = generate_article.load_top_clusters("2026-07-17")

        query, parameters = cursor.execute.call_args.args
        self.assertEqual(clusters, [])
        self.assertIn("ORDER BY rank_score DESC", query)
        self.assertIn("LIMIT ?", query)
        self.assertEqual(parameters, ("2026-07-17", 3))
        self.assertEqual(
            inspect.signature(
                generate_article.load_top_clusters
            ).parameters["limit"].default,
            3,
        )


if __name__ == "__main__":
    unittest.main()
