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
