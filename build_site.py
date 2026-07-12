"""Build NineAM's single-edition static article site."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from app.database.db import connect_database
from app.services.publication import (
    PublicationDecision,
    PublicationOutcome,
    decide_publication,
)
from cluster_articles import edition_window_utc
from run_daily import load_edition_context

BASE_DIR = Path(__file__).resolve().parent
STYLES_PATH = BASE_DIR / "app" / "assets" / "editorial.css"
CITATION_PATTERN = re.compile(r"\[(S\d+-F\d+)\]")


@dataclass(frozen=True)
class SourceEntry:
    source_name: str
    headline: str
    url: str


@dataclass(frozen=True)
class SiteEdition:
    article: dict
    decision: PublicationDecision
    claim_evaluations: list[dict]
    sources: list[SourceEntry]
    citation_map: dict
    cluster_headlines: list[str]
    edition_item_count: int


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Edition date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist"),
        help="Directory to receive index.html and styles.css.",
    )
    return parser.parse_args()


def _parse_json(value: str, field_name: str):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field_name} is invalid JSON: {error}") from error


def _require_safe_url(url: str) -> str:
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError(f"Source URL must use http or https: {url}")
    return url


def _source_entries(article: dict, citation_map: dict) -> list[SourceEntry]:
    raw_sources = _parse_json(article["sources_json"], "sources_json")
    if not isinstance(raw_sources, list):
        raise ValueError("sources_json must contain a list.")

    entries = []
    seen_urls = set()

    def add_source(source_name: str, headline: str, url: str) -> None:
        safe_url = _require_safe_url(url)
        if safe_url in seen_urls:
            return
        entries.append(SourceEntry(source_name, headline, safe_url))
        seen_urls.add(safe_url)

    for source in raw_sources:
        add_source(
            source["source_name"],
            source["headline"],
            source["url"],
        )

    for evidence in citation_map.values():
        add_source(
            evidence["source_name"],
            evidence["headline"],
            evidence["url"],
        )

    return entries


def _load_cluster_headlines(article: dict) -> list[str]:
    cluster_ids = _parse_json(article["cluster_ids_json"], "cluster_ids_json")
    if not isinstance(cluster_ids, list):
        raise ValueError("cluster_ids_json must contain a list.")
    if not cluster_ids:
        return []

    placeholders = ", ".join("?" for _ in cluster_ids)
    conn = connect_database()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT id, representative_headline
            FROM story_clusters
            WHERE id IN ({placeholders})
            """,
            tuple(cluster_ids),
        )
        headlines_by_id = {
            row[0]: row[1]
            for row in cursor.fetchall()
        }
    finally:
        conn.close()

    return [
        headlines_by_id[cluster_id]
        for cluster_id in cluster_ids
        if cluster_id in headlines_by_id
    ]


def _edition_item_count(edition_date: date) -> int:
    window_start, window_end = edition_window_utc(edition_date)
    conn = connect_database()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM items
            WHERE processed_at >= ?
              AND processed_at < ?
            """,
            (window_start, window_end),
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()


def load_site_edition(edition_date: date) -> SiteEdition:
    article, evaluation, claim_evaluations = load_edition_context(
        edition_date.isoformat()
    )
    decision = decide_publication(article, evaluation, claim_evaluations)

    if decision.outcome == PublicationOutcome.BLOCKED:
        reasons = "; ".join(decision.reasons)
        raise ValueError(f"Edition is blocked and cannot be rendered: {reasons}")

    assert article is not None
    citation_map = _parse_json(article["citation_map_json"], "citation_map_json")
    if not isinstance(citation_map, dict):
        raise ValueError("citation_map_json must contain an object.")

    return SiteEdition(
        article=article,
        decision=decision,
        claim_evaluations=claim_evaluations,
        sources=_source_entries(article, citation_map),
        citation_map=citation_map,
        cluster_headlines=_load_cluster_headlines(article),
        edition_item_count=_edition_item_count(edition_date),
    )


def _format_edition_date(edition_date: str) -> str:
    return date.fromisoformat(edition_date).strftime("%B %-d, %Y")


def _reading_time(body: str) -> int:
    word_count = len(re.findall(r"\b\w+(?:[-']\w+)*\b", body))
    return max(1, round(word_count / 200))


def _percentage(value: float | None) -> str:
    return f"{(value or 0) * 100:.0f}%"


def _source_numbers(sources: list[SourceEntry]) -> dict[str, int]:
    return {
        source.url: index
        for index, source in enumerate(sources, start=1)
    }


def render_article_body(
        body: str,
        citation_map: dict,
        source_numbers: dict[str, int],
) -> str:
    """Escapes generated prose before replacing citations with safe anchors."""
    def render_paragraph(paragraph: str, is_lead: bool) -> str:
        parts = []
        position = 0
        for match in CITATION_PATTERN.finditer(paragraph):
            parts.append(html.escape(paragraph[position:match.start()]))
            citation_id = match.group(1)
            evidence = citation_map.get(citation_id)
            if not isinstance(evidence, dict):
                raise ValueError(f"Citation {citation_id} is missing from the map.")
            source_number = source_numbers.get(evidence.get("url"))
            if source_number is None:
                raise ValueError(f"Citation {citation_id} has no source-list entry.")
            parts.append(
                '<sup class="source-ref"><a href="#source-'
                f"{source_number:02d}\" aria-label=\"View source {source_number}\">"
                f"{source_number:02d}</a></sup>"
            )
            position = match.end()
        parts.append(html.escape(paragraph[position:]))
        lead_class = " lead" if is_lead else ""
        return f'<p class="{lead_class.strip()}">{"".join(parts)}</p>'

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", body)
        if paragraph.strip()
    ]
    if len(paragraphs) == 1:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraphs[0])
        paragraphs = [
            " ".join(sentences[index:index + 3])
            for index in range(0, len(sentences), 3)
        ]
    if not paragraphs:
        raise ValueError("Generated article body has no renderable paragraphs.")

    return "\n".join(
        render_paragraph(paragraph, index == 0)
        for index, paragraph in enumerate(paragraphs)
    )


def _render_sources(sources: list[SourceEntry]) -> str:
    return "\n".join(
        '<li id="source-{number:02d}"><a href="{url}" target="_blank" '
        'rel="noreferrer">{source_name}</a><span>{headline}</span></li>'.format(
            number=index,
            url=html.escape(source.url, quote=True),
            source_name=html.escape(source.source_name),
            headline=html.escape(source.headline),
        )
        for index, source in enumerate(sources, start=1)
    )


def _render_threads(cluster_headlines: list[str]) -> str:
    if not cluster_headlines:
        return "<li>No selected clusters</li>"
    return "\n".join(
        f"<li>{html.escape(headline)}</li>"
        for headline in cluster_headlines
    )


def _render_evaluation(edition: SiteEdition) -> str:
    decision = edition.decision
    unsupported_count = sum(
        claim.get("verdict") != "supported"
        for claim in edition.claim_evaluations
    )
    status_class = "warning" if (
        decision.outcome == PublicationOutcome.PUBLISHABLE_WITH_WARNINGS
    ) else "clean"
    status_label = (
        "Published with warnings"
        if status_class == "warning"
        else "Strict evaluation passed"
    )
    status_copy = (
        f"This edition is published with warnings: {unsupported_count} factual "
        "claims were not fully supported by their cited evidence."
        if status_class == "warning"
        else "Every evaluated factual claim was supported by its cited evidence."
    )

    return f"""
    <section class="evaluation" aria-labelledby="evaluation-heading">
        <div class="evaluation-intro">
            <p class="eyebrow">Transparency</p>
            <h2 id="evaluation-heading">Source-grounded evaluation</h2>
            <p>NineAM checks each factual claim against the evidence cited beside it.
            These measures show source support, not objective truth verification.</p>
        </div>
        <div class="evaluation-status {status_class}">
            <strong>{status_label}</strong>
            <span>{html.escape(status_copy)}</span>
        </div>
        <dl class="evaluation-grid">
            <div><dt>Claims evaluated</dt><dd>{decision.factual_claim_count}</dd></div>
            <div><dt>Claims supported</dt><dd>{decision.supported_claim_count} / {decision.factual_claim_count} <small>({_percentage(decision.support_rate)})</small></dd></div>
            <div><dt>Citation validity</dt><dd>{_percentage(decision.citation_validity_score)}</dd></div>
            <div><dt>Citation completeness</dt><dd>{_percentage(decision.citation_completeness_score)}</dd></div>
            <div><dt>Contradicted claims</dt><dd>{decision.contradicted_claim_count}</dd></div>
        </dl>
    </section>
    """


def render_site(edition: SiteEdition) -> str:
    article = edition.article
    source_numbers = _source_numbers(edition.sources)
    article_body = render_article_body(
        article["body"],
        edition.citation_map,
        source_numbers,
    )
    edition_date = _format_edition_date(article["edition_date"])
    edition_year = date.fromisoformat(article["edition_date"]).year
    title = html.escape(article["title"])
    publication_label = (
        "Published with warnings"
        if edition.decision.outcome == PublicationOutcome.PUBLISHABLE_WITH_WARNINGS
        else "Strict evaluation passed"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="NineAM daily AI and technology briefing.">
  <title>NineAM — {title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:ital,opsz,wght@1,6..96,400;1,6..96,500&family=DM+Sans:wght@300;400;500;600&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="page">
    <header class="masthead" aria-label="NineAM masthead">
      <div class="brand" aria-label="NineAM">n<span class="brand-i">i<span aria-hidden="true">✦</span></span>ne<span class="brand-am">AM</span></div>
      <div class="clock" aria-label="Clock showing nine o'clock"><i></i><b></b><em></em></div>
    </header>

    <section class="meta" aria-label="Edition metadata">
      <span>{edition_date}</span><span>Daily 9 AM IST edition</span><span>By NineAM Research Desk</span><span>{_reading_time(article['body'])} min read</span><span>{len(edition.sources)} sources used</span>
    </section>

    <section class="hero">
      <p class="eyebrow">Daily AI &amp; technology briefing</p>
      <h1>{title}</h1>
      <p class="deck">A source-grounded daily AI and technology briefing.</p>
    </section>

    <section class="article-layout">
      <article class="article" aria-label="Daily article">{article_body}</article>
      <aside class="rail" aria-label="Edition context">
        <section class="rail-section"><h2>Key threads</h2><ul class="theme-list">{_render_threads(edition.cluster_headlines)}</ul></section>
        <section class="rail-section"><h2>Edition data</h2>
          <div class="rail-stat"><span>Sources used</span><strong>{len(edition.sources)}</strong></div>
          <div class="rail-stat"><span>Articles processed</span><strong>{edition.edition_item_count}</strong></div>
          <div class="rail-stat"><span>Selected clusters</span><strong>{len(edition.cluster_headlines)}</strong></div>
          <div class="rail-stat"><span>Claims evaluated</span><strong>{edition.decision.factual_claim_count}</strong></div>
          <div class="rail-stat"><span>Publication</span><strong>{html.escape(publication_label)}</strong></div>
        </section>
        <section class="rail-section"><h2>Selected sources</h2><ol class="source-list">{_render_sources(edition.sources)}</ol></section>
      </aside>
    </section>

    {_render_evaluation(edition)}
    <footer><span>© {edition_year} NineAM. A daily, source-grounded briefing.</span><span class="footer-mark">nineAM</span></footer>
  </main>
</body>
</html>"""


def build_site(edition_date: date, output_directory: Path) -> PublicationDecision:
    edition = load_site_edition(edition_date)
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "index.html").write_text(
        render_site(edition),
        encoding="utf-8",
    )
    (output_directory / "styles.css").write_text(
        STYLES_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return edition.decision


def main() -> int:
    arguments = parse_arguments()
    try:
        decision = build_site(arguments.edition_date, arguments.output)
    except (OSError, ValueError) as error:
        print(f"SITE_BUILD_ERROR={error}")
        return 2

    print(f"SITE_BUILD_OUTCOME={decision.outcome.value}")
    print(f"SITE_BUILD_OUTPUT={arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
