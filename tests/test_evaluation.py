import unittest

from app.services.evaluation import (
    extract_citation_ids,
    validate_citation_ids,
    validate_citation_map, build_sentence_records,
)


def evidence_entry() -> dict:
    return {
        "item_id": 4,
        "fact_number": 1,
        "source_name": "Example News",
        "headline": "Example headline",
        "url": "https://example.com/article",
        "claim": "Google changed Search.",
        "supporting_excerpt": "Google announced changes to Search.",
    }


class EvaluationTests(unittest.TestCase):
    def test_extract_citation_ids_preserves_order(self):
        body = "One fact [S4-F1]. Another [S4-F1][S1-F2]."

        self.assertEqual(
            extract_citation_ids(body),
            ["S4-F1", "S4-F1", "S1-F2"],
        )

    def test_valid_citation_map_has_no_errors(self):
        citation_map = {"S4-F1": evidence_entry()}

        self.assertEqual(validate_citation_map(citation_map), [])

    def test_map_rejects_missing_required_field(self):
        broken_entry = evidence_entry()
        del broken_entry["url"]

        errors = validate_citation_map({"S4-F1": broken_entry})

        self.assertTrue(any("url" in error for error in errors))

    def test_map_rejects_id_metadata_mismatch(self):
        broken_entry = evidence_entry()
        broken_entry["item_id"] = 99

        errors = validate_citation_map({"S4-F1": broken_entry})

        self.assertTrue(any("item_id does not match" in error for error in errors))

    def test_validate_citation_ids_finds_invented_citation(self):
        invalid_ids = validate_citation_ids(
            ["S4-F1", "S999-F1"],
            {"S4-F1": evidence_entry()},
        )

        self.assertEqual(invalid_ids, ["S999-F1"])

    def test_build_sentence_records_keeps_citations(self):
        body = "First fact [S4-F1]. Second fact [S4-F2][S4-F3]."

        records = build_sentence_records(body)

        self.assertEqual(records, [
            {
                "sentence_index": 0,
                "sentence_text": "First fact [S4-F1].",
                "citation_ids": ["S4-F1"],
            },
            {
                "sentence_index": 1,
                "sentence_text": "Second fact [S4-F2][S4-F3].",
                "citation_ids": ["S4-F2", "S4-F3"],
            },
        ])

    def test_build_sentence_records_handles_missing_space(self):
        body = "First fact [S4-F1].Second fact [S4-F2]."

        records = build_sentence_records(body)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["citation_ids"], ["S4-F1"])
        self.assertEqual(records[1]["citation_ids"], ["S4-F2"])


if __name__ == "__main__":
    unittest.main()
