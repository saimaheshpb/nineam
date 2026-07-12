import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.services.publication import PublicationDecision, PublicationOutcome
from build_site import (
    SiteEdition,
    SourceEntry,
    _source_entries,
    build_site,
    load_site_edition,
    render_site,
)


def article() -> dict:
    return {
        "edition_date": "2026-07-12",
        "title": "<NineAM> edition",
        "body": "<b>First</b> fact [S1-F1].\n\nSecond fact [S1-F1].",
        "sources_json": json.dumps([
            {
                "source_name": "Example <News>",
                "headline": "Example headline",
                "url": "https://example.com/story",
            }
        ]),
        "citation_map_json": json.dumps({
            "S1-F1": {
                "item_id": 1,
                "fact_number": 1,
                "source_name": "Example <News>",
                "headline": "Example headline",
                "url": "https://example.com/story",
                "claim": "First fact.",
                "supporting_excerpt": "First fact.",
            }
        }),
        "cluster_ids_json": "[1]",
    }


def warning_decision() -> PublicationDecision:
    return PublicationDecision(
        outcome=PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
        reasons=("Warning fixture",),
        factual_claim_count=59,
        supported_claim_count=48,
        contradicted_claim_count=0,
        support_rate=48 / 59,
        contradiction_rate=0.0,
        citation_validity_score=1.0,
        citation_completeness_score=49 / 59,
    )


def edition() -> SiteEdition:
    raw_article = article()
    citation_map = json.loads(raw_article["citation_map_json"])
    return SiteEdition(
        article=raw_article,
        decision=warning_decision(),
        claim_evaluations=(
            [{"verdict": "supported"}] * 48
            + [{"verdict": "unsupported"}] * 11
        ),
        sources=[
            SourceEntry(
                source_name="Example <News>",
                headline="Example headline",
                url="https://example.com/story",
            )
        ],
        citation_map=citation_map,
        cluster_headlines=["Example <cluster>"],
        edition_item_count=4,
    )


class StaticSiteTests(unittest.TestCase):
    def test_page_escapes_generated_content_and_resolves_citations(self):
        page = render_site(edition())

        self.assertIn("&lt;NineAM&gt; edition", page)
        self.assertIn("&lt;b&gt;First&lt;/b&gt;", page)
        self.assertIn("&lt;News&gt;", page)
        self.assertNotIn("[S1-F1]", page)
        self.assertIn('href="#source-01"', page)
        self.assertIn('id="source-01"', page)
        self.assertGreaterEqual(page.count('<p class="'), 2)

    def test_page_renders_warning_evaluation_metrics(self):
        page = render_site(edition())

        self.assertIn("Source-grounded evaluation", page)
        self.assertIn("Published with warnings", page)
        self.assertIn("11 factual claims were not fully supported", page)
        self.assertIn("48 / 59", page)
        self.assertIn("100%", page)
        self.assertIn("83%", page)

    def test_sources_are_deduplicated_by_url(self):
        raw_article = article()
        duplicate = json.loads(raw_article["sources_json"])[0]
        raw_article["sources_json"] = json.dumps([duplicate, duplicate])
        citation_map = json.loads(raw_article["citation_map_json"])

        sources = _source_entries(raw_article, citation_map)

        self.assertEqual(len(sources), 1)

    @patch("build_site.load_edition_context", return_value=(None, None, []))
    def test_blocked_edition_is_rejected(self, _load_context):
        with self.assertRaisesRegex(ValueError, "blocked"):
            load_site_edition(date(2026, 7, 12))

    @patch("build_site.load_site_edition", return_value=edition())
    def test_build_writes_html_and_styles(self, _load_site_edition):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist"

            decision = build_site(
                date(2026, 7, 12),
                output,
            )

            self.assertEqual(
                decision.outcome,
                PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
            )
            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "styles.css").is_file())


if __name__ == "__main__":
    unittest.main()
