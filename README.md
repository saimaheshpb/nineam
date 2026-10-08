# NineAM

**One evidence-grounded AI and technology briefing, every morning.**

NineAM reads a dozen AI news feeds, extracts source-backed facts from each
article, groups related coverage into stories, and writes a single daily article
in which every factual sentence cites the exact evidence it came from. After
publishing, it checks each factual claim against its cited evidence and shows
the result on the page.

[Read today's edition →](https://nineam-nine.vercel.app)

NineAM does not decide what is objectively true. It answers a narrower question
it can actually check: *is each sentence supported by the source evidence it
cites?*

## What an edition contains

- One coherent article of 400+ words, built from the top five story clusters.
- Inline citations such as `[S4-F1]` that link each sentence to a stored source fact.
- A deduplicated list of the sources used.
- A transparency panel with claim counts, the supported share, contradictions,
  and the publication label.

## How it works

```text
12 RSS feeds ─▶ scrape ─▶ extract facts ─▶ embed ─▶ cluster & rank
                         (LLM, per article)  (local)
                                                         │
     publish ◀─ build static site ◀─ write article ◀────┘
        │                              (LLM, top 5 clusters)
        ▼
 split into claims ─▶ judge each claim ─▶ rebuild & republish
   (LLM)               (LLM, cited evidence only)
```

### 1. Collect: `main.py`

For each enabled feed in `app/config.py`, NineAM takes the five newest entries
and skips any URL already in the database. It scrapes the page text, then asks
the evidence-extraction model for structured metadata: headline, summary,
entities, category, a 1–10 importance score, and 3–6 key facts. Each fact
carries a short supporting excerpt from the article.

The summary is embedded locally with `all-MiniLM-L6-v2` and compared against
every stored story. A match at or above **0.75** cosine similarity is logged as
related coverage, and the article is stored either way so clustering can use it.
Each article is tagged with the `--edition-date` it was collected for. Ingestion
pauses 12 seconds between articles.

### 2. Cluster and rank: `cluster_articles.py`

Articles for the edition are grouped in a single pass: an article joins the
most similar existing cluster if their best similarity is at least **0.72**,
and otherwise starts a new one. Clusters are ranked by

```text
rank_score = 3 × cluster size + average importance + 2 × distinct sources
```

so stories covered widely by independent outlets rise to the top. Re-running
clustering for a date replaces that date's clusters.

### 3. Write: `generate_article.py`, orchestrated by `run_daily.py`

The five highest-ranked clusters become an evidence brief. Every fact gets a
stable citation ID, `S<item id>-F<fact number>`. The writer model must:

- use only the evidence in the brief;
- end every factual sentence with one or more citation IDs;
- avoid outside facts, speculation and invented quotes.

The article is stored together with an immutable snapshot of its sources,
cluster IDs and full citation map, so later evaluation never depends on live web
pages. `run_daily.py` will not regenerate an edition that already exists.
Calling `generate_article.py` directly will overwrite that date's article and
reset its evaluation to pending.

### 4. Evaluate: `evaluate_article.py`

Evaluation runs separately, after the article is live:

1. **Deterministic checks.** Title and body are present, sources and clusters
   are non-empty, every cited ID exists in the citation map, and the map is well
   formed. If any of these fail, evaluation stops and the run is marked `failed`.
2. **Claim extraction.** The body is split into sentences, sent in batches of
   10, and broken into atomic claims. Each claim inherits the citations of the
   sentence it came from.
3. **Claim judging.** Each cited factual claim is judged in batches of 10, only
   against the evidence it cites. Possible verdicts are `supported`,
   `partially_supported`, `unsupported` or `contradicted`. Each verdict also
   gets a severity (`major`, `minor` or `none`) and a rationale. Uncited
   factual claims are automatically `unsupported` and `major`.

Model calls are spaced 20 seconds apart, with a 60-second cooldown after every
third call.

| Status | Meaning |
| --- | --- |
| `passed` | Every factual claim is supported |
| `needs_review` | No major failures, but some claims are not fully supported |
| `failed` | A structural check failed, or a major claim is unsupported or contradicted |

Scores stored per run: faithfulness (supported ÷ factual claims), citation
validity, citation completeness (cited ÷ factual claims) and contradiction
(1 − contradicted ÷ factual claims).

### 5. Publish: `build_site.py` and `app/services/publication.py`

Once a generated article exists, the site is always built and deployed. A
separate publication policy decides the **label** the page shows:

| Outcome | Rule | Page label |
| --- | --- | --- |
| `clean` | Evaluation complete and every factual claim supported | Strict evaluation passed |
| `publishable_with_warnings` | All citations valid, at least 50% supported, under 20% contradicted | Published with warnings |
| `blocked` | Evaluation pending or incomplete, invalid citations, under 50% supported, or 20%+ contradicted | Evaluation flagged — published |

Before evaluation finishes, the panel reads *Evaluation pending — article
published*. A failed evaluation never takes an article down.

## Models

All model calls go through the
[Vercel AI Gateway](https://vercel.com/ai-gateway) using the OpenAI SDK and
strict JSON-schema structured output. Every response is validated locally with
Pydantic. There is no automatic retry and no fallback model, so a failed call
fails its step loudly.

| Role | Default model | Used in | Volume per edition |
| --- | --- | --- | --- |
| Evidence extraction | `anthropic/claude-haiku-5-5` | `main.py` | One call per new article |
| Article generation | `anthropic/claude-sonnet-5-5` (reasoning effort `low`) | `generate_article.py` | One call |
| Claim extraction | `openai/gpt-6-luna` | `evaluate_article.py` | One call per 10 sentences |
| Claim judging | `openai/gpt-6-luna` | `evaluate_article.py` | One call per 10 cited claims |
| Embeddings | `all-MiniLM-L6-v2` (local, CPU) | `main.py`, clustering | Free |

Each role can be overridden with an environment variable (see below).
Production sets them explicitly in both workflow files, and
`tests/test_model_config.py` fails if the workflows or `.env.example` drift from
the defaults in `app/services/llm.py`. When you change a model, change all
three places.

Every call logs a `gateway_response` JSON line with the role, the requested and
served model, the provider, token counts and cost. Search the Actions logs for
it to see exactly what production ran.

## Automation

Two GitHub Actions workflows run production:

| Workflow | Trigger | Does |
| --- | --- | --- |
| **Daily NineAM edition** (`daily.yml`) | Cron `30 5 * * *` (Asia/Kolkata), or manual with an optional date | Collects sources, generates the article, builds the site, deploys to Vercel, and hands the edition date to the evaluator |
| **Evaluate NineAM edition** (`evaluate.yml`) | When the daily run succeeds on `main`, or manual with a date | Evaluates that exact edition, rebuilds the site and redeploys it |

The evaluator checks out the same commit the publisher ran, so code and models
match across the two stages. Both workflows share the `nineam-daily` concurrency
group, so deployments never overlap. GitHub delays scheduled runs at busy times,
so in practice the edition usually lands mid-morning IST rather than exactly at
the cron time.

To recover a failed evaluation without regenerating anything, run **Evaluate
NineAM edition** manually with the edition date.

## Local setup

**Requirements:** Python 3.12, a Vercel AI Gateway API key, and optionally Turso
credentials.

```bash
git clone https://github.com/saimaheshpb/nineam.git
cd nineam

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `AI_GATEWAY_API_KEY` in `.env`. Leave both Turso variables empty to use the
local SQLite file `news_aggregator.db`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `AI_GATEWAY_API_KEY` | Yes | Authenticates every model call |
| `EVIDENCE_EXTRACTION_MODEL` | No | Overrides the evidence-extraction model |
| `ARTICLE_GENERATION_MODEL` | No | Overrides the writer model |
| `CLAIM_EXTRACTION_MODEL` | No | Overrides the claim-extraction model |
| `CLAIM_JUDGE_MODEL` | No | Overrides the claim judge |
| `TURSO_DATABASE_URL` | No | Production libSQL database URL |
| `TURSO_AUTH_TOKEN` | No | Production libSQL auth token |

The two Turso variables must be set together. Setting only one is an error
rather than a silent fallback to SQLite. In GitHub Actions, `VERCEL_TOKEN`,
`VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` are also required as repository
secrets.

## Run an edition locally

Pass the same edition date to every stage:

```bash
EDITION_DATE=$(date +%F)

python main.py --edition-date "$EDITION_DATE"        # collect and extract
python run_daily.py --edition-date "$EDITION_DATE"   # cluster and write
python build_site.py --edition-date "$EDITION_DATE" --output dist
python -m http.server 8000 --directory dist          # preview at localhost:8000

python evaluate_article.py --edition-date "$EDITION_DATE"
python build_site.py --edition-date "$EDITION_DATE" --output dist
```

You can also run individual stages:

```bash
python cluster_articles.py --edition-date "$EDITION_DATE"   # prints clusters
python generate_article.py --edition-date "$EDITION_DATE"   # overwrites that date's article
```

To copy a local SQLite database into Turso, set both Turso variables and run
`python import_sqlite_to_turso.py`. It validates relationships and JSON before
committing, and re-running it is safe.

### Exit codes

| Script | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `run_daily.py` | Article ready | Infrastructure error | No article could be produced |
| `evaluate_article.py` | Evaluation finished | Evaluation error | No article for that date |
| `build_site.py` | Site built | — | Missing article or build error |

## Data model

| Table | Stores |
| --- | --- |
| `items` | Scraped articles, extracted metadata, evidence facts, embeddings, edition date |
| `story_clusters` | Ranked story groups per edition |
| `story_cluster_items` | Which articles belong to which cluster |
| `generated_articles` | Article, source and citation snapshots, writer model, prompt version, `eval_status` |
| `eval_runs` | Scores, deterministic checks, judge model and prompt version per evaluation |
| `claim_evaluations` | One verdict, severity, confidence and rationale per factual claim |

Models and prompt versions are stored with each article and each evaluation run,
so results from different models or prompts are never mixed up.

## Project structure

```text
app/
  config.py                  RSS feed list
  assets/editorial.css       Site stylesheet
  database/db.py             SQLite / Turso connection and schema
  scrapers/                  RSS, article text, YouTube transcripts (not yet wired in)
  services/
    llm.py                   Gateway client, schemas, prompts, model defaults
    embeddings.py            Local sentence-transformer embeddings
    clustering.py            Greedy clustering and ranking
    evaluation.py            Citation parsing, sentence splitting, word counts
    publication.py           Publication policy (clean / warnings / blocked)
main.py                      Ingestion
cluster_articles.py          Clustering for one edition
generate_article.py          Evidence brief and article generation
run_daily.py                 Cluster and generate, without overwriting an existing edition
evaluate_article.py          Claim-level evaluation
build_site.py                Static site renderer
import_sqlite_to_turso.py    One-off SQLite → Turso migration
.github/workflows/           Daily publisher and evaluator
tests/                       Offline tests (no API calls)
NINEAM_EVAL_HARNESS.md       Evaluation design notes and roadmap
PLANS.md                     Plan from the publish/evaluate split (historical)
```

## Tests

The suite mocks every model call and sleep, so it is fast and uses no API
credits:

```bash
python -m unittest discover -s tests -v
```

It covers structured-output validation, prompt contracts, citation parsing,
evaluation batching and pacing, publication policy, the site renderer, the
SQLite-to-Turso import, workflow date handoff, and model-configuration drift.

## Known limitations

- The writer (Claude) and the judge (GPT) come from different families, but the judge is a small model. A stronger judge
  from a different family would be a more independent check.
- Not built yet (see `NINEAM_EVAL_HARNESS.md`): cross-source conflict
  detection, an editorial-quality judge, and a labelled golden set to calibrate
  the judge.
- Article scraping collects every `<p>` on the page, so boilerplate text can
  leak into the source text.
- The YouTube transcript scraper exists but is not part of ingestion yet.
- Evaluation pacing (20 s between calls, 60 s cooldowns) dates from earlier
  rate limits and may be more conservative than the Gateway needs.
