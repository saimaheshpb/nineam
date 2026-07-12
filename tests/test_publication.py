import json
import unittest

from app.services.publication import PublicationOutcome, decide_publication


def article() -> dict:
    return {
        "eval_status": "failed",
        "title": "NineAM edition",
        "body": "A supported fact happened [S1-F1].",
        "sources_json": json.dumps([
            {
                "source_name": "Example News",
                "headline": "Example headline",
                "url": "https://example.com/story",
            }
        ]),
        "citation_map_json": json.dumps({
            "S1-F1": {
                "item_id": 1,
                "fact_number": 1,
                "source_name": "Example News",
                "headline": "Example headline",
                "url": "https://example.com/story",
                "claim": "A supported fact happened.",
                "supporting_excerpt": "A supported fact happened.",
            }
        }),
    }


def evaluation(claim_count: int, **overrides) -> dict:
    result = {
        "checks_json": json.dumps({"factual_claim_count": claim_count}),
        "faithfulness_score": 1.0,
        "citation_validity_score": 1.0,
        "citation_completeness_score": 1.0,
        "contradiction_score": 1.0,
    }
    result.update(overrides)
    return result


def claims(supported: int, unsupported: int = 0, contradicted: int = 0) -> list[dict]:
    verdicts = (
        ["supported"] * supported
        + ["unsupported"] * unsupported
        + ["contradicted"] * contradicted
    )
    return [{"verdict": verdict} for verdict in verdicts]


class PublicationPolicyTests(unittest.TestCase):
    def test_all_supported_claims_are_clean(self):
        decision = decide_publication(article(), evaluation(2), claims(2))

        self.assertEqual(decision.outcome, PublicationOutcome.CLEAN)
        self.assertEqual(decision.support_rate, 1.0)

    def test_current_48_of_59_case_is_publishable_with_warnings(self):
        decision = decide_publication(
            article(),
            evaluation(
                59,
                faithfulness_score=48 / 59,
                citation_completeness_score=49 / 59,
            ),
            claims(48, unsupported=11),
        )

        self.assertEqual(
            decision.outcome,
            PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
        )
        self.assertAlmostEqual(decision.support_rate, 48 / 59)
        self.assertEqual(decision.contradicted_claim_count, 0)

    def test_less_than_half_supported_is_blocked(self):
        decision = decide_publication(
            article(),
            evaluation(59, faithfulness_score=29 / 59),
            claims(29, unsupported=30),
        )

        self.assertEqual(decision.outcome, PublicationOutcome.BLOCKED)
        self.assertIn("Fewer than 50%", decision.reasons[0])

    def test_twenty_percent_contradicted_is_blocked(self):
        decision = decide_publication(
            article(),
            evaluation(10, faithfulness_score=0.8, contradiction_score=0.8),
            claims(8, contradicted=2),
        )

        self.assertEqual(decision.outcome, PublicationOutcome.BLOCKED)
        self.assertIn("At least 20%", decision.reasons[0])

    def test_incomplete_claim_evaluation_is_blocked(self):
        decision = decide_publication(article(), evaluation(2), claims(1))

        self.assertEqual(decision.outcome, PublicationOutcome.BLOCKED)
        self.assertIn("Evaluation is incomplete", decision.reasons[0])

    def test_pending_article_cannot_use_an_older_valid_evaluation(self):
        pending_article = article()
        pending_article["eval_status"] = "pending"

        decision = decide_publication(
            pending_article,
            evaluation(1),
            claims(1),
        )

        self.assertEqual(decision.outcome, PublicationOutcome.BLOCKED)
        self.assertTrue(any("has not completed evaluation" in reason for reason in decision.reasons))

    def test_malformed_article_is_blocked(self):
        malformed_article = article()
        malformed_article["citation_map_json"] = "not-json"

        decision = decide_publication(
            malformed_article,
            evaluation(1),
            claims(1),
        )

        self.assertEqual(decision.outcome, PublicationOutcome.BLOCKED)
        self.assertTrue(any("citation_map_json" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()
