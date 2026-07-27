import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import libsql

from app.database.db import create_schema
from import_sqlite_to_turso import import_sqlite_database


def seed_database(connection) -> None:
    connection.execute(
        """
        INSERT INTO items (
            id, url, source_name, source_category, headline, summary,
            full_text, entities, evidence_json, category,
            importance_score, embedding, processed_at, edition_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "https://example.com/story",
            "Example News",
            "ai",
            "Example headline",
            "Example summary",
            "Example full text",
            json.dumps(["Example"]),
            json.dumps([
                {
                    "claim": "Example claim",
                    "supporting_excerpt": "Example excerpt",
                }
            ]),
            "ai",
            8,
            json.dumps([0.1, 0.2]),
            "2026-07-12 01:00:00",
            "2026-07-12",
        ),
    )
    connection.execute(
        """
        INSERT INTO story_clusters (
            id, run_date, representative_headline,
            cluster_size, rank_score, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (1, "2026-07-12", "Example headline", 1, 13.0, "2026-07-12 02:00:00"),
    )
    connection.execute(
        """
        INSERT INTO story_cluster_items (
            id, cluster_id, item_id, similarity_to_representative
        )
        VALUES (?, ?, ?, ?)
        """,
        (1, 1, 1, None),
    )
    connection.execute(
        """
        INSERT INTO generated_articles (
            id, edition_date, title, body, sources_json,
            cluster_ids_json, citation_map_json, generator_model,
            generation_prompt_version, eval_status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "2026-07-12",
            "Example edition",
            "Example article body [S1-F1].",
            json.dumps([{"url": "https://example.com/story"}]),
            json.dumps([1]),
            json.dumps({
                "S1-F1": {
                    "item_id": 1,
                    "fact_number": 1,
                    "source_name": "Example News",
                    "headline": "Example headline",
                    "url": "https://example.com/story",
                    "claim": "Example claim",
                    "supporting_excerpt": "Example excerpt",
                }
            }),
            "test-generator",
            "test-prompt",
            "passed",
            "2026-07-12 03:00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO eval_runs (
            id, generated_article_id, overall_status,
            faithfulness_score, citation_validity_score,
            citation_completeness_score, contradiction_score,
            coverage_score, editorial_quality_score, checks_json,
            judge_model, judge_prompt_version, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            "passed",
            1.0,
            1.0,
            1.0,
            1.0,
            None,
            None,
            json.dumps({"factual_claim_count": 1}),
            "test-judge",
            "test-judge-prompt",
            "2026-07-12 04:00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO claim_evaluations (
            id, eval_run_id, claim_index, claim_text,
            citation_ids_json, citation_valid, verdict,
            confidence, severity, rationale, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            1,
            "Example claim",
            json.dumps(["S1-F1"]),
            1,
            "supported",
            1.0,
            "none",
            "Directly supported.",
            "2026-07-12 05:00:00",
        ),
    )
    connection.commit()


class ImportSQLiteToTursoTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.source_path = Path(self.temporary_directory.name) / "source.db"

        source_connection = sqlite3.connect(self.source_path)
        create_schema(source_connection)
        seed_database(source_connection)
        source_connection.close()

        self.target_connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.target_connection.close()
        self.temporary_directory.cleanup()

    def test_imports_all_tables_and_is_idempotent(self):
        first_result = import_sqlite_database(
            self.source_path,
            self.target_connection,
        )
        second_result = import_sqlite_database(
            self.source_path,
            self.target_connection,
        )

        expected_counts = {
            "items": 1,
            "story_clusters": 1,
            "story_cluster_items": 1,
            "generated_articles": 1,
            "eval_runs": 1,
            "claim_evaluations": 1,
        }
        self.assertTrue(first_result.imported)
        self.assertFalse(second_result.imported)
        self.assertEqual(first_result.table_counts, expected_counts)
        self.assertEqual(second_result.table_counts, expected_counts)

    def test_rejects_nonmatching_existing_target_data(self):
        import_sqlite_database(self.source_path, self.target_connection)
        self.target_connection.execute(
            "UPDATE generated_articles SET title = ? WHERE id = ?",
            ("Different title", 1),
        )
        self.target_connection.commit()

        with self.assertRaisesRegex(
            RuntimeError,
            "does not exactly match",
        ):
            import_sqlite_database(self.source_path, self.target_connection)

    def test_imports_into_libsql_connection(self):
        libsql_connection = libsql.connect(":memory:")

        try:
            result = import_sqlite_database(
                self.source_path,
                libsql_connection,
            )
            item_count = libsql_connection.execute(
                "SELECT COUNT(*) FROM items"
            ).fetchone()[0]
        finally:
            libsql_connection.close()

        self.assertTrue(result.imported)
        self.assertEqual(item_count, 1)

    def test_rolls_back_invalid_relationships(self):
        source_connection = sqlite3.connect(self.source_path)
        source_connection.execute("DELETE FROM story_clusters WHERE id = 1")
        source_connection.commit()
        source_connection.close()

        with self.assertRaisesRegex(
            RuntimeError,
            "Relationship verification failed",
        ):
            import_sqlite_database(self.source_path, self.target_connection)

        item_count = self.target_connection.execute(
            "SELECT COUNT(*) FROM items"
        ).fetchone()[0]
        self.assertEqual(item_count, 0)

    def test_rolls_back_invalid_json(self):
        source_connection = sqlite3.connect(self.source_path)
        source_connection.execute(
            "UPDATE items SET evidence_json = ? WHERE id = ?",
            ("not-json", 1),
        )
        source_connection.commit()
        source_connection.close()

        with self.assertRaisesRegex(
            RuntimeError,
            "Invalid JSON",
        ):
            import_sqlite_database(self.source_path, self.target_connection)

        item_count = self.target_connection.execute(
            "SELECT COUNT(*) FROM items"
        ).fetchone()[0]
        self.assertEqual(item_count, 0)


if __name__ == "__main__":
    unittest.main()
