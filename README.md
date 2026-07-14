# NineAM

**A daily, evidence-grounded AI and technology briefing.**

NineAM turns reporting from multiple sources into one readable morning article.
It collects and structures source material, groups related coverage, generates a
citation-aware edition, publishes it as a static website, and then evaluates
every factual claim against its cited evidence.

[Read the latest NineAM edition](https://nineam-nine.vercel.app)

## Why NineAM

Most news aggregators produce a feed of links or disconnected summaries.
NineAM produces one coherent article while preserving the evidence behind it.

Each edition includes:

- one editorially structured AI and technology briefing;
- inline citations connected to immutable source evidence;
- a deduplicated source list;
- claim-level support and contradiction results;
- transparent pending, warning, or completed evaluation status.

NineAM does not claim to determine objective truth. Its evaluation reports
whether the article's factual claims are supported by the evidence cited beside
them.

## How It Works

```text
RSS sources
    ↓
article scraping and structured extraction
    ↓
source-backed facts and local embeddings
    ↓
semantic clustering and coverage ranking
    ↓
citation-aware article generation
    ↓
static build and first deployment
    ↓
atomic-claim extraction and evidence judging
    ↓
static rebuild with evaluation results
```

### 1. Collect and structure

`main.py` reads configured RSS feeds, scrapes the latest articles, and uses
Gemini structured output to extract metadata and evidence facts. Exact duplicate
URLs are skipped, while semantically related reporting from independent sources
is retained for clustering.

### 2. Cluster and rank

`cluster_articles.py` selects the edition window, clusters articles with local
sentence-transformer embeddings, and ranks stories using coverage, importance,
and source diversity.

### 3. Generate and publish

`run_daily.py` clusters the current edition when necessary and generates one
article from the selected evidence. Every factual sentence must cite a stable
evidence identifier such as `S4-F1`. The pending article is rendered by
`build_site.py` and deployed immediately.

### 4. Evaluate and enrich

`evaluate_article.py` validates citation structure, extracts atomic claims, and
judges each cited factual claim only against its attached evidence. Evaluation
uses batches of up to 10 sentences or claims. Requests are spaced 20 seconds
apart, with a full 60-second cooldown after every third evaluation call.

Evaluation is intentionally separate from initial publishing. A temporary model
failure can delay scores, but it cannot remove the already-published article.

## Automated Publishing

NineAM uses two GitHub Actions workflows:

1. **Daily NineAM edition** collects sources, generates the article, builds the
   static site, deploys it to Vercel, and uploads the exact edition date.
2. **Evaluate NineAM edition** starts only after the daily workflow succeeds,
   evaluates that exact article, rebuilds the site, and deploys the completed
   evaluation status.

Both workflows share one deployment concurrency group. The evaluation workflow
also supports manual dispatch for evaluation-only recovery without recollecting
sources or regenerating the article.

## Technology

- **Python 3.12** for ingestion, generation, evaluation, and static rendering
- **Gemini** for structured extraction, article generation, and claim judging
- **Sentence Transformers** for local semantic embeddings
- **Turso/libSQL** for production persistence
- **SQLite** as the zero-configuration local database
- **GitHub Actions** for scheduled and recovery workflows
- **Vercel** for static production deployment

## Local Setup

### Prerequisites

- Python 3.12
- a Gemini API key
- optional Turso credentials for cloud persistence

### Install

```bash
git clone https://github.com/saimaheshpb/nineam.git
cd nineam

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`. Leave both Turso variables empty to use the local
`news_aggregator.db` database.

### Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | Structured extraction, generation, and evaluation |
| `TURSO_DATABASE_URL` | No | Production libSQL database URL |
| `TURSO_AUTH_TOKEN` | No | Production libSQL authentication token |

`TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` must either both be configured or
both be empty. Partial Turso configuration fails explicitly instead of silently
falling back to SQLite.

GitHub Actions additionally uses `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and
`VERCEL_PROJECT_ID` as repository secrets.

## Run an Edition Locally

Choose the edition date explicitly so every stage operates on the same data:

```bash
EDITION_DATE=2026-07-14

python main.py
python run_daily.py --edition-date "$EDITION_DATE"
python build_site.py --edition-date "$EDITION_DATE" --output dist
```

Preview the initial static edition:

```bash
python -m http.server 8000 --directory dist
```

Run evaluation separately, then rebuild the page with its completed status:

```bash
python evaluate_article.py --edition-date "$EDITION_DATE"
python build_site.py --edition-date "$EDITION_DATE" --output dist
```

Individual development stages remain directly executable:

```bash
python cluster_articles.py --edition-date "$EDITION_DATE"
python generate_article.py --edition-date "$EDITION_DATE"
```

## Data Model

NineAM keeps the source-to-claim trail in six tables:

| Table | Stores |
| --- | --- |
| `items` | Scraped articles, metadata, evidence facts, and embeddings |
| `story_clusters` | Ranked story groups for an edition |
| `story_cluster_items` | Article membership within each cluster |
| `generated_articles` | Final article, source snapshot, citations, and evaluation status |
| `eval_runs` | Aggregate evaluation results and deterministic checks |
| `claim_evaluations` | One evidence verdict and rationale per factual claim |

The generated article stores its source and citation snapshots, so later
evaluation does not depend on mutable web pages.

## Project Structure

```text
app/
  config.py                 RSS source configuration
  database/db.py            SQLite and Turso connection layer
  services/                 LLM, embeddings, clustering, and policy logic
  scrapers/                 RSS and article extraction
main.py                     Source ingestion
cluster_articles.py         Edition clustering and ranking
generate_article.py         Evidence-grounded article generation
run_daily.py                Generation-only daily orchestrator
evaluate_article.py         Claim-level evaluation harness
build_site.py               Static site renderer
.github/workflows/          Daily publisher and downstream evaluator
tests/                      Offline unit and regression tests
PLANS.md                    Current implementation and verification ledger
```

## Tests

The test suite uses mocks for Gemini and does not consume API quota:

```bash
python -m unittest discover -s tests -v
```

Useful verification commands:

```bash
python -m compileall -q main.py cluster_articles.py generate_article.py \
  evaluate_article.py run_daily.py build_site.py app tests
git diff --check
```

## Operational Notes

- The edition window uses stored UTC timestamps corresponding to an IST morning
  cutoff.
- Exact URL duplicates are skipped; independent related coverage is preserved.
- Generated editions are not silently overwritten on reruns.
- Evaluation results describe support from cited sources, not universal truth.
- Free GitHub runners and external model APIs provide no strict timing SLA.

Current implementation and production-verification progress are tracked in
[`PLANS.md`](PLANS.md).
