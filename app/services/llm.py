import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Literal

GENERATOR_MODEL = "gemini-2.5-flash"
GENERATION_PROMPT_VERSION = "citation-aware-v1"

CLAIM_EXTRACTOR_MODEL = "gemini-3.1-flash-lite"
CLAIM_EXTRACTION_PROMPT_VERSION = "claim-extraction-v1"

JUDGE_MODEL = "gemini-3.5-flash"
JUDGE_PROMPT_VERSION = "claim-faithfulness-v1"

load_dotenv()

# The SDK automatically finds your GEMINI_API_KEY in the .env file
client = genai.Client()


class EvidenceFact(BaseModel):
    claim: str
    supporting_excerpt: str


# We define the exact structure in Python.
# Gemini is physically forced to return data that matches this perfectly.
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


def extract_structured_data(raw_text: str) -> dict:
    """
    Forces Gemini to extract structured data using native Structured Outputs.
    """
    try:
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

        print("Sending to Gemini 3.5 Flash for Structured Extraction...")

        # Note: Google's API string for the Flash model is currently 'gemini-2.5-flash'
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, raw_text],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ArticleData,  # We pass our Pydantic class here!
                temperature=0.2,
            ),
        )

        # We can safely parse it because Google guarantees it is perfect JSON
        structured_data = json.loads(response.text)
        return structured_data

    except Exception as e:
        print(f"Oops. Gemini failed. Error: {e}")
        return {}


def generate_daily_article(article_brief: str) -> dict:
    """
    Writes one daily NineAM article from source-backed evidence.
    """
    try:
        prompt = """
        Write one clear daily AI/technology news article using only the
        evidence provided.

        Requirements:
        - Return a title and body.
        - Write between 800 and 1200 words.
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

        print("Sending selected evidence to Gemini for article generation...")

        response = client.models.generate_content(
            model=GENERATOR_MODEL,
            contents=[prompt, article_brief],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeneratedArticle,
                temperature=0.4,
            ),
        )

        return json.loads(response.text)

    except Exception as e:
        print(f"Article generation failed: {e}")
        return {}


def extract_atomic_claims(sentence_batch: list[dict]) -> list[dict]:
    """
    Extracts independently checkable claims from up to five article sentences.
    """
    if not sentence_batch:
        return []

    if len(sentence_batch) > 5:
        raise ValueError("Claim extraction batches may contain at most five sentences.")

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

    try:
        response = client.models.generate_content(
            model=CLAIM_EXTRACTOR_MODEL,
            contents=[prompt, json.dumps(sentence_batch)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClaimExtractionResult,
                temperature=0.0,
            ),
        )

        return json.loads(response.text)["claims"]


    except Exception as error:
        raise RuntimeError(f"Claim extraction failed: {error}") from error


def judge_claim_batch(claims, citation_map):
    """
    Judges up to five factual claims only against their cited evidence.
    """
    if not claims:
        return []

    if len(claims) > 5:
        raise ValueError("Claim judge batches may contain at most five claims.")

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

    try:
        response = client.models.generate_content(
            model=JUDGE_MODEL,
            contents=[prompt, json.dumps(judge_input)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClaimJudgeResult,
                temperature=0.0,
            ),
        )

        return json.loads(response.text)["verdicts"]

    except Exception as error:
        raise RuntimeError(f"Claim judging failed: {error}") from error
