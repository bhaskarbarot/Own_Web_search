# Independent progress

Date: 2026-10-21, Asia/Kolkata. Active branch: `Independent`.
Preserved previous implementation: `dependent`, checkpoint `489d8dc`.
The owner explicitly replaced metasearch with independent direct crawling.
Prior phase gates and historical measurements are preserved in
[history/PROGRESS-dependent.md](history/PROGRESS-dependent.md).

## Rebuild step 1: independent runtime baseline

Done: removed bundled `searxxxing/`, provider/API adapters and bootstrap,
legacy database/index runtime and obsolete provider/index commands. Removed the
ignored former service installation directories. Existing ignored user `data/`
contents are untouched. Added query-time direct fetching, link/sitemap/feed
traversal, shared origin robots/politeness/cooldown, bounded workers, memory caches,
lexical ranking, cited source excerpts, CLI/API and the existing HTML filters.
Starting sites were explicitly requested by the owner and live in `sources.txt`.

Validation: 84 tests pass (26 retained parser/snippet regressions plus 58 new
independent crawler/API/security tests). Obsolete provider/index suites remain on
`dependent`; this is not the old 303-test suite. Import audit finds no SQLite module.
The 300 DEV queries parse successfully; dev/split/original human-review fingerprints
are unchanged. No sealed query text was opened or used.

Controlled benchmark: `eval/runs/independent/fixture-initial.json`, runtime SHA
`d7227c61745fbab051bf20f672061e2cdf6f5c7e91fdb7961d8bcd849195dd36` (before the
additional Host/cross-site guards). 11 synthetic cases, 9 positive, 2 negative.

| Measurement | Empty memory cache | Direct crawl | Cache-only repeat |
| --- | --- | --- | --- |
| Fixture mean Recall@10, 9 positive cases | 0 | 1.000 | Same ranked URL signatures |
| Mean strict P@5, all 11 cases (denominator always 5) | 0 | 0.23636 | Same ranked URL signatures |
| p50 | Not measured for this comparison | 54.711 ms | 43.189 ms |
| p95 | Not measured for this comparison | 181.052 ms | 44.803 ms |
| Network requests on repeats | 0 | Per-case recorded | 0 |

These are controlled fixture measurements with test-only zero crawl delay, not
live search accuracy or public-web latency. Both negative controls returned no
results. Live relevance metrics remain unjudged.

Public direct probe: `eval/runs/independent/public-python-smoke-initial.json`.
6-second budget, 5 actual requests including robots, 3 completed HTML pages,
1 unfinished page excluded, 0 ranked results. It exposed query-qualifier link
priority and title-only technical-document gating problems. Do not call this a
successful live search. Fix and remeasure these problems next.

## Remaining work and limits

- Fix generic link prioritization and documentation evidence gating; ablate each.
- Remove avoidable network-client setup from cache-only searches; measure separately.
- Finish documentation/audit and run the final regression and controlled benchmark.
- Public coverage is bounded by configured origins, observed links, cache lifetime
  and query budget. No full-web index is present. Cold crawling can take seconds.
- Wikipedia/Stack Overflow/news site availability is not yet established here.
- Answers are source excerpts, not independently confirmed facts. Human relevance
  judgments are still needed; no old phase quality gate has been declared passed.
- Next phase: only after these runtime acceptance checks pass, expand measured
  source coverage and improve ranking using actual review judgments.

## Step 2: query qualifiers guide the crawl

Baseline implementation commit: `94b4c6c`. Generic link priority now includes
literal query qualifiers and URL-path evidence, rather than relying only on the
ranker's required subject terms. No query/topic/domain mapping was added.

Ablation `link-priority-ablation.json`: under the same two-page fixture budget,
the old implementation fetched a version link and missed the tutorial; the new
implementation fetches the observed tutorial link and returns it. Added a regression.
All 85 tests pass. The unchanged 11-case benchmark preserves fixture Recall@10
1.000, strict P@5 0.23636, all warm URL signatures and both negative controls.
Cold p50 58.451 ms, warm p50 44.867 ms; these small timing changes are not claimed
as improvements. See `fixture-link-priority.json` for raw per-case measurements.

Repeated public Python probe: one ranked, fetched tutorial URL, versus zero
initially; 3 actual requests, 5,081.941 ms. Both runs used the same 6-second/5-page
budget. They occurred at different times, so this is a functional observation,
not an independent relevance or controlled network latency improvement.
Raw: `public-python-link-priority.json`. Remaining attempts reported delay/deadline
errors honestly. No fabricated fetch successes or late content were admitted.

## Step 3: cache-only searches skip network-client setup

Baseline commit: `6066f49`. Cache-only requests no longer construct a TLS/network
fetch session. Ranking and result signatures are unchanged. All 85 tests pass.
Same 11-case benchmark, `fixture-cache-client.json`: warm p50 44.867 → 6.089 ms,
p95 47.085 → 7.677 ms, zero repeat network requests. Fixture Recall@10 remains
1.000 and strict P@5 0.23636. Cold p50 55.382 ms; no cold improvement claimed.
These are small controlled fixtures with test-only zero crawl delay, not a promise
of that latency for a large cache or public website. Runtime SHA recorded in JSON.

## Step 4: fetched documentation with version-only titles

Baseline `77b2ed7`. Allow an inspected technical document whose literal project
name matches its hostname and fetched body, even if its title only names a version.
Content coverage is still required; hostname alone cannot rank unrelated content.
Two-fixture ablation: relevant document returned 0 → 1, unrelated 0 → 0.
All 87 tests pass. Same 11-case benchmark preserves Recall@10 1.000, strict P@5
0.23636, both negative controls and all warm signatures. Warm p50 6.144 ms; no
additional speed claim. Evidence: `doc-title-ablation.json`, `fixture-doc-title.json`.
