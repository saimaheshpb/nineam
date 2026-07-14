import json
import inspect
import unittest
from datetime import date
from unittest.mock import Mock

from app.services.publication import PublicationDecision, PublicationOutcome
from run_daily import DailyRunResult, _exit_code, run_daily


def completed_context(eval_status="failed"):
    article = {
        "id": 1,
        "eval_status": eval_status,
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
    evaluation = {
        "id": 1,
        "checks_json": json.dumps({"factual_claim_count": 59}),
        "faithfulness_score": 48 / 59,
        "citation_validity_score": 1.0,
        "citation_completeness_score": 49 / 59,
        "contradiction_score": 1.0,
    }
    claims = ([{"verdict": "supported"}] * 48) + ([{"verdict": "unsupported"}] * 11)
    return article, evaluation, claims


def publication_decision(outcome: PublicationOutcome) -> PublicationDecision:
    return PublicationDecision(outcome=outcome, reasons=())


class DailyRunnerTests(unittest.TestCase):
    def test_publication_runner_has_no_ingestion_stage(self):
        self.assertNotIn(
            "ingestion_stage",
            inspect.signature(run_daily).parameters,
        )
        self.assertNotIn("run_ingestion", inspect.getsource(run_daily))

    def test_completed_warning_edition_is_a_no_op(self):
        context = completed_context()
        setup = Mock()
        clustering = Mock()
        generation = Mock()
        context_loader = Mock(return_value=context)

        result = run_daily(
            date(2026, 7, 12),
            setup_stage=setup,
            clustering_stage=clustering,
            generation_stage=generation,
            context_loader=context_loader,
        )

        self.assertTrue(result.no_op)
        self.assertEqual(
            result.decision.outcome,
            PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
        )
        setup.assert_called_once_with()
        clustering.assert_not_called()
        generation.assert_not_called()

    def test_pending_article_is_a_no_op_without_evaluation(self):
        pending_article, _, _ = completed_context(eval_status="pending")
        clustering = Mock()
        generation = Mock()
        context_loader = Mock(return_value=(pending_article, None, []))

        result = run_daily(
            date(2026, 7, 12),
            setup_stage=Mock(),
            clustering_stage=clustering,
            generation_stage=generation,
            context_loader=context_loader,
        )

        self.assertTrue(result.no_op)
        self.assertTrue(result.article_ready)
        clustering.assert_not_called()
        generation.assert_not_called()
        context_loader.assert_called_once_with("2026-07-12")

    def test_new_edition_runs_generation_stages_without_evaluation(self):
        pending_article, _, _ = completed_context(eval_status="pending")
        clustering = Mock()
        generation = Mock(return_value={"title": "New edition"})
        context_loader = Mock(side_effect=[
            (None, None, []),
            (pending_article, None, []),
        ])

        result = run_daily(
            date(2026, 7, 12),
            setup_stage=Mock(),
            clustering_stage=clustering,
            generation_stage=generation,
            context_loader=context_loader,
        )

        self.assertFalse(result.no_op)
        self.assertTrue(result.article_ready)
        self.assertEqual(result.decision.outcome, PublicationOutcome.BLOCKED)
        clustering.assert_called_once_with(date(2026, 7, 12))
        generation.assert_called_once_with("2026-07-12")

    def test_missing_generated_article_is_blocked(self):
        generation = Mock(return_value=None)

        result = run_daily(
            date(2026, 7, 12),
            setup_stage=Mock(),
            clustering_stage=Mock(),
            generation_stage=generation,
            context_loader=Mock(return_value=(None, None, [])),
        )

        self.assertEqual(result.decision.outcome, PublicationOutcome.BLOCKED)
        self.assertFalse(result.no_op)
        self.assertFalse(result.article_ready)

    def test_publisher_has_no_evaluation_stage(self):
        self.assertNotIn(
            "evaluation_stage",
            inspect.signature(run_daily).parameters,
        )
        self.assertNotIn("evaluate_edition", inspect.getsource(run_daily))

    def test_exit_codes_publish_articles_even_when_evaluation_is_blocked(self):
        clean_result = DailyRunResult(
            decision=publication_decision(PublicationOutcome.CLEAN),
            no_op=False,
        )
        warning_result = DailyRunResult(
            decision=publication_decision(PublicationOutcome.PUBLISHABLE_WITH_WARNINGS),
            no_op=False,
        )
        blocked_article_result = DailyRunResult(
            decision=publication_decision(PublicationOutcome.BLOCKED),
            no_op=False,
        )
        blocked_no_article_result = DailyRunResult(
            decision=publication_decision(PublicationOutcome.BLOCKED),
            no_op=False,
            article_ready=False,
        )

        self.assertEqual(_exit_code(clean_result), 0)
        self.assertEqual(_exit_code(warning_result), 0)
        self.assertEqual(_exit_code(blocked_article_result), 0)
        self.assertEqual(_exit_code(blocked_no_article_result), 2)


if __name__ == "__main__":
    unittest.main()
