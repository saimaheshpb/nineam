# NineAM Automation Split

## Goal

Publish each generated article before evaluation, then evaluate and redeploy it
through a separate GitHub Actions workflow. Evaluation uses batches of 10 and a
shared cadence of three Gemini calls followed by a full 60-second cooldown.

## Working State

- Branch: `codex/eval-workflow-split`
- Baseline: `9cd4c31081ff33a56816f17aedb2367fbccb0057`
- Production workflows after completion: `daily.yml` and `evaluate.yml`
- This file is the current cross-session tracker. Prior milestones are complete
  history and are intentionally not carried into this plan.

## Milestones

### [x] COMPLETED — Milestone 1 — Separate Application Logic and Slow Evaluation

Required changes:

- Make `run_daily.py` stop after clustering and article generation; it must not
  import or invoke evaluation.
- Increase atomic-extraction batches to 10 sentences and judge batches to 10
  cited factual claims.
- Share one evaluation pacer across extraction and judging: calls 1–3 run,
  then the evaluator waits 60 seconds before call 4, and repeats that cadence.
- Make the evaluator CLI exit nonzero for runtime failure or a missing article.
- Add focused tests without real Gemini calls or real sleeping.

Completion evidence required:

- Full unit suite passes.
- Python compilation passes.
- `git diff --check` passes.
- Tests prove publisher/evaluator separation, `10/10/1` batching, 10-item
  limits, cross-stage pacing, and evaluator exit codes.

Completion evidence — 2026-07-14:

- Added generation-only daily orchestration with no evaluator dependency.
- Increased both evaluation batch types to 10 and added one shared three-call,
  60-second pacer across extraction and judging.
- Added explicit evaluator exit codes `0`, `1`, and `2`.
- `.venv/bin/python -m unittest discover -s tests -v` passed all 48 tests.
- Python compilation and `git diff --check` passed.

### [x] COMPLETED — Milestone 2 — Split and Clean GitHub Actions

Required changes:

- Keep `daily.yml` as the scheduled/manual publisher: collect, generate, build,
  deploy, and upload the exact edition-date artifact.
- Add `evaluate.yml`, triggered after a successful daily workflow and manually
  recoverable for an explicit edition date.
- Share the `nineam-daily` concurrency group so deployments cannot collide.
- Delete `collect.yml`, `publish.yml`, and the empty `init.yml`.

Completion evidence required:

- Exactly `daily.yml` and `evaluate.yml` remain.
- Workflow YAML parses successfully.
- Daily contains no evaluation command; evaluation contains no collection,
  clustering, or generation command.
- Full unit suite and `git diff --check` pass.

Completion evidence — 2026-07-14:

- Reworked `daily.yml` to resolve one IST edition date, publish the article,
  and upload the exact date for downstream evaluation.
- Added `evaluate.yml` with successful-`workflow_run` ordering and a required
  manual recovery date.
- Deleted `collect.yml`, `publish.yml`, and the empty `init.yml`; exactly two
  workflow files remain.
- Both workflows use `nineam-daily`; Ruby YAML parsing passed for both files.
- Command inspection confirmed publisher/evaluator separation.
- `.venv/bin/python -m unittest discover -s tests -v` passed all 48 tests.
- Python compilation and `git diff --check` passed.

### [ ] IN PROGRESS — Milestone 3 — GitHub and Production Verification

Required evidence:

- Commit and push the focused branch and open a draft pull request.
- After the workflows reach `main`, verify a daily run deploys the article
  before the evaluation workflow begins.
- Verify evaluation logs show batches no larger than 10 and a 60-second
  cooldown after every third evaluation call.
- Verify successful evaluation performs the second deployment.
- If Gemini returns another 503, verify only evaluation fails and recover with
  the manual evaluation workflow for the same edition date.

Milestone 3 stays pending until the change reaches `main` and live run URLs plus
deployment evidence are recorded here.

## Strict Exclusions

- No transient-error retries, rollback, or incomplete-evaluation cleanup.
- No database schema or migration changes.
- No model, prompt, scoring, publication-threshold, or UI changes.
- No article-generation or ingestion pacing changes.
- No dependency or README changes.
- No workflow files beyond `daily.yml` and `evaluate.yml`.
- No unrelated refactoring or cleanup.

## Cross-Session Resume Protocol

1. Read this file.
2. Run `git status --short --branch` and confirm the branch above.
3. Continue the first milestone not marked `COMPLETED`.
4. Run that milestone's required verification before marking it complete.
5. Record concise, exact evidence here when the milestone is completed.
