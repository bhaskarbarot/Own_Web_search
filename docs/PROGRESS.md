# OwnSearch quality improvement handoff

Date: 2026-10-21, Asia/Kolkata. Instructions: win_win.md and AGENTS.md.

## Current phase and preserved baseline

Phase 0 is in progress. No search-behaviour files have changed. Do not start
Phase 1 until the Phase 0 gate passes or its missing judgments are resolved.

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

## Step 2 — live capture and judging pipeline (in progress)

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
- Eleven evaluation regression tests pass. Full suite after this step is pending.
- Live provider observations already show Brave rate limits, Google access
  denials and DuckDuckGo timeouts; preserved without bypass or relabeling.
- The installed local discovery backend was stopped at session start. It was
  started using existing configuration for measurement; no provider config changed.

## Blocking and next work

No LLM judge credentials or configured judge adapter are available. Pool rows
must remain unjudged; relevance and fabricated-URL metrics must not be invented.
Finish the dev recording, run the metrics command, prepare review candidates,
and report the exact exit-gate failure if human/LLM judgments are still missing.
Do not inspect or execute sealed query bodies.
