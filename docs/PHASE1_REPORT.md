# Phase 1 discovery report

Current implementation: 5709c59. Date: 2026-10-21, Asia/Kolkata.
The combined 300-query live DEV capture is in progress; no phase gate is passed.

## Scope and ownership

The active path uses owned OwnSearch code and self-hosted general discovery.
New account-based Mojeek/Marginalia adapters were removed at the user's request.
Existing Brave compatibility remains disabled. Basic free official APIs are
independent optional supplements, not paid requirements or an unlimited index.
External API/site limits and access denials remain binding.

## Retained components and ablations

| Component | Before | After | Evidence scope |
| --- | --- | --- | --- |
| Repeated denied sources | 6 fixture requests | 2 fixture requests | All 300 dev source replays, 300 healthy calls retained |
| Two-source failure injection | Working source retained | Working source retained | All ranked URL signatures identical |
| Wrong API schema | 4 calls, 4 false health successes | 3 failures, then circuit_open | Four HTTP-200 schema fixtures |
| Explicit site with empty general discovery | 0 results | 1 fetched article | Declared sitemap-index fixture, 5 HTTP requests |
| Query variants | 204/300 nonempty frozen-source replay | 204/300 | No new source retrieval; runtime change reverted |
| Query variants live probe | 2/4 nonempty | 2/4, slower | Small paired sample; priority-fix repeat 1/4 → 1/4 |

The query-variant experiment did not justify activation. Its bounded concurrency,
original-query priority, lexical preservation and RRF implementation are retained
only as an auditable patch under eval/runs/phase1/query-variants-experiment.patch.
No guessed synonyms were introduced. The running path was restored.

The complete final regression suite passes 299 tests. The separate legacy
59-case fixture benchmark remains P@5 0.200000, Recall@10 0.880117,
MRR@10 0.947368, NDCG@10 0.914425, zero-result rate 0.084746.
These are preservation figures, not live search accuracy.

## Independent official-API observations

Each probe considered all 300 fixed dev cases, then attempted at most two
stable-hash-selected eligible cases. Counts below are availability/metadata
observations, not relevance judgments or full dev API coverage.

| Source | Eligible | Attempted | Actual statuses | Returned URL rows |
| --- | --- | --- | --- | --- |
| wikipedia | 177 | 2 | ok, ok | 20 |
| wikidata | 12 | 2 | ok, ok | 0 |
| github | 14 | 2 | ok, ok | 1 |
| pypi | 8 | 2 | error, ok | 3 |
| npm | 2 | 2 | error, ok | 10 |
| crates | 2 | 2 | error, ok | 10 |
| arxiv | 32 | 1 | rate_limited | 0 |
| openalex | 32 | 2 | ok, ok | 20 |
| stackexchange | 110 | 2 | ok, ok | 10 |

arXiv probing stopped on HTTP 429; the source stays disabled. Wikidata's small
probe returned no rows, so it is also excluded from the candidate profile.
General discovery remains eligible regardless of uncertain vertical intent.

## Combined live evaluation

Pending complete capture at eval/runs/phase1/dev-free-candidate.json.
The code is frozen during capture. The profile enables github,pypi,npm,crates,
openalex,stackexchange,wikipedia with at most three eligible verticals per query.
Paid sources and arXiv are off. Original requests and page deadlines are retained.
No relevance grades are manufactured. The existing human-review CSVs stay intact;
a separate union pool and review queue will be created after the capture.

## Remaining phase gate

Human relevance judgments are absent. Pooled Recall@10, strict P@5, NDCG and
quality confidence intervals therefore remain unavailable. Live nonempty counts
and API rows cannot replace those judgments. Further Phase 2 work and the sealed
Phase 5 run remain deferred under the ordered phase gate in AGENTS.md. The
previous measured Phase 2 snippet fix remains preserved.
