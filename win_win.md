Part 1: Master prompt (save as AGENTS.md)
ROLE
You are a senior search-engine engineer improving OwnSearch (this repo) into a
fast, relevant, trustworthy live web search with a Brave-like experience.
Implement, test and measure. Never reply with only a plan.

MEASURED CONTEXT (docs/SEARCH_QUALITY_REPORT.md)
- 244 tests pass. Cold median 6.4 s, p95 8.26 s (page fetching blocks results).
- Strict P@5 0.56, NDCG@10 0.748, but only on 20 non-independent reviews.
- Upstream failures: Brave rate-limits, Google denies access, mwmbl times out,
  DuckDuckGo crashes. Zero-result queries exist (Cargo docs, site:/quoted queries).
- Known defects: --answer returns only excerpts; excerpts cut mid-word or from the
  wrong passage; duplicate URLs (mobile/desktop/export variants); low-trust sites
  outrank Britannica/NOAA/Wikipedia; wrong-market links; verbose queries not
  simplified; news queries return schedule pages; authoritative pages fail
  enrichment (403/timeout).
- Hardware: CPU-only desktop, no GPU. Any model must be small, optional, configurable.

HARD RULES
1. Never hardcode queries, URLs, answers, expected domains, or benchmark-specific rules.
2. Never fabricate URLs, content, citations, metrics or fetch successes.
3. Respect robots.txt, provider terms and rate limits. Do NOT bypass CAPTCHAs,
   403s, paywalls or access denials; report them honestly.
4. Keep SSRF protection, size limits, concurrency limits and request deadlines.
5. No mandatory paid APIs, no full-web crawl. Optional free-tier keys via config only.
6. Preserve working architecture unless measurements justify changing it.
7. One change at a time, measured against the baseline (ablation). Revert any
   change that does not improve the metrics or that causes regressions.
8. Add a regression test for every confirmed failure. All existing tests must pass.
9. Never claim an accuracy number that was not measured by a defined metric.
10. Never tune on the sealed test set.

WORKING PROTOCOL (every phase)
A. PLAN FIRST: inspect the code, then write docs/plan/phase-N.md containing goal,
   files to change, ordered small steps, risks, and how each step will be measured.
B. EXECUTE step by step. After each step: run tests, run the dev benchmark,
   record the delta in docs/PROGRESS.md (date, git hash, metric before/after).
C. COMMIT after every successful step with a clear message. Revert failed steps.
D. GATE: at the end of the phase, check the phase's exit criteria. If any fail,
   keep fixing within the phase or state exactly what blocks it. Do NOT start the
   next phase.
E. HANDOFF: update docs/PROGRESS.md with: done, measured results, failures,
   open issues, next phase. A fresh session must be able to continue from this file.
F. REPORT: finish with a concise report: what changed, ablation table, before/after
   numbers, remaining failures, limitations, items needing human review.
If you run low on budget, stop at a clean commit and write the handoff. Do not
skip measurement to finish more steps.
Part 2: Phase prompts (paste one at a time)
Phase 0: Baseline and evaluation set
Execute PHASE 0 per AGENTS.md. Make no search-behaviour changes.
1. Tag the current commit as baseline-v0. Record the code hash.
2. Build a versioned eval set (eval/queries.jsonl), >=500 queries, each with id,
   category, text, freshness_requirement, expected_behaviour. Cover: programming,
   documentation, news, research, business, finance, general knowledge, local,
   ambiguous, adversarial, nonexistent-entity, verbose natural-language, exact-phrase,
   site:/operator, and multilingual. Include the existing 100 benchmark cases.
3. Split 60% dev / 40% sealed test by stable hash of the id. Store the sealed
   split's IDs but do not run or inspect it until the final phase.
4. Build the judging pipeline: pool top-10 from OwnSearch plus any other available
   sources, grade 0-3 with a documented rubric (eval/RUBRIC.md) using an LLM judge
   if configured, otherwise leave unjudged. Randomly sample 10% of judgments into
   eval/human_review.csv for me to check. Label everything not independently verified.
5. Write the metrics script: Recall@10 (against the pooled reference set), NDCG@10,
   MRR, P@5, strict P@5, zero-result rate, fabricated-URL count, bootstrap 95% CIs,
   latency p50/p95/p99 for cold and warm runs separately.
6. Run the baseline on dev. Save raw outputs in eval/runs/baseline-dev.json.
EXIT GATE: eval set exists, split is fixed, baseline numbers with CIs are saved,
metrics script is reproducible with one command.
Phase 1: Discovery (largest bottleneck)
Execute PHASE 1 per AGENTS.md. Plan first.
1. Provider abstraction: health tracking, circuit breaker, per-provider backoff and
   rate-limit budget, temporary suspension of failing providers, honest per-provider
   status in output.
2. Vertical providers via official public APIs, each an independent adapter that can
   be disabled in config: Wikipedia/Wikidata, GitHub, PyPI, npm, crates.io,
   arXiv/OpenAlex, StackExchange, plus documentation sitemaps and RSS/news feeds
   discovered from real pages. Add one provider per commit and measure each.
3. Route by detected intent, but low-confidence intent must never restrict general
   discovery. General discovery is always the fallback.
4. Optional adapters, off by default: Brave Search API (free tier key), Mojeek,
   Marginalia.
5. Implement site:, "quoted phrase" and -exclusion locally by post-filtering when
   the upstream ignores them, and by querying the named site's sitemap or search
   where permitted.
6. Query rewriting: strip filler from verbose requests, generate 2-3 variants
   (keywords, entity+facet, synonym), run concurrently, merge with Reciprocal
   Rank Fusion.
EXIT GATE (dev set): zero-result rate drops versus baseline (excluding
nonexistent-entity queries), Recall@10 improves with CI reported, no regression in
strict P@5, provider-failure injection test passes (kill 2 providers, search still
returns results), all tests pass.
Phase 2: Ranking
Execute PHASE 2 per AGENTS.md. Plan first.
1. Canonicalise URLs (tracking params, trailing slash, mobile/amp/export/print
   variants) and dedupe near-identical pages.
2. Passage-level scoring (BM25 first; add a small CPU cross-encoder or embedding
   reranker only if it improves metrics and cold latency stays acceptable).
3. Combine: passage relevance, entity and phrase match, freshness only when the
   intent needs it, and a configurable domain-trust prior based on structural
   signals (official or primary ownership evidence), never topic-specific lists.
4. Distinguish namesakes and similar entities; penalise results about a different
   entity.
5. Cap results per domain; ensure no single provider dominates the final top 10.
6. Snippets: cut at sentence boundaries from the best-matching passage.
EXIT GATE (dev set): strict P@5 and NDCG@10 improve over the Phase 1 numbers with
CIs; duplicate rate and mid-word snippet rate measured and reduced; ablation table
shows each component's contribution.
Phase 3: Speed
Execute PHASE 3 per AGENTS.md. Plan first by profiling where the time goes
(provider wait, fetch, extraction, ranking) and recording the breakdown.
1. Two-stage delivery: stage 1 returns ranked snippets and vertical results fast;
   stage 2 streams enrichment and answers as they finish (NDJSON/SSE in the API,
   progressive output in the CLI).
2. Hedged requests, strict per-provider deadlines, cancel stragglers, never wait on
   the slowest provider once enough quality results exist.
3. Bounded cache with intent-based TTL: no stale news or finance served as current;
   long TTL for stable documentation; brief negative caching; show cache status
   and source timestamps.
4. Optimise fetching, parsing and dedup (connection reuse, early byte limits,
   skip enrichment when snippets suffice).
EXIT GATE: report cold and warm p50/p95/p99 separately versus baseline; quality
metrics must not drop more than the CI noise; cache correctness tests for
news/finance freshness pass.
Phase 4: Trustworthy answers
Execute PHASE 4 per AGENTS.md. Plan first.
1. Extract candidate claims from fetched passages. Label each VERIFIED (one primary
   source or >=2 independent sources), SOURCE EXCERPT, or INFERENCE, with URL and
   timestamp.
2. Show source conflicts instead of picking silently.
3. Abstain when evidence is insufficient or the passage concerns a different entity.
4. Keep price and finance answers tied to provider timestamps and delay labels.
5. Measure answer correctness and citation support separately from retrieval, on a
   dev subset judged with the documented rubric.
EXIT GATE: citation-support rate, abstention precision, and unsupported-claim rate
reported with CIs; fabricated-URL count is 0; nonexistent-entity queries abstain.
Phase 5: Final proof (only after Phases 0 to 4 pass)
Execute PHASE 5 per AGENTS.md. Do not change code in this phase.
1. Run baseline-v0 and the final code ONCE on the sealed test set.
2. Report Recall@10, NDCG@10, MRR, P@5, strict P@5 with bootstrap 95% CIs;
   answer correctness and citation support separately; zero-result rate;
   fabricated-URL count; abstention precision; cold and warm latency percentiles;
   provider-failure-injection results.
3. Compare against targets (aim for, report whatever is measured): strict P@5
   >= 0.75, NDCG@10 >= 0.80, zero-result rate < 3% excluding nonexistent-entity
   queries, fabricated URLs = 0, cold first results p50 < 1.5 s, final p95 < 4 s,
   warm p50 < 100 ms.
4. List remaining failures, limitations (including that this is not an independent
   web index), and the items in eval/human_review.csv that I must verify.
Provide reproducible commands and saved raw outputs.