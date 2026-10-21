# Phase 0 — reproducible live evaluation baseline

Date: 2026-10-21 (Asia/Kolkata)

## Goal and boundary
Freeze the current search implementation, preserve earlier evaluation fixtures, and establish a versioned development benchmark before any search-behaviour changes. Follow win_win.md and AGENTS.md. Phases 1–5 remain gated.

## Files and ordered steps
1. Record HEAD and tag it baseline-v0; run the existing regression suite and legacy offline benchmark. Save evidence under eval/runs/. Save the existing eval/queries.jsonl byte-for-byte as eval/legacy/queries.jsonl and adjust only its consumers.
2. Add eval/build_dataset.py and eval/query_topics.json with 400 diverse new authored cases plus the exact 100 query.md cases. Produce eval/queries.jsonl (v1), fixed 60/40 SHA-256-ID split, IDs and content fingerprints. Do not evaluate or tune against sealed IDs.
3. Add eval/live_eval.py for dev-only, resumable sequential cold/cache-warm capture, provenance-preserving top-ten pools, optional external source imports, supplied-judgment validation, deterministic 10% human-review sampling, and reproducible bootstrap metrics. Add eval/RUBRIC.md and evaluation regression tests.
4. Run tests and the legacy benchmark after each successful step. Run all dev cases against the configured live provider with ordinary safety limits and a pause between cold requests; checkpoint each result. Produce eval/runs/baseline-dev.json and its metrics, pooled results and review CSV.
5. Record before/after observations, gate results, blockers and reproducible commands in docs/PROGRESS.md and eval/README.md. Commit each successful step, if repository permissions permit.

## Measurement
No ranking or provider changes in Phase 0. Verify the engine fingerprint is identical throughout. Legacy metrics are an offline preservation check, not live accuracy. Live metrics: pooled Recall@10, graded NDCG@10, MRR@10, P@5 (>0), strict P@5 (>=2), zero-result rate (also excluding nonexistent-entity cases), URL-provenance violations, bootstrap 95% CIs, and separate cold/warm p50/p95/p99. Missing relevance judgments stay null, never zero or invented. Distinguish source provenance from verified URL existence and answer correctness.

## Risks and handling
- No LLM judge credentials are currently configured: leave new pool rows unjudged; prepare human review. Missing judgments may block the quality part of the exit gate.
- Sandbox denies local network access: request scoped execution for the actual benchmark; do not disable safety checks or access denials.
- Providers may be unavailable or rate-limited: retain statuses and failed measurements; do not call failures successful searches. Do not repeatedly hammer denied sources.
- Existing fixture runner expects the old query schema: preserve it under eval/legacy/ and check legacy metric equivalence.
- Cache is disabled in current config: report natural repeat timing separately from an explicitly opt-in response-cache experiment; never advertise forced cache hits as default behavior.
- Corpus is developer-authored, not independent; sealed IDs protect later tuning but cannot retroactively make authored examples independent.

## Exit gate
Versioned >=500 queries; fixed dev/sealed split; baseline dev capture with reproducible metrics and CIs; usable judging and review pipeline. Retrieval-quality numbers require actual source judgments. If no judgments or providers are available, report the exact failed gate and stop before Phase 1.
