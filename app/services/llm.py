import json
import os
import re
from copy import deepcopy
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from typing import Literal

load_dotenv()

EVIDENCE_EXTRACTION_MODEL = os.getenv(
    "EVIDENCE_EXTRACTION_MODEL", "openai/gpt-5.6-luna"
)
GENERATOR_MODEL = os.getenv(
    "ARTICLE_GENERATION_MODEL", "alibaba/qwen3.8-max-0902"
)
GENERATION_PROMPT_VERSION = "citation-aware-v2"

CLAIM_EXTRACTOR_MODEL = os.getenv(
    "CLAIM_EXTRACTION_MODEL", "openai/gpt-5.6-luna"
)
CLAIM_EXTRACTION_PROMPT_VERSION = "claim-extraction-v1"

JUDGE_MODEL = os.getenv(
    "CLAIM_JUDGE_MODEL", "deepseek/deepseek-v4.1-flash"
)
JUDGE_PROMPT_VERSION = "claim-faithfulness-v1"

def _gateway_client() -> OpenAI:
    api_key = os.getenv("AI_GATEWAY_API_KEY")
    if not api_key:
        raise RuntimeError("AI_GATEWAY_API_KEY is missing")
    return _client_for_key(api_key)


@lru_cache(maxsize=1)
def _client_for_key(api_key: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url="https://ai-gateway.vercel.sh/v1",
        max_retries=0,
    )


class EvidenceFact(BaseModel):
    claim: str
    supporting_excerpt: str


class ArticleData(BaseModel):
    headline: str
    summary: str
    entities: list[str]
    category: str
    importance_score: int
    key_facts: list[EvidenceFact]


class GeneratedArticle(BaseModel):
    title: str
    body: str


class ExtractedClaim(BaseModel):
    source_sentence_index: int
    claim_text: str
    is_factual: bool


class ClaimExtractionResult(BaseModel):
    claims: list[ExtractedClaim]


class ClaimVerdict(BaseModel):
    claim_index: int
    verdict: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "contradicted",
    ]
    confidence: float
    severity: Literal["major", "minor", "none"]
    rationale: str


class ClaimJudgeResult(BaseModel):
    verdicts: list[ClaimVerdict]


SCHEMA_NAMES = {
    ArticleData: "article_data",
    GeneratedArticle: "generated_article",
    ClaimExtractionResult: "claim_extraction_result",
    ClaimJudgeResult: "claim_judge_result",
}


def _strict_json_schema(schema_type: type[BaseModel]) -> dict:
    """Inline Pydantic references for Gateway's strict JSON Schema format."""
    schema = schema_type.model_json_schema()
    definitions = schema.pop("$defs", {})

    def clean(value):
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            name = value["$ref"].removeprefix("#/$defs/")
            return clean(deepcopy(definitions[name]))
        result = {}
        for key, item in value.items():
            if key == "title":
                continue  # Schema annotation, not an output field.
            if key == "properties":
                result[key] = {
                    field_name: clean(field_schema)
                    for field_name, field_schema in item.items()
                }
            else:
                result[key] = clean(item)
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result

    return clean(schema)


def _request_structured(
    role: str,
    model: str,
    schema_type: type[BaseModel],
    prompt: str,
    content: str,
    *,
    reasoning_effort: str | None = None,
) -> dict:
    """Request and validate one schema-shaped response without model fallback."""
    try:
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAMES[schema_type],
                    "strict": True,
                    "schema": _strict_json_schema(schema_type),
                },
            },
        }
        if reasoning_effort is not None:
            request["extra_body"] = {"reasoning": {"effort": reasoning_effort}}
        response = _gateway_client().chat.completions.create(**request)
        if not response.choices:
            raise ValueError("Gateway returned no choices")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError("Gateway stopped at its output limit")
        if not choice.message.content:
            raise ValueError("Gateway returned empty structured content")
        parsed = schema_type.model_validate_json(choice.message.content)
        payload = response.model_dump()
        gateway = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("provider_metadata", {})
            .get("gateway", {})
        )
        usage = payload.get("usage") or {}
        print(json.dumps({
            "event": "gateway_response",
            "role": role,
            "model": model,
            "response_model": response.model,
            "provider": gateway.get("routing", {}).get("finalProvider"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "cost": usage.get("cost"),
            "request_id": payload.get("generationId") or payload.get("id"),
        }))
        return parsed.model_dump()
    except Exception as error:
        status = getattr(error, "status_code", None)
        code = getattr(error, "code", None)
        if isinstance(error, ValidationError):
            message = ", ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['type']}"
                for item in error.errors(include_input=False)
            )
        else:
            message = str(error)
        api_key = os.getenv("AI_GATEWAY_API_KEY")
        if api_key:
            message = message.replace(api_key, "[REDACTED]")
        message = re.sub(r"(?:vck_|sk-)[A-Za-z0-9_-]{16,}", "[REDACTED]", message)
        response_payload = (
            response.model_dump()
            if "response" in locals() and hasattr(response, "model_dump")
            else {}
        )
        print(json.dumps({
            "event": "gateway_error",
            "role": role,
            "model": model,
            "status": status,
            "code": code,
            "error_type": type(error).__name__,
            "message": message[:300],
            "cost": (response_payload.get("usage") or {}).get("cost"),
            "request_id": response_payload.get("generationId") or response_payload.get("id"),
        }))
        raise RuntimeError(
            f"{role} failed with {model}: {type(error).__name__}"
            f" (status={status}, code={code})"
        ) from error


def extract_structured_data(raw_text: str) -> dict:
    """Extract source-backed facts for clustering and citation snapshots."""
    prompt = """
        Analyze this news article and return structured metadata.

        For key_facts, extract 3 to 6 specific factual claims from the article.
        For every claim, include a short supporting excerpt from the article.

        Rules:
        - Use only information present in the article.
        - Do not infer, speculate, or add outside knowledge.
        - Keep claims concrete and verifiable.
        - The supporting excerpt must directly support its claim.
        - Set importance_score from 1 to 10, where 10 means a major
          development with broad significance.
        """
    return _request_structured(
        "evidence_extraction", EVIDENCE_EXTRACTION_MODEL,
        ArticleData, prompt, raw_text,
    )


def generate_daily_article(article_brief: str) -> dict:
    """Write one daily NineAM article from source-backed evidence."""
    prompt = """
        Write one clear daily AI/technology news article using only the
        evidence provided.

        Requirements:
        - Return a title and body.
        - Write at least 400 words. There is no maximum word count.
        - Build a coherent narrative rather than listing source summaries.
        - Use only claims supported by the supplied evidence.
        - Every sentence in the body that makes a factual claim must end with
          one or more citations in exactly this format:
          [S4-F1] or [S4-F1][S4-F2].
        - Use only citation IDs supplied in the evidence brief.
        - A citation supports only the sentence immediately before it.
        - Do not add outside facts, speculation, causal claims, or invented quotes.
        - If stories are unrelated, present them as a tightly edited daily briefing.
        - Do not include URLs in the body.
        """
    result = _request_structured(
        "article_generation", GENERATOR_MODEL,
        GeneratedArticle, prompt, article_brief,
        reasoning_effort="low",
    )
    if not result["title"].strip() or not result["body"].strip():
        raise RuntimeError("Article generation returned an empty title or body")
    return result


def extract_atomic_claims(sentence_batch: list[dict]) -> list[dict]:
    """
    Extracts independently checkable claims from up to ten article sentences.
    """
    if not sentence_batch:
        return []

    if len(sentence_batch) > 10:
        raise ValueError("Claim extraction batches may contain at most ten sentences.")

    prompt = """
    Extract atomic, independently checkable claims from the supplied article
    sentences.

    Rules:
    - Split compound factual statements into separate factual claims.
    - Preserve the meaning of each claim; do not add outside information.
    - Set is_factual to true for claims that can be checked against evidence.
    - Ignore purely stylistic or rhetorical text.
    - source_sentence_index must match the input sentence that produced the claim.
    - Do not include inline citation labels in claim_text.
    """

    return _request_structured(
        "claim_extraction", CLAIM_EXTRACTOR_MODEL,
        ClaimExtractionResult, prompt, json.dumps(sentence_batch),
    )["claims"]


def judge_claim_batch(claims, citation_map):
    """
    Judges up to ten factual claims only against their cited evidence.
    """
    if not claims:
        return []

    if len(claims) > 10:
        raise ValueError("Claim judge batches may contain at most ten claims.")

    judge_input = []

    for claim in claims:
        cited_evidence = []

        for citation_id in claim["citation_ids"]:
            evidence = citation_map[citation_id]

            cited_evidence.append({
                "citation_id": citation_id,
                "source_name": evidence["source_name"],
                "url": evidence["url"],
                "evidence_claim": evidence["claim"],
                "supporting_excerpt": evidence["supporting_excerpt"],
            })

        judge_input.append({
            "claim_index": claim["claim_index"],
            "claim_text": claim["claim_text"],
            "cited_evidence": cited_evidence,
        })

    prompt = """
    Judge whether each generated claim is supported by its cited evidence.

    Rules:
    - Use only the cited evidence supplied for that specific claim.
    - Do not use outside knowledge.
    - supported: evidence directly states or clearly entails the claim.
    - partially_supported: core claim is supported, but a qualifier, scope,
      cause, time frame, or degree is not.
    - unsupported: evidence does not establish the claim.
    - contradicted: evidence conflicts with the claim.
    - major: an error changes the main actor, event, number, time, cause,
      or significance.
    - minor: an error is non-central wording or detail.
    - severity must be "none" for supported claims.
    - Return one verdict for every input claim_index.
    """

    return _request_structured(
        "claim_judging", JUDGE_MODEL,
        ClaimJudgeResult, prompt, json.dumps(judge_input),
    )["verdicts"]
