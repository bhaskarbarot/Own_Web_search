# OwnSearch quality improvement handoff

Date: 2026-10-21, Asia/Kolkata. Instructions: win_win.md and AGENTS.md.

## Ordered roadmap and gates

| Phase | Work | Required evidence before advancing |
| --- | --- | --- |
| 0 (current) | Freeze baseline, dataset, split, judging and metrics | Reproducible dev recording and judged quality measurements with CIs |
| 1 (pending) | Provider resilience, intent-safe vertical discovery, operators, query variants | Lower zero-result rate, better pooled recall, no strict P@5 regression, failure-injection pass |
| 2 (pending) | URL deduplication, passage relevance, trust signals, entity focus, snippets | Better strict P@5/NDCG, reduced duplicates and broken snippets, component ablations |
| 3 (pending) | Profile, progressive delivery, deadlines and bounded freshness-aware caching | Cold/warm latency measurements and unchanged quality within uncertainty |
| 4 (pending) | Evidence-grounded claims, conflict handling and abstention | Citation support, answer correctness and unsupported-claim measurements |
| 5 (sealed, pending) | Once-only baseline/final holdout comparison; no code changes | Full saved report, uncertainty, limitations and human review |

This is the execution order from win_win.md. Detailed later-phase plans are
written only after the preceding phase passes. Numeric targets are goals,
never claims about unmeasured performance.

## Current phase and preserved baseline

Phase 0 implementation and full dev capture are complete; its quality gate is awaiting human judgments and five missing reference pools. No search-behaviour files have changed. Do not start
Phase 1 until the Phase 0 gate passes.

- Baseline tag: baseline-v0 -> 344dedc3f50a2d4811ede23b25700d97c9f9a41d.
- Engine fingerprint (legacy evaluator algorithm):
  0aede2ad15dc6acdc822052c695670cd60977ba17224df7b03a6566d1bc6fc3d.
- Plan: docs/plan/phase-0.md.
- Existing synthetic fixture query bytes preserved in eval/legacy/queries.jsonl.
  Only its runner default and fixture validation test now refer to that path.
- New live-v1: 500 distinct queries, exact 100 query.md cases plus 400 authored
  cases across 16 additional categories; 300 dev / 200 sealed by SHA-256 ID rank.
  Frozen IDs and hashes: eval/splits.json. Use eval/dev.jsonl only in phases 0–4.
  Dataset hash: a3a3a5cc6526abaa4100b82912a722c94b6bd5a59f9d0729e1329981956bd846.
- Queries were developer-authored; the split does not establish independent
  authorship. Previously used original benchmark cases remain disclosed.

## Step 1 — preserve fixtures and freeze the evaluation split

Measured against baseline-v0 (code hash above), with no runtime changes:

| Offline preservation metric (59 synthetic cases) | Before | After dataset setup | Delta |
| --- | ---: | ---: | ---: |
| P@5 | 0.200000 | 0.200000 | 0 |
| Recall@10 | 0.880117 | 0.880117 | 0 |
| MRR@10 | 0.947368 | 0.947368 | 0 |
| NDCG@10 | 0.914425 | 0.914425 | 0 |
| Zero-result rate | 0.084746 | 0.084746 | 0 |

These are local synthetic-corpus metrics, not live-web accuracy. Both raw reports
include bootstrap CIs: eval/runs/phase0-offline-before.json and
phase0-offline-after-dataset.json. Latency varies and is not a search speed ablation.

Existing suite: **246 tests passed in 48.827 s** with localhost fixture access
(eval/runs/phase0-tests-baseline.txt). The initial sandboxed run could not start
local HTTP fixtures; that failure is retained in phase0-tests-before.txt and was
resolved by granting the test command socket access, without changing tests or
search implementation. A ResourceWarning was emitted but no test failed.

## Step 2 — live capture and judging pipeline implemented

- eval/live_eval.py captures only fixed dev IDs, checkpoints each query, refuses
  mismatched resume settings, retains provider batches and safety statuses.
- Cold requests bypass OwnSearch's response cache. An immediate repeated query
  is captured for a deterministic 10% subset, under the unchanged cache policy.
  Cache is disabled in the current configuration; repeated timings are not
  response-cache-hit timings.
- eval/RUBRIC.md defines grades, pooling, null metrics, provenance audits,
  independence and seeded 10% human review sampling.
- Confirmed evaluation regression: deduplicating ranks before P@5 moved a sixth
  result into the first five. Fixed in the new evaluator and covered by a
  hand-calculated test; duplicate URLs retain their original rank positions.
- Twelve new evaluation regression tests pass, including human-review import,
  spreadsheet-text handling, stale judgment rejection, null measurements and
  rank-preserving duplicate scoring. Full suite: **258 passed in 47.308 s**
  (eval/runs/phase0-tests-after-pipeline-final.txt).
- Live provider observations already show Brave rate limits, Google access
  denials and DuckDuckGo timeouts; preserved without bypass or relabeling.
- The installed local discovery backend was stopped at session start. It was
  started using existing configuration for measurement; no provider config changed.

- Offline preservation metrics after the complete evaluator step are identical
  to Step 1 and baseline: eval/runs/phase0-offline-after-pipeline.json.
- All **82 tracked engine files** match baseline-v0 byte-for-byte; see
  eval/runs/baseline-source-manifest.json. This is stronger than the legacy
  fingerprint, which excludes some resource suffixes.
- User explicitly selected **Prepare CSVs for my review**. No LLM grading is run.
  The importer accepts completed human fields and preserves judgment history.
- Dataset step commit: 92ea64b; pipeline step commit: 2691519. This follows
  the baseline without any
  search-behaviour change. The raw capture's code_git_hash identifies the engine
  checkout at capture start; the engine manifest establishes exact equivalence.

## Step 2b — explicit CSV independence labels

Commit d02facf. CSV review candidates now explicitly show independent_review=False rather than
an empty cell. Twelve evaluator regression tests pass after the change, and
all five offline quality measurements remain identical to baseline
(eval/runs/phase0-offline-final.json). This affects review artifacts only.
The final full suite ran after recording: **258 tests passed in 48.759 s**
(eval/runs/phase0-tests-final.txt).

## Step 3 — full dev recording complete; quality gate not passed

Recorded **300/300 dev queries**, plus **30 deterministic immediate repeats**, on
2026-10-21 from 11:02:22 to 11:35:58 IST. No sealed queries were run.
The response cache remained disabled, and all 30 repeats report cache_hit=False.
Warm numbers below therefore describe repeated requests, not cache hits.

Raw capture: eval/runs/baseline-dev.json. Metrics and bootstrap intervals:
eval/runs/baseline-dev-metrics.json. Metrics, pools and review CSVs reproduce
byte-for-byte with the documented command (eval/runs/phase0-verification.json).

| Live baseline measurement | Value | Bootstrap 95% CI | Queries |
| --- | ---: | --- | ---: |
| Cold p50 | 5.116 s | 5.070–5.168 s | 300 |
| Cold p95 | 8.035 s | 7.592–8.137 s | 300 |
| Cold p99 | 8.250 s | 8.136–8.374 s | 300 |
| Warm p50 | 5.131 s | 4.972–5.973 s | 30 |
| Warm p95 | 8.024 s | 6.952–8.525 s | 30 |
| Warm p99 | 8.402 s | 7.632–8.525 s | 30 |
| Zero-result rate, all cases | 31.33% | 26.00–36.67% | 300 |
| Zero-result rate, excluding explicit nonexistent-entity controls | 28.22% | 23.34–33.81% | 287 |

These are new observations on a larger development set, not a speed or accuracy
improvement over the old 100-case run. Early capture overlapped setup tests;
OS caches, upstream caches, provider suspension and shared-host load were not
controlled. Queries ran in dataset order, so category and temporal provider
availability may be confounded. CIs resample queries and do not remove that bias.

### Quality, provenance and source failures

- 206 cold queries returned results; 94 were empty. Nonemptiness is not accuracy.
- 3,719 pooled query/URL pairs; **0 graded**, **0 independently reviewed**.
  Recall@10, NDCG@10, MRR@10, P@5 and strict P@5 remain **null**, with null CIs.
- 1,610 unique returned query/URL pairs; **0 have explicit URL audits**.
  Fabricated-URL count remains **null**, not zero. Mechanical provenance gaps
  are 0; that is not proof that every URL exists or every claim is supported.
- SearXNG adapter status was ok in all 300 cold requests, but upstream failures
  remained: Brave suspension/rate-limit warning in 291 queries, Google suspension/
  denial warning in 291, Mwmbl timeout in 66, and DuckDuckGo suspension, CAPTCHA
  or access-denial warnings. Adapter completion does not establish upstream health.
- Structured answer correctness and citation support have not been graded.

Diagnostic empty-response counts (not relevance judgments):

| Development group | Empty / total |
| --- | ---: |
| Verbose requests | 14 / 14 |
| Exact phrase | 12 / 13 |
| Operators | 8 / 14 |
| Multilingual | 8 / 11 |
| Comparison | 8 / 11 |
| News | 9 / 20 |
| Original coding-agent cases | 7 / 7 |
| Original research-agent cases | 4 / 4 |

These identify cases to investigate after grading; no runtime tuning was done.

### Human-review handoff

User chose CSV review. Files are ready:

- eval/human_review_queue.csv: **3,719 unjudged rows**, grouped by query.
- eval/human_review_candidates.csv: **372 unjudged candidates** (seeded 10%).
- eval/human_review.csv: header only, because no actual judgments exist yet.
  After labels are imported, this becomes the seeded 10% judgment audit sample.
- eval/empty_pool_queries.csv: the **five queries with no observed source URLs**.
- eval/runs/pool-dev.jsonl: original observations and provenance fingerprints.
- eval/runs/pool-dev-blinded.json: provider/rank-blinded evidence.

Review a copy, using eval/RUBRIC.md. Fill human_grade (0–3), human_rationale,
human_reviewer and reviewed_at. Complete all pool rows for a query to measure
that query. The import and metrics commands are in eval/README.md. Do not edit
sealed files. Keep source access denials and unverified facts explicit.

Five empty pools cannot be graded from missing URLs. They need reference
collection from another genuinely available source, supplied via --extra-source
with its real timestamp and observations; do not invent reference URLs:

- live-multilingual-002
- live-multilingual-003
- live-multilingual-007
- live-multilingual-020
- live-multilingual-025

### Exit gate and next action

- PASS: >=500 versioned queries, fixed 300/200 split, full dev recording,
  reproducible metrics/CIs, preserved legacy fixtures and safe review workflow.
- BLOCKED: complete pool relevance judgments and associated quality CIs; five
  empty source pools also need reference collection. The saved gate is false.
- Human action: grade captured evidence and supply references for the five empty
  pools. Until then do not claim new retrieval accuracy or begin Phase 1.

This follows win_win.md: “If any fail, keep fixing within the phase or state
exactly what blocks it. Do NOT start the next phase.” No further search changes
can be qualified against an unjudged baseline.

The installed discovery backend was started only for measurement and stopped
after capture, restoring the session's initial service state. No provider
configuration, optional models, local corpus or production search code changed.

After the gate is resolved, plan Phase 1 against these saved dev outputs:
provider health/backoff, individually measured public vertical adapters,
operator handling and conservative query variants. Leave the sealed set unused
until Phase 5.
