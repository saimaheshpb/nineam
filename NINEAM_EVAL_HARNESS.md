# NineAM Eval Harness: Status and Remaining Work

This document is the detailed source of truth for NineAM evaluation. Read `README.md` first for overall project status; read this file when changing evaluation behavior.

Status as of 2026-07-12: the V1 core claim-level harness is implemented and has been exercised locally. The latest run validated all citation IDs, extracted 59 factual claims, judged them against their cited evidence, and correctly blocked the article because 11 claims were unsupported. The remaining work below is evaluation hardening, not the missing core.

## Why This Exists

NineAM must not present basic formatting checks as an LLM evaluation system.

Checks such as word count, non-empty body, source count, and duplicate paragraphs are useful smoke tests, but they do not understand the article. A real NineAM eval must evaluate whether generated claims are grounded in the evidence that was selected from the source articles.

The central question is:

> Is every factual claim in the generated article supported by the exact evidence it cites?

The system should also evaluate editorial quality and coverage, but claim-level grounding is the non-negotiable core.

## Product Promise

NineAM cannot prove that a news source is objectively true in the real world. It can make the defensible and valuable promise that:

1. The article uses only selected source evidence.
2. Every factual claim has a traceable evidence citation.
3. An evaluator checks whether each cited excerpt supports the claim.
4. Unsupported major claims, citation errors, and material contradictions block publication.
5. The complete evaluation trail is stored for inspection.

This is a source-grounded synthesis and evaluation system, not an omniscient fact checker.

## Current Project State

The following is already implemented and working locally:

```text
RSS sources
  -> scraping
  -> Gemini structured extraction
  -> per-source key facts with supporting excerpts
  -> local embeddings
  -> semantic similarity and clustering
  -> cluster ranking
  -> 9 AM IST daily edition window
  -> top-ranked cluster selection
  -> evidence brief
  -> Gemini article generation
  -> generated_articles persistence
```

Existing relevant tables:

### `items`

Stores each source article, including:

- `id`
- `url`
- `source_name`
- `headline`
- `summary`
- `full_text`
- `evidence_json`
- `embedding`
- `processed_at`

`evidence_json` is a JSON list like:

```json
[
  {
    "claim": "Gradium has raised a total of $100 million in its seed round.",
    "supporting_excerpt": "... has now raised $100 million total for the round ..."
  }
]
```

### `story_clusters` and `story_cluster_items`

Store ranked daily story groups and membership of source items.

### `generated_articles`

Currently stores:

- `edition_date`
- `title`
- `body`
- `sources_json`
- `cluster_ids_json`
- `citation_map_json`
- `generator_model`
- `generation_prompt_version`
- `eval_status` (`pending`, `passed`, `failed`, or `needs_review`)
- `created_at`

New generated articles are citation-aware. Older rows may lack the citation snapshot and must be regenerated before evaluation.

## V1 Core: Implemented

- Stable evidence identifiers and immutable citation-map snapshots.
- Inline citation instructions in article generation.
- Deterministic citation parsing, map validation, and invalid-ID checks.
- Atomic claim extraction in small Gemini batches.
- Per-claim judging against only the evidence cited by that claim.
- Persisted `eval_runs` and `claim_evaluations` records.
- Aggregate faithfulness, citation completeness, and contradiction scores.
- Hard blocking for malformed output, uncited claims, and major unsupported or contradicted claims.
- `generated_articles.eval_status` updates after evaluation.

The current implementation is deliberately source-grounded evaluation, not objective truth verification. It checks whether the article is supported by the evidence NineAM selected.

## Remaining Evaluation Work

- Add cross-source conflict detection for selected evidence.
- Add a separate editorial coverage and quality judge.
- Add golden fixtures and adversarial mutations.
- Calibrate the judge against manual labels and record false-pass/false-fail results.
- Improve error handling so an interrupted Gemini call records `error` instead of leaving an eval run at `needs_review`.
- Add integration tests that exercise persistence and the publish decision without spending Gemini quota.

## Desired Architecture

```text
Selected cluster evidence
  -> assign stable evidence IDs
  -> citation-aware writer produces article
  -> save article plus immutable citation/evidence snapshot
  -> extract atomic factual claims from article
  -> validate each claim's citation IDs
  -> judge each claim against cited excerpts
  -> run contradiction and editorial-quality judges
  -> aggregate scores and publishing decision
  -> persist run, verdicts, reasons, prompt versions, and model versions
  -> publish only when the hard gate passes
```

## Design Principle: The Evaluator Must See the Generation Trace

Do not ask one LLM to read an article and give a vague "quality score."

The evaluator must receive:

1. The generated claim.
2. The citation ID(s) attached to that claim.
3. The exact evidence excerpts represented by those IDs.
4. Optionally, source metadata and source URL for auditability.

The judge must not receive unrelated raw articles. Claim-level inputs should remain small and attributable.

## Phase 1: Stable Evidence IDs

### Purpose

The current evidence brief contains claims and excerpts but no durable labels. Add labels so the writer can cite individual evidence facts and the evaluator can resolve every citation deterministically.

### Citation ID Format

Use this format:

```text
S{item_id}-F{fact_number}
```

Examples:

```text
S4-F1
S4-F2
S1-F1
```

Rules:

- `item_id` is the existing database ID from `items`.
- `fact_number` is one-based and is assigned from the selected evidence list for that item.
- IDs must be deterministic within the selected source snapshot.
- Citation IDs are internal identifiers. The public site can render them as source links later.

### Required `generate_article.py` Changes

When loading each article, preserve `id`, source metadata, URL, and parsed `evidence_json`.

When building the article brief, enumerate each evidence fact and output it like:

```text
[S4-F1]
Claim: Google Search accepts multimodal inputs.
Supporting excerpt: "..."
Source: VentureBeat AI
URL: https://...
```

Build a citation map in parallel:

```python
{
    "S4-F1": {
        "item_id": 4,
        "fact_number": 1,
        "source_name": "VentureBeat AI",
        "headline": "...",
        "url": "https://...",
        "claim": "...",
        "supporting_excerpt": "..."
    }
}
```

The writer receives the labeled evidence brief. The save path receives the citation map.

## Phase 2: Citation-Aware Article Generation

### Why the Current Generated Article Contract Is Insufficient

The current `GeneratedArticle` schema contains only:

```python
class GeneratedArticle(BaseModel):
    title: str
    body: str
```

This is acceptable for basic generation but cannot prove which evidence supports a particular sentence.

Keep this simple schema initially, but require citations in `body` using the evidence IDs. A later refinement can introduce structured sections, but do not overbuild before claim evaluation works.

### Writer Prompt Requirements

The writer prompt must state all of these rules:

```text
- Use only the supplied evidence.
- Every sentence that makes a factual claim must end with one or more
  evidence citations in this exact format: [S4-F1] or [S4-F1][S4-F2].
- Do not cite an evidence ID that is absent from the supplied brief.
- Do not make factual assertions without citations.
- Do not add outside facts, speculation, causal claims, or invented quotes.
- Use citations only to support the sentence immediately before them.
- Keep the article readable; citations are part of the transparency system.
```

Example desired writer output:

```text
Google is reshaping Search from a keyword box into a multimodal AI interface that can accept text, images, and video [S4-F1].
```

### Generation Metadata to Persist

Add these fields to `generated_articles` through a safe SQLite migration helper:

- `citation_map_json TEXT`
- `generator_model TEXT`
- `generation_prompt_version TEXT`

For V1, nullable columns are acceptable because the existing generated row predates this feature. New citation-aware rows must populate all three fields.

`citation_map_json` is an immutable snapshot. Do not reconstruct it later from mutable `items.evidence_json`, because an item could be reprocessed or corrected after publication.

### Regeneration Behavior

The existing `ON CONFLICT(edition_date) DO UPDATE` generation path should update:

- `title`
- `body`
- `sources_json`
- `cluster_ids_json`
- `citation_map_json`
- `generator_model`
- `generation_prompt_version`
- `eval_status = 'pending'`

Do not run evals against an old article after regeneration. A new eval run must be created for the newly saved output.

## Phase 3: Eval Persistence Schema

Create these tables through `setup_database()` and safe local migration patterns where necessary.

### `eval_runs`

One high-level report per evaluation attempt.

```sql
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_article_id INTEGER NOT NULL,
    overall_status TEXT NOT NULL,
    faithfulness_score REAL,
    citation_validity_score REAL,
    citation_completeness_score REAL,
    contradiction_score REAL,
    coverage_score REAL,
    editorial_quality_score REAL,
    checks_json TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    judge_prompt_version TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (generated_article_id) REFERENCES generated_articles(id)
)
```

Suggested `overall_status` values:

```text
passed
failed
needs_review
error
```

Do not enforce one row per article. Multiple eval attempts are useful for comparisons after prompt or judge changes.

### `claim_evaluations`

One row per atomic factual claim in one eval run.

```sql
CREATE TABLE IF NOT EXISTS claim_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id INTEGER NOT NULL,
    claim_index INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    citation_ids_json TEXT NOT NULL,
    citation_valid INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL,
    severity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id)
)
```

Suggested verdicts:

```text
supported
partially_supported
unsupported
contradicted
not_factual
```

Suggested severities:

```text
major
minor
none
```

### Why Two Tables

`eval_runs` answers, "Did this edition pass and why?"

`claim_evaluations` answers, "Which exact sentence failed, which citations did it use, and what did the judge say?"

This separation is essential for an inspectable, resume-quality system.

## Phase 4: Claim Extraction

### Objective

Turn the generated body into a list of atomic factual claims. A sentence can contain multiple factual assertions, so sentence splitting alone is not enough.

### Input

- Generated article `body` containing inline citations.
- Citation map snapshot.

### Process

1. Deterministically identify paragraph and sentence boundaries for traceability.
2. Extract inline IDs using a strict regex, for example:

```python
r"\[S\d+-F\d+\]"
```

3. Send each sentence, or small batches of up to five sentences, to a claim-extractor model with structured output.
4. The extractor returns atomic claims and marks whether each is factual.
5. Every factual claim inherits the citation IDs from its source sentence.

### Claim Extraction Schema

```python
class ExtractedClaim(BaseModel):
    claim_text: str
    is_factual: bool
    citation_ids: list[str]
```

Rules for the claim extractor:

- Split compound factual statements into independently checkable claims.
- Ignore opinion, rhetorical transition, and purely stylistic text.
- Preserve the factual meaning; do not add claims.
- Return the citation IDs that appeared in the source sentence.

## Phase 5: Citation Validation and Completeness

These checks are deterministic but are not the whole eval.

### Citation Validity

For every extracted citation ID:

- Parse it successfully.
- Confirm it exists in the saved `citation_map_json`.
- Confirm the map includes an item ID, URL, claim, and supporting excerpt.

Invalid citation IDs are a hard failure.

### Citation Completeness

For every factual claim:

- It must have at least one citation ID.

An uncited factual claim is a hard failure.

Compute:

```text
citation_completeness_score = factual_claims_with_citations / total_factual_claims
```

## Phase 6: Claim-Level Faithfulness Judge

### Objective

For each factual claim, determine whether the cited evidence entails it.

This is the heart of the eval harness.

### Judge Input Per Claim

```text
Claim:
<atomic generated claim>

Cited evidence:
[S4-F1]
Source: <source name>
URL: <source URL>
Evidence claim: <stored evidence claim>
Supporting excerpt: <stored excerpt>
```

Do not provide unrelated evidence. The judge should assess the actual attribution, not search a large context for a convenient post-hoc justification.

### Judge Output Schema

```python
class ClaimVerdict(BaseModel):
    verdict: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "contradicted",
    ]
    confidence: float
    severity: Literal["major", "minor", "none"]
    rationale: str
```

### Judge Rubric

- `supported`: The excerpt directly states the claim or logically entails it without extra assumptions.
- `partially_supported`: Core claim is supported, but it adds an unproven qualifier, scope, cause, time frame, or degree.
- `unsupported`: The cited evidence does not establish the claim.
- `contradicted`: The cited evidence conflicts with the claim.
- `major`: Incorrect/unsupported claim changes the main meaning, number, actor, event, causality, or significance.
- `minor`: Small unsupported wording or non-central detail.

### Batching and Cost Control

Never send a 1,000-word article plus every raw article to the judge.

- Evaluate claims individually or in batches of at most five claims.
- Each claim sees only its cited evidence.
- Persist verdicts so reruns do not need to recompute unchanged claims.
- A future optimization may hash the claim plus cited evidence and cache the result.

### Judge Independence

The judge should use a configurable model and prompt version, separate from the writer configuration.

For a stronger setup, use a different model family or a more capable judge model than the writer when budget allows. If the same Gemini model is used initially, record that clearly in `eval_runs`; do not pretend it is an independent judge.

## Phase 7: Contradiction Evaluation

There are two useful contradiction checks.

### A. Article-to-Citation Contradiction

This is naturally covered by the per-claim verdict `contradicted`.

### B. Cross-Source Evidence Conflict

Before or during generation, compare evidence facts from different sources within the same cluster. The conflict judge should identify whether they disagree about material values such as:

- numbers or dates;
- actor or company;
- event outcome;
- causal explanation;
- scope or timeline.

If a conflict is found, the writer must either omit the disputed detail or explicitly attribute the disagreement. A material unresolved conflict blocks publishing.

Keep this check limited to selected cluster evidence. Do not compare all facts across all ingested articles.

## Phase 8: Coverage and Editorial-Quality Judge

Grounding alone can pass a dull or incomplete article. Use a separate structured LLM-as-a-judge pass for editorial quality.

### Inputs

- The generated article.
- Selected cluster metadata: rank, representative headline, source count.
- The citation map/evidence brief.

### Output Dimensions (1 to 5)

- `coverage`: Does the article cover the material selected top clusters?
- `relevance`: Does it prioritize important information rather than trivia?
- `coherence`: Does it build a readable narrative or a clearly organized briefing?
- `clarity`: Is the prose direct, precise, and non-repetitive?
- `editorial_value`: Does it explain why the developments matter without inventing facts?

The judge must return reasons for every score. The judge must not award high relevance merely because prose is fluent.

Use these scores as a review signal initially. Promote a threshold to a hard gate only after calibration against human judgments.

## Phase 9: Aggregate Scores and Publish Gate

### Metrics

```text
faithfulness_score = supported_factual_claims / total_factual_claims
citation_validity_score = valid_citations / total_citations
citation_completeness_score = cited_factual_claims / total_factual_claims
contradiction_score = 1 - contradicted_claims / total_factual_claims
coverage_score = editorial judge coverage score / 5
editorial_quality_score = mean editorial dimensions / 5
```

### Initial Hard-Gate Policy

These values are starting policies, not permanent scientific thresholds. Tune them after calibration.

```text
FAIL if title/body smoke checks fail.
FAIL if any citation ID is invalid.
FAIL if any factual claim has no citation.
FAIL if any major claim is unsupported or contradicted.
FAIL if a material cross-source conflict is unresolved.
NEEDS_REVIEW if minor unsupported or partially-supported claims exist.
NEEDS_REVIEW if editorial-quality scores are low.
PASS only when all hard gates pass.
```

Do not initially require a particular floating-point faithfulness threshold if a single major unsupported claim can hide inside an average. The major-claim gate is more meaningful.

### `generated_articles.eval_status`

Update after each eval:

```text
pending -> passed
pending -> failed
pending -> needs_review
```

The static publishing step must only render articles with `eval_status = 'passed'`.

## Phase 10: Calibration and Adversarial Benchmark

An LLM judge is not trustworthy merely because it produces scores. The eval harness itself needs evaluation.

### Create a Small Golden Set

Build 10 to 20 real source/evidence bundles. For each, manually label:

- supported claims;
- unsupported claims;
- partially supported claims;
- contradictions;
- expected citation IDs;
- major versus minor severity.

Keep these fixtures as JSON files in a test directory, not in the production database.

### Create Deliberate Mutations

For each bundle, create bad generated-output variants:

- change a number (`$100M` to `$1B`);
- swap a citation to another source;
- negate a fact;
- add a causal claim absent from evidence;
- attach one citation to an unrelated sentence;
- remove a citation;
- omit the top-ranked cluster;
- repeat a paragraph.

The evaluator should flag each mutation. If it does not, improve the rubric or judge process before trusting the publish gate.

### Calibration Metrics

Compare judge verdicts with manual labels and record:

- precision for unsupported/contradicted claims;
- recall for unsupported/contradicted claims;
- agreement by severity;
- false-pass examples;
- false-fail examples.

Version the benchmark and judge prompts. Do not silently alter a prompt and compare scores as if they were the same measurement.

## Recommended File Layout

```text
app/
  services/
    llm.py                    # writer, extraction, possibly small structured judge wrappers
    evaluation.py             # pure parsing, metrics, orchestration-independent eval logic
  database/
    db.py                     # schema and safe local migration helpers

generate_article.py           # builds labeled evidence, writes citation-aware article and snapshot
evaluate_article.py           # loads one edition, executes eval, persists reports, updates status

tests/
  fixtures/
    eval_goldens.json
  test_evaluation.py
  test_eval_mutations.py
```

Avoid putting all evaluation code in `generate_article.py`. Generation and evaluation must remain separately runnable.

## Implementation History and Remaining Order

Completed:

1. Add stable evidence IDs and build `citation_map_json`.
2. Add citation-aware writer instructions and regenerate one article with inline citations.
3. Add the citation-map/model/prompt-version fields to `generated_articles` and persist them.
4. Implement citation parsing, validity, and completeness checks.
5. Add `eval_runs` and `claim_evaluations` tables.
6. Implement structured atomic-claim extraction.
7. Implement the per-claim faithfulness judge and persist each verdict.
8. Add aggregate metrics and hard publish gate.

Remaining:

9. Add the cross-source conflict check.
10. Add the editorial-quality judge.
11. Build goldens and adversarial mutations.
12. Calibrate thresholds, document results, then mark the eval harness complete.

## Things Not To Do

- Do not call a generic single-prompt "quality evaluator" an eval harness.
- Do not evaluate against all raw articles at once.
- Do not let the judge inspect unrelated evidence when evaluating a citation.
- Do not rely on source links listed only at the end of an article.
- Do not store only one pass/fail boolean; persist claim-level reasons.
- Do not publish `pending`, `failed`, or `needs_review` articles.
- Do not claim objective truth verification; claim source-grounded evaluation.
- Do not make threshold decisions before manually reviewing initial judge results.

## Current Resume Positioning

For the implemented V1 core, use language like:

> Built a claim-level eval-gated news synthesis pipeline that maps every factual statement to source evidence, detects unsupported or contradicted claims with structured LLM judging, stores audit-ready verdicts, and blocks publication when groundedness checks fail.

Do not claim that the judge is calibrated or that the public site is live until the remaining work below is complete.

## Definition of Done

V1 core is complete when:

- [x] Generated articles contain inline evidence citations.
- [x] Each generated article stores an immutable citation/evidence snapshot.
- [x] Factual claims are extracted and evaluated against cited evidence.
- [x] Invalid citations, uncited claims, and major unsupported/contradicted claims fail the run.
- [x] Claim-level verdicts, reasons, models, and prompt versions are persisted.

The full, calibrated harness is complete when:

- [ ] Editorial coverage and quality are separately scored.
- [ ] Cross-source conflicts are detected for selected evidence.
- [ ] Goldens and adversarial mutations exist.
- [ ] Judge performance has been calibrated against manual labels.
- [ ] Only passed editions can be statically published.
