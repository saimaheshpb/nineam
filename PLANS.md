# NineAM Production ExecPlan

This file is the cross-session implementation checkpoint for taking NineAM from
the verified local pipeline to a daily static website hosted on Vercel.

Only one milestone may be implemented at a time. After a milestone is complete,
run its verification steps, mark it `[x] COMPLETED`, record the evidence in this
file, and stop for explicit user approval before starting the next milestone.

## Product Outcome

NineAM publishes one readable AI/technology article by 9:00 AM IST every day.
The production content window is the previous day at 8:00 AM IST through the
edition day at 8:00 AM IST. The hour between cutoff and publication is reserved
for final ingestion, clustering, generation, evaluation, static rendering, and
deployment.

The public product remains article-first: one edition date, one headline, one
medium-length article, source links, and a compact transparency section. It is
not a feed reader, dashboard, account system, or public API.

## Target Architecture

```text
GitHub Actions (scheduled and manual runner)
  -> Python ingestion, clustering, generation, and evaluation
  -> Turso hosted SQLite-compatible database (durable production state)
  -> publication decision: clean / publishable_with_warnings / blocked
  -> Python static-site builder writes dist/index.html and dist/styles.css
  -> Vercel CLI deploys the immutable static artifact
  -> readers receive HTML/CSS only; no browser-to-database connection
```

Code and design changes travel through Git branches. Daily article updates do
not create Git commits: the scheduled workflow builds a fresh static artifact
and deploys that artifact directly to Vercel.

## Locked Decisions

- Hosting: Vercel.
- Durable production database: Turso, using its remote SQLite-compatible Python
  client. Local SQLite remains available as a development fallback.
- Repository workflow: protect a clean `main` baseline and implement production
  work on `codex/vercel-site`.
- Edition window: `[previous-day 08:00 IST, edition-day 08:00 IST)`.
- Publication target: by 09:00 IST on free, best-effort infrastructure.
- Daily generation budget: one generated article and one full evaluation in V1;
  no automatic second generation/evaluation.
- Publication policy:
  - `clean`: strict evaluation passes.
  - `publishable_with_warnings`: readable, sourced output with non-catastrophic
    citation, grounding, length, or evaluator issues.
  - `blocked`: empty or malformed output, no source snapshot, fewer than 50% of
    judged factual claims supported, or at least 20% contradicted claims.
- If an edition is blocked, keep the previous deployed edition live.
- V1 shows the latest edition only. Archives, search, authentication, a CMS, and
  a public runtime API are out of scope.

## Milestones

### [x] COMPLETED — Milestone 1 — Repository Safety and GitHub Baseline

Objective: preserve the verified local pipeline in a clean GitHub repository
before production changes begin.

Implementation:

- Add this ExecPlan and a root `.gitignore`.
- Exclude `.env`, SQLite files, virtual environments, caches, IDE metadata,
  generated static output, and local Vercel metadata.
- Rebuild the initial Git index so ignored secrets and runtime artifacts are not
  committed while keeping the local files intact.
- Review the staged file list and check the staged patch for whitespace errors
  and obvious embedded credentials.
- Run the existing evaluation unit tests.
- Commit the verified baseline to `main` and push it to a private GitHub
  repository.
- Create and push `codex/vercel-site` for Milestones 2-5.

Completion evidence required:

- Existing unit test suite passes.
- `.env`, `*.db`, `.idea/`, `.venv/`, and Python caches are absent from Git.
- GitHub contains the baseline `main` branch.
- Local and remote `codex/vercel-site` branches exist and track one another.

### [ ] Milestone 2 — Turso Persistence

Objective: give the pipeline durable cloud storage while preserving the current
SQLite-style schema and local development path.

Implementation:

- Add the Turso/libSQL dependency and document required environment variables:
  `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`.
- Centralize database connections behind one function that uses Turso when both
  credentials exist and local SQLite otherwise.
- Route ingestion, clustering, generation, evaluation, and schema setup through
  that connection function.
- Remove SQLite-only row handling that is incompatible with the remote client.
- Add an idempotent import command that copies the current local database to an
  empty Turso database in foreign-key order without printing secrets.
- Verify schema, row counts, relationships, JSON fields, and representative
  article/evaluation values after import.

Completion evidence required:

- Existing unit tests pass.
- Database-focused tests cover local selection, Turso selection, and missing
  partial credentials without making a live network call.
- All current pipeline reads/writes work against a test Turso database.
- Imported Turso table counts match the local source database.

### [ ] Milestone 3 — Edition Timing, Publication Policy, and Daily Command

Objective: turn the separate pipeline stages into one safe, repeatable daily
operation.

Implementation:

- Capture RSS `published_at` timestamps and persist them on source items.
- Use the locked 8:00 AM IST cutoff and UTC query bounds for edition membership.
- Add one orchestration command:
  `python run_daily.py --edition-date YYYY-MM-DD`.
- Run setup, bounded ingestion, clustering, generation, evaluation, publication
  decision, and site-build eligibility in order.
- Keep initial ingestion to at most one eligible unseen article per configured
  source so Gemini 2.5 Flash remains within the observed free daily allowance.
- Prevent a completed evaluated edition from being silently overwritten.
- Make reruns idempotent and return clear clean, warning, blocked, and
  infrastructure-error outcomes.

Completion evidence required:

- Existing and new orchestration tests pass without Gemini calls.
- Boundary tests prove start-inclusive/end-exclusive IST-to-UTC behavior.
- A second run of the same completed edition is a no-op.
- The current 48/59-supported article is classified as publishable with
  warnings; catastrophic fixtures are blocked.

### [ ] Milestone 4 — Static Article Website

Objective: render the selected edition as a small, safe, responsive static site.

Implementation:

- Add `python build_site.py --edition-date YYYY-MM-DD --output dist`.
- Generate `dist/index.html` and `dist/styles.css` from a publishable database
  edition.
- Render NineAM branding, edition date, headline, article, numbered source
  links, a deduplicated source list, and compact transparency metrics.
- Explain the ingestion-to-evaluation pipeline without turning the page into a
  dashboard.
- Escape generated text before adding HTML structure or citation links.
- Include responsive layout, accessible link/focus treatment, and readable
  article typography without a frontend framework or runtime API.

Completion evidence required:

- Static-builder tests cover escaping, citation resolution, source
  deduplication, status rendering, and blocked-edition rejection.
- The existing representative edition renders locally without secrets or broken
  links.
- Manual desktop and mobile inspection confirms the article-first layout.

### [ ] Milestone 5 — GitHub Actions and Vercel Publishing

Objective: run and publish NineAM automatically using free-tier infrastructure.

Implementation:

- Add a manually triggered GitHub Actions workflow first.
- Cache Python dependencies and the embedding model.
- Configure GitHub secrets for Turso, Gemini, and Vercel; never echo them.
- Run the daily command and deploy `dist/` directly with Vercel CLI only when
  the publication decision is clean or publishable with warnings.
- Preserve the previous Vercel production deployment when blocked.
- After a successful manual end-to-end run, add scheduled executions at 8:07 AM
  and 8:32 AM IST with a concurrency lock and an early no-op for an already
  published edition.
- Keep `workflow_dispatch` as the recovery path because free scheduled runners
  provide no timing SLA.

Completion evidence required:

- GitHub Actions completes a manual production run.
- The Vercel production URL shows the selected edition.
- A repeated workflow does not duplicate work or consume unnecessary model
  quota.
- A simulated blocked edition does not replace the previous production page.
- The scheduled workflow is enabled only after the manual path is verified.

## Cross-Session Resume Protocol

At the beginning of a new session:

1. Read `README.md`, then this file.
2. Run `git status --short --branch` and confirm the current branch.
3. Identify the first milestone not marked `[x] COMPLETED`.
4. Read its completion evidence before editing.
5. Implement only that milestone.
6. Run its required verification.
7. Record concise evidence here, mark it complete, and stop for user approval.

## Completion Log

### 2026-07-12 — Milestone 1 completed

- Added the root `.gitignore` and this cross-session ExecPlan.
- Rebuilt the initial index without deleting local files; `.env`, `*.db`,
  `.idea/`, `.venv/`, and Python caches are ignored and absent from Git.
- `git diff --cached --check` passed before the baseline commit, and a staged
  secret-pattern scan found no credential values.
- `.venv/bin/python -m unittest discover -s tests -v` passed all 7 tests.
- `.venv/bin/python -m compileall -q main.py cluster_articles.py
  generate_article.py evaluate_article.py app tests` passed.
- Baseline commit `681356d` was pushed to `main` at
  `https://github.com/saimaheshpb/nineam`.
- Created local `codex/vercel-site`; the milestone checkpoint commit on this
  branch will be pushed before pausing.
