import argparse
import json
import re
import sys
from datetime import date
import time

from app.database.db import connect_database, row_to_dict, setup_database
from app.services.evaluation import (
    build_sentence_records, extract_citation_ids,
    validate_citation_ids, validate_citation_map,
)

from app.services.llm import (
    JUDGE_MODEL, JUDGE_PROMPT_VERSION,
    extract_atomic_claims, judge_claim_batch,
)

TARGET_MIN_WORDS = 800
TARGET_MAX_WORDS = 1200
DETERMINISTIC_EVAL_VERSION = "deterministic-v1"
EVALUATION_BATCH_SIZE = 10
EVALUATION_CALLS_PER_GROUP = 3
EVALUATION_REQUEST_INTERVAL_SECONDS = 20
EVALUATION_COOLDOWN_SECONDS = 60


class EvaluationCallPacer:
    """Spaces evaluation calls and pauses after each completed group."""

    def __init__(
            self,
            *,
            calls_per_group: int = EVALUATION_CALLS_PER_GROUP,
            request_interval_seconds: int = EVALUATION_REQUEST_INTERVAL_SECONDS,
            cooldown_seconds: int = EVALUATION_COOLDOWN_SECONDS,
            sleep_fn=time.sleep,
    ):
        self.calls_per_group = calls_per_group
        self.request_interval_seconds = request_interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self.sleep_fn = sleep_fn
        self.call_count = 0

    def before_call(self) -> None:
        if self.call_count and self.call_count % self.calls_per_group == 0:
            print(f"EVALUATION_COOLDOWN_SECONDS={self.cooldown_seconds}")
            self.sleep_fn(self.cooldown_seconds)
        elif self.call_count:
            print(
                "EVALUATION_REQUEST_INTERVAL_SECONDS="
                f"{self.request_interval_seconds}"
            )
            self.sleep_fn(self.request_interval_seconds)

        self.call_count += 1
        print(f"EVALUATION_API_CALL={self.call_count}")


def parse_edition_date() -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--edition-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Edition date in YYYY-MM-DD format.",
    )
    return parser.parse_args().edition_date.isoformat()


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+(?:[-']\w+)*\b", text))


def load_generated_article(edition_date: str) -> dict:
    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            edition_date,
            title,
            body,
            sources_json,
            cluster_ids_json,
            citation_map_json
        FROM generated_articles
        WHERE edition_date = ?
    """, (edition_date,))

    row = cursor.fetchone()
    article = row_to_dict(cursor, row)
    conn.close()

    if article is None:
        raise ValueError(f"No generated article found for {edition_date}.")

    return article


def parse_json(value: str, field_name: str, errors: list[str]):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        errors.append(f"{field_name}: invalid JSON ({error})")
        return None


def run_deterministic_checks(article: dict) -> dict:
    parsing_errors = []

    sources = parse_json(
        article["sources_json"],
        "sources_json",
        parsing_errors,
    )
    cluster_ids = parse_json(
        article["cluster_ids_json"],
        "cluster_ids_json",
        parsing_errors,
    )
    citation_map = parse_json(
        article["citation_map_json"],
        "citation_map_json",
        parsing_errors,
    )

    title = article["title"]
    body = article["body"]
    citations = extract_citation_ids(body)

    map_errors = []
    invalid_citation_ids = []

    if isinstance(citation_map, dict):
        map_errors = validate_citation_map(citation_map)
        invalid_citation_ids = validate_citation_ids(citations, citation_map)
    else:
        map_errors = ["citation_map_json must contain an object"]

    total_citations = len(citations)
    # This correctly handles repeated invalid citations.
    valid_citations = (
        sum(citation_id in citation_map for citation_id in citations)
        if isinstance(citation_map, dict)
        else 0
    )

    citation_validity_score = (
        valid_citations / total_citations
        if total_citations
        else 0.0
    )

    checks = {
        "title_non_empty": bool(title.strip()),
        "body_non_empty": bool(body.strip()),
        "body_word_count": word_count(body),
        "body_within_target_length": (TARGET_MIN_WORDS <= word_count(body) <= TARGET_MAX_WORDS),
        "sources_json_non_empty": isinstance(sources, list) and bool(sources),
        "cluster_ids_json_non_empty": isinstance(cluster_ids, list) and bool(cluster_ids),
        "citation_ids_present": bool(citations),
        "citation_map_errors": map_errors,
        "invalid_citation_ids": invalid_citation_ids,
        "json_parsing_errors": parsing_errors,
    }

    hard_failure = (
            not checks["title_non_empty"]
            or not checks["body_non_empty"]
            or not checks["body_within_target_length"]
            or not checks["sources_json_non_empty"]
            or not checks["cluster_ids_json_non_empty"]
            or not checks["citation_ids_present"]
            or bool(map_errors)
            or bool(invalid_citation_ids)
            or bool(parsing_errors)
    )

    # If the evidence trail is good, we say "needs review." If so, next we have to check if
    # the cited evidence actually supports each factual claim

    return {
        "overall_status": "failed" if hard_failure else "needs_review",
        "citation_validity_score": citation_validity_score,
        "checks": checks
    }


def save_eval_run(article_id: int, result: dict) -> int | None:
    conn = connect_database()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO eval_runs (
            generated_article_id,
            overall_status,
            citation_validity_score,
            checks_json,
            judge_model,
            judge_prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        article_id,
        result["overall_status"],
        result["citation_validity_score"],
        json.dumps(result["checks"]),
        "not-run",
        DETERMINISTIC_EVAL_VERSION,
    ))

    eval_run_id = cursor.lastrowid

    cursor.execute("""
        UPDATE generated_articles
        SET eval_status = ?
        WHERE id = ?
    """, (
        result["overall_status"],
        article_id,
    ))

    conn.commit()
    conn.close()

    return eval_run_id


# Just a function used to split a list of sentence records into batches.
# Just to save tokens and money while calling Gemini again in extract_atomic_claims.
def split_into_batches(
        records: list[dict],
        batch_size: int = EVALUATION_BATCH_SIZE,
) -> list[list[dict]]:
    return [
        records[start:start + batch_size]
        for start in range(0, len(records), batch_size)
    ]


def extract_claims_from_article(
        body: str,
        pacer: EvaluationCallPacer | None = None,
) -> list[dict]:
    """
    Extracts atomic claims and deterministically attaches each claim to the
    citation IDs from its original article sentence.
    """
    sentence_records = build_sentence_records(body)
    records_by_index = {
        record["sentence_index"]: record
        for record in sentence_records
    }

    claims = []
    pacer = pacer or EvaluationCallPacer()

    for batch in split_into_batches(sentence_records):
        pacer.before_call()
        extracted_claims = extract_atomic_claims(batch)
        batch_indices = {
            record["sentence_index"]
            for record in batch
        }

        for extracted_claim in extracted_claims:
            sentence_index = extracted_claim["source_sentence_index"]

            if sentence_index not in batch_indices:
                raise ValueError(
                    "Claim extractor returned a sentence index outside its batch."
                )

            claim_text = extracted_claim["claim_text"].strip()
            if not claim_text:
                raise ValueError("Claim extractor returned an empty claim.")

            source_record = records_by_index[sentence_index]

            claims.append({
                "source_sentence_index": sentence_index,
                "claim_text": claim_text,
                "is_factual": extracted_claim["is_factual"],
                "citation_ids": source_record["citation_ids"],
                "claim_index": len(claims) + 1,
            })

    return claims


def judge_factual_claims(
        claims,
        citation_map,
        pacer: EvaluationCallPacer | None = None,
):
    claim_results = []
    cited_claims = []
    pacer = pacer or EvaluationCallPacer()

    for claim in claims:
        if not claim["is_factual"]:
            continue

        if not claim["citation_ids"]:
            claim_results.append({
                "claim_index": claim["claim_index"],
                "claim_text": claim["claim_text"],
                "citation_ids": [],
                "citation_valid": False,
                "verdict": "unsupported",
                "confidence": 1.0,
                "severity": "major",
                "rationale": (
                    "Factual claim has no citation and was not sent to "
                    "the faithfulness judge."
                ),
            })
            continue

        cited_claims.append(claim)

    verdicts_by_index = {}

    for batch in split_into_batches(cited_claims):
        pacer.before_call()
        verdicts = judge_claim_batch(batch, citation_map)

        expected_indexes = {
            claim["claim_index"]
            for claim in batch
        }
        returned_indexes = {
            verdict["claim_index"]
            for verdict in verdicts
        }

        if len(verdicts) != len(batch) or returned_indexes != expected_indexes:
            raise ValueError(
                "Claim judge did not return exactly one verdict per claim."
            )

        for verdict in verdicts:
            verdicts_by_index[verdict["claim_index"]] = verdict

    for claim in cited_claims:
        verdict = verdicts_by_index[claim["claim_index"]]

        claim_results.append({
            "claim_index": claim["claim_index"],
            "claim_text": claim["claim_text"],
            "citation_ids": claim["citation_ids"],
            "citation_valid": True,
            "verdict": verdict["verdict"],
            "confidence": verdict["confidence"],
            "severity": verdict["severity"],
            "rationale": verdict["rationale"],
        })

    return sorted(
        claim_results,
        key=lambda claim_result: claim_result["claim_index"],
    )


def apply_claim_results(result, claim_results):
    factual_claim_count = len(claim_results)
    cited_claim_count = sum(
        bool(claim_result["citation_ids"])
        for claim_result in claim_results
    )
    supported_claim_count = sum(
        claim_result["verdict"] == "supported"
        for claim_result in claim_results
    )
    contradicted_claim_count = sum(
        claim_result["verdict"] == "contradicted"
        for claim_result in claim_results
    )

    verdict_counts = {
        verdict: sum(
            claim_result["verdict"] == verdict
            for claim_result in claim_results
        )
        for verdict in (
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
        )
    }

    uncited_claims = [
        {
            "claim_index": claim_result["claim_index"],
            "claim_text": claim_result["claim_text"],
        }
        for claim_result in claim_results
        if not claim_result["citation_ids"]
    ]

    result["faithfulness_score"] = (
        supported_claim_count / factual_claim_count
        if factual_claim_count
        else 0.0
    )
    result["citation_completeness_score"] = (
        cited_claim_count / factual_claim_count
        if factual_claim_count
        else 0.0
    )
    result["contradiction_score"] = (
        1 - (contradicted_claim_count / factual_claim_count)
        if factual_claim_count
        else 0.0
    )

    result["checks"]["factual_claim_count"] = factual_claim_count
    result["checks"]["uncited_factual_claims"] = uncited_claims
    result["checks"]["claim_verdict_counts"] = verdict_counts

    major_grounding_failure = any(
        claim_result["verdict"] in {"unsupported", "contradicted"}
        and claim_result["severity"] == "major"
        for claim_result in claim_results
    )

    any_non_supported_claim = any(
        claim_result["verdict"] != "supported"
        for claim_result in claim_results
    )

    if result["overall_status"] == "failed" or major_grounding_failure:
        result["overall_status"] = "failed"
    elif any_non_supported_claim:
        result["overall_status"] = "needs_review"
    else:
        result["overall_status"] = "passed"

    return result


def finalize_eval_run(eval_run_id, article_id, result, claim_results):
    conn = connect_database()
    cursor = conn.cursor()

    for claim_result in claim_results:
        cursor.execute("""
            INSERT INTO claim_evaluations (
                eval_run_id,
                claim_index,
                claim_text,
                citation_ids_json,
                citation_valid,
                verdict,
                confidence,
                severity,
                rationale
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            eval_run_id,
            claim_result["claim_index"],
            claim_result["claim_text"],
            json.dumps(claim_result["citation_ids"]),
            int(claim_result["citation_valid"]),
            claim_result["verdict"],
            claim_result["confidence"],
            claim_result["severity"],
            claim_result["rationale"],
        ))

    cursor.execute("""
        UPDATE eval_runs
        SET
            overall_status = ?,
            faithfulness_score = ?,
            citation_completeness_score = ?,
            contradiction_score = ?,
            checks_json = ?,
            judge_model = ?,
            judge_prompt_version = ?
        WHERE id = ?
    """, (
        result["overall_status"],
        result["faithfulness_score"],
        result["citation_completeness_score"],
        result["contradiction_score"],
        json.dumps(result["checks"]),
        JUDGE_MODEL,
        JUDGE_PROMPT_VERSION,
        eval_run_id,
    ))

    cursor.execute("""
        UPDATE generated_articles
        SET eval_status = ?
        WHERE id = ?
    """, (
        result["overall_status"],
        article_id,
    ))

    conn.commit()
    conn.close()


def evaluate_edition(edition_date: str) -> dict | None:
    """Evaluates one saved edition and persists its evaluation trail."""
    setup_database()

    try:
        article = load_generated_article(edition_date)
    except ValueError:
        return None

    result = run_deterministic_checks(article)
    eval_run_id = save_eval_run(article["id"], result)

    if result["overall_status"] == "failed":
        return result

    pacer = EvaluationCallPacer()

    try:
        claims = extract_claims_from_article(article["body"], pacer)
    except RuntimeError as error:
        raise RuntimeError(f"Claim extraction failed: {error}") from error

    try:
        citation_map = json.loads(article["citation_map_json"])
        claim_results = judge_factual_claims(claims, citation_map, pacer)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f"Claim judging failed: {error}") from error

    result = apply_claim_results(result, claim_results)

    finalize_eval_run(
        eval_run_id,
        article["id"],
        result,
        claim_results,
    )

    result["claim_results"] = claim_results
    return result


def main() -> int:
    edition_date = parse_edition_date()

    try:
        result = evaluate_edition(edition_date)
    except RuntimeError as error:
        print(error)
        return 1

    if result is None:
        print(f"No generated article found for {edition_date}.")
        return 2

    print(f"Status: {result['overall_status']}")
    print(
        "Citation validity: "
        f"{result['citation_validity_score']:.2f}"
    )
    print(
        "Invalid citation IDs: "
        f"{result['checks']['invalid_citation_ids']}"
    )
    print(
        "Citation-map errors: "
        f"{result['checks']['citation_map_errors']}"
    )

    if "faithfulness_score" not in result:
        return 0

    print(f"\nFinal status: {result['overall_status']}")
    print(f"Faithfulness score: {result['faithfulness_score']:.2f}")
    print(
        "Citation completeness: "
        f"{result['citation_completeness_score']:.2f}"
    )
    print(f"Contradiction score: {result['contradiction_score']:.2f}")

    print("\nClaims needing attention:\n")

    for claim_result in result.get("claim_results", []):
        if claim_result["verdict"] != "supported":
            print(
                f"{claim_result['claim_index']}. "
                f"{claim_result['verdict']} "
                f"({claim_result['severity']})"
            )
            print(f"   {claim_result['claim_text']}")
            print(f"   Reason: {claim_result['rationale']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
