"""Run one NineAM edition without silently replacing completed work."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date

from app.database.db import connect_database, row_to_dict, setup_database
from app.services.publication import (
    PublicationDecision,
    PublicationOutcome,
    decide_publication,
)


@dataclass(frozen=True)
class DailyRunResult:
    decision: PublicationDecision
    no_op: bool


def parse_edition_date() -> date:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Edition date in YYYY-MM-DD format.",
    )
    return parser.parse_args().edition_date


def load_edition_context(
        edition_date: str,
) -> tuple[dict | None, dict | None, list[dict]]:
    """Loads the immutable inputs needed to classify an edition."""
    conn = connect_database()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT *
            FROM generated_articles
            WHERE edition_date = ?
            """,
            (edition_date,),
        )
        article = row_to_dict(cursor, cursor.fetchone())
        if article is None:
            return None, None, []

        cursor.execute(
            """
            SELECT *
            FROM eval_runs
            WHERE generated_article_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (article["id"],),
        )
        evaluation = row_to_dict(cursor, cursor.fetchone())
        if evaluation is None:
            return article, None, []

        cursor.execute(
            """
            SELECT *
            FROM claim_evaluations
            WHERE eval_run_id = ?
            ORDER BY claim_index
            """,
            (evaluation["id"],),
        )
        claim_evaluations = [
            row_to_dict(cursor, row)
            for row in cursor.fetchall()
        ]
        return article, evaluation, claim_evaluations
    finally:
        conn.close()


def _no_article_decision() -> PublicationDecision:
    return PublicationDecision(
        outcome=PublicationOutcome.BLOCKED,
        reasons=("No generated article exists for this edition.",),
    )


def run_daily(
        edition_date: date,
        *,
        setup_stage=setup_database,
        clustering_stage=None,
        generation_stage=None,
        evaluation_stage=None,
        context_loader=load_edition_context,
) -> DailyRunResult:
    """Runs post-collection stages while preserving completed editions as-is."""
    edition_date_string = edition_date.isoformat()

    if clustering_stage is None:
        from cluster_articles import run_clustering
        clustering_stage = run_clustering
    if generation_stage is None:
        from generate_article import generate_edition
        generation_stage = generate_edition
    if evaluation_stage is None:
        from evaluate_article import evaluate_edition
        evaluation_stage = evaluate_edition

    setup_stage()

    article, _, _ = context_loader(edition_date_string)
    if article is not None:
        if article["eval_status"] == "pending":
            evaluation_stage(edition_date_string)
            article, evaluation, claims = context_loader(edition_date_string)
            return DailyRunResult(
                decision=decide_publication(article, evaluation, claims),
                no_op=False,
            )

        article, evaluation, claims = context_loader(edition_date_string)
        return DailyRunResult(
            decision=decide_publication(article, evaluation, claims),
            no_op=True,
        )

    clustering_stage(edition_date)
    generated_article = generation_stage(edition_date_string)
    if generated_article is None:
        return DailyRunResult(
            decision=_no_article_decision(),
            no_op=False,
        )

    evaluation_stage(edition_date_string)
    article, evaluation, claims = context_loader(edition_date_string)
    return DailyRunResult(
        decision=decide_publication(article, evaluation, claims),
        no_op=False,
    )


def _exit_code(result: DailyRunResult) -> int:
    if result.decision.outcome in {
            PublicationOutcome.CLEAN,
            PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
    }:
        return 0
    return 2


def main() -> int:
    edition_date = parse_edition_date()

    try:
        result = run_daily(edition_date)
    except Exception as error:
        print(f"INFRASTRUCTURE_ERROR={error}")
        return 1

    decision = result.decision
    print(f"EDITION_DATE={edition_date.isoformat()}")
    print(f"PUBLICATION_OUTCOME={decision.outcome.value}")
    print(f"NO_OP={str(result.no_op).lower()}")
    for reason in decision.reasons:
        print(f"PUBLICATION_REASON={reason}")

    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
