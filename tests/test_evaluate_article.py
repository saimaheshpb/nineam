import json
import unittest
from unittest.mock import Mock, patch

import evaluate_article
from app.services import llm
from evaluate_article import (
    EvaluationCallPacer,
    extract_claims_from_article,
    judge_factual_claims,
    run_deterministic_checks,
    split_into_batches,
)


class EvaluationBatchTests(unittest.TestCase):
    def test_default_batch_size_is_ten(self):
        batches = split_into_batches([{"id": index} for index in range(21)])

        self.assertEqual([len(batch) for batch in batches], [10, 10, 1])

    @patch("app.services.llm.client.models.generate_content")
    def test_atomic_extractor_accepts_ten_and_rejects_eleven(self, generate):
        generate.return_value.text = json.dumps({"claims": []})

        self.assertEqual(llm.extract_atomic_claims([{}] * 10), [])
        with self.assertRaisesRegex(ValueError, "at most ten sentences"):
            llm.extract_atomic_claims([{}] * 11)

    @patch("app.services.llm.client.models.generate_content")
    def test_claim_judge_accepts_ten_and_rejects_eleven(self, generate):
        claims = [
            {
                "claim_index": index,
                "claim_text": f"Claim {index}",
                "citation_ids": ["S1-F1"],
            }
            for index in range(1, 11)
        ]
        citation_map = {
            "S1-F1": {
                "source_name": "Example",
                "url": "https://example.com",
                "claim": "Evidence claim",
                "supporting_excerpt": "Evidence excerpt",
            }
        }
        generate.return_value.text = json.dumps({
            "verdicts": [
                {
                    "claim_index": index,
                    "verdict": "supported",
                    "confidence": 1.0,
                    "severity": "none",
                    "rationale": "Supported.",
                }
                for index in range(1, 11)
            ]
        })

        self.assertEqual(len(llm.judge_claim_batch(claims, citation_map)), 10)
        with self.assertRaisesRegex(ValueError, "at most ten claims"):
            llm.judge_claim_batch(claims + [claims[0]], citation_map)


class EvaluationPacerTests(unittest.TestCase):
    def test_seven_calls_are_spaced_with_group_cooldowns(self):
        sleep = Mock()
        pacer = EvaluationCallPacer(sleep_fn=sleep)

        for _ in range(7):
            pacer.before_call()

        self.assertEqual(pacer.call_count, 7)
        self.assertEqual(
            sleep.call_args_list,
            [
                unittest.mock.call(20),
                unittest.mock.call(20),
                unittest.mock.call(60),
                unittest.mock.call(20),
                unittest.mock.call(20),
                unittest.mock.call(60),
            ],
        )

    @patch("evaluate_article.judge_claim_batch")
    @patch("evaluate_article.extract_atomic_claims")
    @patch("evaluate_article.build_sentence_records")
    def test_one_counter_crosses_extraction_and_judging(
        self,
        build_records,
        extract_atomic,
        judge_batch,
    ):
        build_records.return_value = [
            {
                "sentence_index": index,
                "citation_ids": ["S1-F1"],
            }
            for index in range(20)
        ]
        extract_atomic.side_effect = lambda batch: [
            {
                "source_sentence_index": record["sentence_index"],
                "claim_text": f"Claim {record['sentence_index']}",
                "is_factual": True,
            }
            for record in batch
        ]
        judge_batch.side_effect = lambda batch, _citation_map: [
            {
                "claim_index": claim["claim_index"],
                "verdict": "supported",
                "confidence": 1.0,
                "severity": "none",
                "rationale": "Supported.",
            }
            for claim in batch
        ]
        sleep = Mock()
        pacer = EvaluationCallPacer(sleep_fn=sleep)

        claims = extract_claims_from_article("Body", pacer)
        results = judge_factual_claims(
            claims,
            {"S1-F1": {}},
            pacer,
        )

        self.assertEqual(len(results), 20)
        self.assertEqual(pacer.call_count, 4)
        self.assertEqual(
            sleep.call_args_list,
            [
                unittest.mock.call(20),
                unittest.mock.call(20),
                unittest.mock.call(60),
            ],
        )


class DeterministicWordCountTests(unittest.TestCase):
    @staticmethod
    def article_with_word_count(count):
        return {
            "title": "NineAM edition",
            "body": " ".join(["word"] * count),
            "sources_json": json.dumps([{"url": "https://example.com"}]),
            "cluster_ids_json": json.dumps([1]),
            "citation_map_json": json.dumps({}),
        }

    def test_399_words_fails_the_length_check(self):
        result = run_deterministic_checks(self.article_with_word_count(399))

        self.assertEqual(result["checks"]["body_word_count"], 399)
        self.assertFalse(result["checks"]["body_within_target_length"])

    def test_400_words_passes_the_length_check(self):
        result = run_deterministic_checks(self.article_with_word_count(400))

        self.assertEqual(result["checks"]["body_word_count"], 400)
        self.assertTrue(result["checks"]["body_within_target_length"])

    def test_arbitrarily_larger_article_passes_the_length_check(self):
        result = run_deterministic_checks(self.article_with_word_count(5000))

        self.assertEqual(result["checks"]["body_word_count"], 5000)
        self.assertTrue(result["checks"]["body_within_target_length"])


class EvaluationCliTests(unittest.TestCase):
    @patch("evaluate_article.parse_edition_date", return_value="2026-07-14")
    @patch("evaluate_article.evaluate_edition", side_effect=RuntimeError("503"))
    def test_runtime_failure_returns_one(self, _evaluate, _parse):
        self.assertEqual(evaluate_article.main(), 1)

    @patch("evaluate_article.parse_edition_date", return_value="2026-07-14")
    @patch("evaluate_article.evaluate_edition", return_value=None)
    def test_missing_article_returns_two(self, _evaluate, _parse):
        self.assertEqual(evaluate_article.main(), 2)

    @patch("evaluate_article.parse_edition_date", return_value="2026-07-14")
    @patch("evaluate_article.evaluate_edition")
    def test_completed_evaluation_returns_zero(self, evaluate, _parse):
        evaluate.return_value = {
            "overall_status": "failed",
            "citation_validity_score": 1.0,
            "checks": {
                "invalid_citation_ids": [],
                "citation_map_errors": [],
            },
        }

        self.assertEqual(evaluate_article.main(), 0)


if __name__ == "__main__":
    unittest.main()
