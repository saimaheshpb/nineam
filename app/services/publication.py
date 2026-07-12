"""Pure publication-policy helpers for a generated NineAM edition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.services.evaluation import (
    extract_citation_ids,
    validate_citation_ids,
    validate_citation_map,
)


class PublicationOutcome(str, Enum):
    CLEAN = "clean"
    PUBLISHABLE_WITH_WARNINGS = "publishable_with_warnings"
    BLOCKED = "blocked"


COMPLETED_EVAL_STATUSES = {"passed", "failed", "needs_review"}


@dataclass(frozen=True)
class PublicationDecision:
    outcome: PublicationOutcome
    reasons: tuple[str, ...]
    factual_claim_count: int | None = None
    supported_claim_count: int | None = None
    contradicted_claim_count: int | None = None
    support_rate: float | None = None
    contradiction_rate: float | None = None
    citation_validity_score: float | None = None
    citation_completeness_score: float | None = None


def _parse_json(value: Any, field_name: str, errors: list[str]) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError) as error:
        errors.append(f"{field_name}: invalid JSON ({error})")
        return None


def _article_errors(article: dict[str, Any] | None) -> list[str]:
    if not article:
        return ["No generated article exists for this edition."]

    errors = []
    if article.get("eval_status") not in COMPLETED_EVAL_STATUSES:
        errors.append(
            "The current generated article has not completed evaluation."
        )
    if not str(article.get("title", "")).strip():
        errors.append("Article title is empty.")
    if not str(article.get("body", "")).strip():
        errors.append("Article body is empty.")

    sources = _parse_json(article.get("sources_json"), "sources_json", errors)
    if not isinstance(sources, list) or not sources:
        errors.append("Article source snapshot is missing or empty.")
    else:
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict) or any(
                    not str(source.get(field, "")).strip()
                    for field in ("source_name", "headline", "url")
            ):
                errors.append(f"Source snapshot entry {index} is malformed.")

    citation_map = _parse_json(
        article.get("citation_map_json"),
        "citation_map_json",
        errors,
    )
    citation_ids = extract_citation_ids(str(article.get("body", "")))

    if not citation_ids:
        errors.append("Article body has no inline citations.")
    if not isinstance(citation_map, dict):
        errors.append("Citation map is missing or malformed.")
    else:
        errors.extend(validate_citation_map(citation_map))
        invalid_ids = validate_citation_ids(citation_ids, citation_map)
        if invalid_ids:
            errors.append(
                "Article uses citation IDs missing from its evidence map: "
                + ", ".join(invalid_ids)
            )

    return errors


def _evaluation_errors(
        evaluation: dict[str, Any] | None,
        claim_evaluations: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any] | None]:
    if not evaluation:
        return ["No completed evaluation exists for this edition."], None

    errors = []
    checks = _parse_json(evaluation.get("checks_json"), "checks_json", errors)
    if not isinstance(checks, dict):
        return errors + ["Evaluation checks are missing or malformed."], None

    factual_claim_count = checks.get("factual_claim_count")
    if not isinstance(factual_claim_count, int) or factual_claim_count <= 0:
        errors.append("Evaluation does not record a positive factual claim count.")
    elif len(claim_evaluations) != factual_claim_count:
        errors.append(
            "Evaluation is incomplete: persisted claim verdicts do not match "
            "the recorded factual claim count."
        )

    required_scores = (
        "faithfulness_score",
        "citation_validity_score",
        "citation_completeness_score",
        "contradiction_score",
    )
    for score_name in required_scores:
        if not isinstance(evaluation.get(score_name), (int, float)):
            errors.append(f"Evaluation is missing {score_name}.")

    return errors, checks


def decide_publication(
        article: dict[str, Any] | None,
        evaluation: dict[str, Any] | None,
        claim_evaluations: list[dict[str, Any]],
) -> PublicationDecision:
    """Classifies one edition without reading from the database.

    A warning edition is still fully evaluated and structurally sound; it is
    merely short of the strict all-supported standard required for ``clean``.
    """
    errors = _article_errors(article)
    evaluation_errors, checks = _evaluation_errors(evaluation, claim_evaluations)
    errors.extend(evaluation_errors)
    if errors:
        return PublicationDecision(
            outcome=PublicationOutcome.BLOCKED,
            reasons=tuple(errors),
        )

    assert evaluation is not None
    assert checks is not None
    factual_claim_count = checks["factual_claim_count"]
    supported_claim_count = sum(
        claim.get("verdict") == "supported"
        for claim in claim_evaluations
    )
    contradicted_claim_count = sum(
        claim.get("verdict") == "contradicted"
        for claim in claim_evaluations
    )
    support_rate = supported_claim_count / factual_claim_count
    contradiction_rate = contradicted_claim_count / factual_claim_count
    citation_validity_score = float(evaluation["citation_validity_score"])
    citation_completeness_score = float(evaluation["citation_completeness_score"])

    metrics = {
        "factual_claim_count": factual_claim_count,
        "supported_claim_count": supported_claim_count,
        "contradicted_claim_count": contradicted_claim_count,
        "support_rate": support_rate,
        "contradiction_rate": contradiction_rate,
        "citation_validity_score": citation_validity_score,
        "citation_completeness_score": citation_completeness_score,
    }

    if citation_validity_score < 1.0:
        return PublicationDecision(
            outcome=PublicationOutcome.BLOCKED,
            reasons=("Evaluation found invalid citations.",),
            **metrics,
        )
    if support_rate < 0.5:
        return PublicationDecision(
            outcome=PublicationOutcome.BLOCKED,
            reasons=("Fewer than 50% of factual claims are supported.",),
            **metrics,
        )
    if contradiction_rate >= 0.2:
        return PublicationDecision(
            outcome=PublicationOutcome.BLOCKED,
            reasons=("At least 20% of factual claims are contradicted.",),
            **metrics,
        )
    if supported_claim_count == factual_claim_count:
        return PublicationDecision(
            outcome=PublicationOutcome.CLEAN,
            reasons=("Every factual claim is supported.",),
            **metrics,
        )

    return PublicationDecision(
        outcome=PublicationOutcome.PUBLISHABLE_WITH_WARNINGS,
        reasons=(
            "The edition passed structural checks and the publication "
            "thresholds, but not every factual claim is supported.",
        ),
        **metrics,
    )
