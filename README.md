# NineAM

NineAM is a daily AI/tech news synthesis system. By 9 AM, it should publish one readable, evidence-backed article generated from multiple sources.

Read this overview first, then read `PLANS.md`, the cross-session execution
checkpoint. Together they let a new chat understand the product, current state,
decisions, and next steps without digging through old conversation context.

Last verified: 2026-07-12. The local V1 pipeline, core claim-level eval harness,
and daily publication gate are implemented. The saved edition has 11 unsupported
claims out of 59, so the strict evaluator marks it failed while the publication
policy makes it publishable with warnings; static rendering is not wired yet.

## Product Goal

Turn many noisy AI/tech news sources into one medium-sized daily article.

NineAM is not meant to be:

- a chatbot
- a generic LLM wrapper
- a dashboard full of summaries
- a social/newsletter platform in V1

The resume-worthy engineering story is:

```text
multi-source ingestion
-> structured extraction
-> evidence capture
-> local embeddings
-> semantic clustering
-> cluster ranking
-> article generation
-> eval-gated publishing
```

## V1 Output

The final V1 product should be a simple static website with:

- brand: NineAM
- edition date
- one headline
- one ~1200-word article
- source links
- small transparency section with source/article/cluster/eval metadata

The site should be article-first, not a feed reader.

## Daily Edition Rule

Each article belongs to an `edition_date`.

For V1, the edition window is:

```text
previous day 8:00 AM IST -> edition date 8:00 AM IST
```

Example:

```text
2026-07-10 edition
= articles processed from 2026-07-09 08:00 IST through 2026-07-10 08:00 IST
```

Current caveat: V1 uses `processed_at` as the edition timestamp. Later, RSS parsing should store actual article `published_at`.

## Current Pipeline

Current implemented flow:

```text
app/config.py
  -> RSS sources
main.py
  -> fetch latest source links
  -> scrape article text
  -> Gemini structured extraction
  -> evidence facts
  -> local embedding
  -> exact URL skip
  -> semantic match logging
  -> Turso items in production, local SQLite during development
cluster_articles.py
  -> load current edition articles
  -> cluster by cosine similarity
  -> rank clusters
  -> save story_clusters and story_cluster_items
generate_article.py
  -> load top clusters
  -> build evidence brief
  -> generate citation-aware article draft with Gemini
  -> save generated_articles row
evaluate_article.py
  -> validate citation structure
  -> extract atomic claims
  -> judge claims against cited evidence
  -> save eval_runs and claim_evaluations
  -> update generated_articles.eval_status
run_daily.py
  -> run only missing stages for one edition
  -> derive clean / publishable_with_warnings / blocked publication outcome
  -> preserve completed editions as no-ops
build_site.py
  -> render a clean or warning edition as static HTML and CSS
  -> expose source-grounded evaluation metrics without a runtime API
```

Target V1 flow still needed:

```text
generated_articles row
  -> eval harness
  -> publication policy
  -> static site generation
```

## Current Status

Implemented:

- Multi-source RSS configuration in `app/config.py`.
- Article scraping in `app/scrapers/article.py`.
- Shared Turso/local-SQLite connection and schema setup in `app/database/db.py`.
- Idempotent, relationship-aware SQLite-to-Turso import and verification.
- Production Turso database seeded with the current six-table dataset.
- Gemini structured extraction in `app/services/llm.py`.
- Evidence extraction into `items.evidence_json`.
- Local embeddings in `app/services/embeddings.py`.
- Semantic match detection in `main.py`.
- Edition-window clustering in `cluster_articles.py`.
- Cluster ranking in `app/services/clustering.py`.
- Generated article persistence in `generate_article.py`.
- Citation-aware generated article persistence and evidence snapshots.
- Deterministic citation-map and citation-ID validation.
- Atomic claim extraction and cited-evidence faithfulness judging.
- Claim-level eval persistence in `eval_runs` and `claim_evaluations`.
- Publish status updates: `pending`, `passed`, `failed`, and `needs_review`.
- Publication decisions: `clean`, `publishable_with_warnings`, and `blocked`.
- One-command daily orchestration with completed-edition no-ops.
- Static article rendering with linked citations and claim-level transparency.

Pending for V1:

- A scheduler that runs before 9 AM IST.
- Repository cleanup: remove editor/runtime artifacts and unneeded legacy modules.
- Broader tests, including eval integration fixtures and failure cases.

Pending after the first shippable V1:

- Use RSS `published_at` instead of `processed_at` for edition membership.
- Add retries, explicit error states, and stronger idempotency around network/API calls.
- Detect unresolved conflicts between evidence from different sources.
- Add a separate editorial coverage/quality judge.
- Build golden examples, adversarial mutations, and manual judge calibration.

## Active Files

Keep these for V1:

- `main.py` - ingestion pipeline
- `cluster_articles.py` - edition clustering and cluster persistence
- `generate_article.py` - article draft generation
- `run_daily.py` - idempotent daily orchestration and publication outcome
- `build_site.py` - static edition renderer
- `app/config.py` - RSS source list
- `app/database/db.py` - Turso/local-SQLite connection selection and schema setup
- `import_sqlite_to_turso.py` - safe one-time cloud import and verification
- `app/scrapers/rss.py` - RSS parsing
- `app/scrapers/article.py` - article text scraping
- `app/services/llm.py` - Gemini extraction and generation
- `app/services/embeddings.py` - local embedding and cosine similarity helpers
- `app/services/clustering.py` - story clustering and ranking
- `app/services/publication.py` - shared clean/warning/blocked policy
- `app/assets/editorial.css` - responsive editorial site stylesheet

Likely remove or ignore:

- `backfill_evidence.py` - one-time migration helper if evidence backfill is complete
- `app/runner.py` - legacy generic runner
- `app/services/digest.py` - old digest path, superseded by `generate_article.py`
- `app/scrapers/youtube.py` - out of V1 scope unless YouTube ingestion returns
- `news_aggregator.db` - local runtime database, do not commit
- `.env` - local secrets, do not commit
- `.idea/` - editor metadata, usually do not commit
- `__pycache__/` and `*.pyc` - generated Python cache files
- `.venv/` - local environment, do not commit

## Database Tables

Current tables:

- `items`
  - stores source metadata, article text, extracted metadata, evidence JSON, embeddings, and `processed_at`
- `story_clusters`
  - stores edition clusters, representative headline, cluster size, rank score, and `run_date`
- `story_cluster_items`
  - stores article membership for each cluster
- `generated_articles`
  - stores generated title/body, source snapshot, citation map, model/prompt versions, and eval status
- `eval_runs`
  - stores one evaluation attempt, aggregate scores, deterministic checks, model, and prompt version
- `claim_evaluations`
  - stores one verdict and rationale for each extracted factual claim

There is no separate `eval_reports` table. `eval_runs` is the evaluation report, and `claim_evaluations` contains its detailed evidence trail.

## Key Design Decisions

### One Article, Not Many Cards

The visible product should be one daily article. The complexity belongs in the backend pipeline.

### Evidence-First Generation

NineAM should generate from extracted evidence facts:

```text
claim + supporting excerpt
```

This avoids dumping raw article text into a huge prompt and sets up later factual evals.

### Keep Semantically Related Coverage

Exact duplicate URLs are skipped, but semantically similar independent articles are stored.

Reason: if multiple sources cover the same story, clustering should see that and ranking should reward source diversity.

### Ranking Is A V1 Heuristic

Current cluster score:

```text
rank_score =
  cluster_size * CLUSTER_SIZE_WEIGHT
  + average importance_score
  + unique_source_count * SOURCE_DIVERSITY_WEIGHT
```

Current weights:

```python
CLUSTER_SIZE_WEIGHT = 3
SOURCE_DIVERSITY_WEIGHT = 2
```

This is intentionally simple and explainable. It can be tuned later.

### Use Gemini Carefully

The user wants the project to stay free, relying on Gemini's generous free tier. Keep test runs small and avoid unnecessary backfills.

## How To Run Current Pipeline

Use the project virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
.venv/bin/python cluster_articles.py
.venv/bin/python generate_article.py
.venv/bin/python evaluate_article.py
.venv/bin/python run_daily.py --edition-date YYYY-MM-DD
.venv/bin/python build_site.py --edition-date YYYY-MM-DD --output dist
```

Database selection:

- with both `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`, every stage uses Turso;
- with neither variable, every stage uses the local `news_aggregator.db`;
- configuring only one variable is an error, preventing silent local fallback.

`.env.example` documents the required variable names without containing secrets.
To verify or import an existing local database after configuring Turso:

```bash
.venv/bin/python import_sqlite_to_turso.py
```

Notes:

- `main.py` can call Gemini once per processed article.
- `generate_article.py` calls Gemini once for the daily article draft.
- `evaluate_article.py` may call Gemini for claim extraction and claim judging. It batches claims and waits between requests to protect the free tier.
- Keep `latest_links = get_latest_urls(source.url, 1)` while testing to protect free-tier usage.

## Next Chat: Start Here

Read `PLANS.md` and begin the first milestone not marked complete. The next
milestone is GitHub Actions and Vercel publishing.

## Current Known Issues

- The latest real article was marked `failed` by the strict evaluator because 11
  claims were unsupported. Milestone 3's separate publication policy classifies
  it as `publishable_with_warnings` (48/59 claims supported, no
  contradictions); Milestone 4 must disclose this visibly if it renders it.
- The evaluator currently uses LLM claim extraction and judging but has no golden benchmark or calibration report.
- If a Gemini claim-extraction or judging call is interrupted, the current run can remain at `needs_review` instead of being recorded as `error`.
- Cross-source contradiction detection and editorial-quality scoring are not implemented.
- `story_cluster_items.similarity_to_representative` is currently saved as `NULL`.
- The pipeline has a daily orchestrator but no scheduler yet.
- The static builder is local only; GitHub Actions and Vercel deployment are
  not implemented yet.
- Article scraping is basic and may include boilerplate.
- `processed_at` is used instead of article `published_at`.
- Local SQLite remains the no-credential development fallback; Turso is the
  durable cloud database, while scheduling and static deployment are not yet
  implemented.

## Resume Positioning

Current phrasing:

> Built NineAM, an automated AI/tech news synthesis pipeline that ingests multi-source RSS feeds, extracts structured article metadata and source-backed evidence with Gemini, generates local sentence-transformer embeddings, clusters semantically related stories with cosine similarity, ranks clusters by coverage and source diversity, and generates a daily article from selected evidence.

After static publishing and scheduler:

> Added an eval-gated static publishing workflow that validates citation structure and claim-level source support before publishing a daily 9 AM briefing.

## Guidance For Future Chats

The user wants to write and understand the code personally. Future assistants should:

- read this file first
- inspect current code before advising
- give small-to-medium code chunks
- explain why each change matters
- keep the project focused on shipping V1
- avoid scope creep
- avoid unnecessary Gemini calls during testing
