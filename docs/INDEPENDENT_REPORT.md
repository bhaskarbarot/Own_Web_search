# Independent runtime report

Date: 2026-10-21, Asia/Kolkata. Branch: `Independent`.
Previous implementation preserved on `dependent`, checkpoint `489d8dc`.

## What changed

The owner requested a replacement of provider-based discovery with an independent,
cache-only crawler. The replacement removes the bundled `searxxxing/` engine
(995 tracked files), search adapters, optional external knowledge/market API paths,
service bootstrap and the SQLite/document-index runtime. The first replacement
commit `94b4c6c` records 1,083 tracked deletions in total; see
[INDEPENDENT_REMOVALS.md](INDEPENDENT_REMOVALS.md). Historical captures, human-review
CSVs, the sealed dataset and ignored user data remain preserved.

The active path is query parsing → real starting URLs → robots-aware direct fetch
→ observed links/sitemaps/feeds → extraction → lexical ranking/filters → fetched
source excerpt with citation or abstention. Pages and discovered links are cached
only in bounded memory. There is no external search-engine fallback or mandatory
package installation. Starting sites are editable configuration in `sources.txt`,
chosen from the owner's requested Wikipedia/news/Python/Stack Overflow categories.

The CLI, HTTP API, launcher and HTML controls use this runtime. Filters include
site, phrases/exclusions, language, publication dates/freshness and actual content
file types. Images/video derive from fetched-page metadata. PDF/Office extraction
runs in a bounded subprocess. Access denials, unfinished work, resource limits,
source provenance and cache age remain visible.

## Measured changes

| Component / scope | Before | After |
| --- | --- | --- |
| Search-provider integrations in active runtime | Metasearch discovery | Removed |
| Query-time document persistence | Optional legacy SQLite/index | No document files; memory only |
| Two-page navigation fixture finds tutorial | No | Yes, from observed link |
| Version-only documentation title fixture | Relevant 0, unrelated 0 | Relevant 1, unrelated 0 |
| Three oversized fixture targets, 700-byte budget | All 3 requested | 2 requested; charged bytes ≤700 |
| Cache-only fixture p50 | 44.867 ms | 6.091 ms in final run |
| Cache-only fixture p95 | 47.085 ms | 7.684 ms in final run |
| Cache-only network requests | 0 | 0 |
| Same 11-case fixture mean Recall@10, 9 positive cases | 1.000 | 1.000 |
| Same fixture strict P@5, all 11 cases | 0.23636 | 0.23636 |

Fixture precision always uses denominator five, including short result lists.
Fixture recall uses known positive fixture URLs, not human labels. Both negative
controls pass and all warm ranked URL signatures are preserved. Test crawl delay
is zero: these timings must not be presented as cold public-web latency or live
accuracy. Full per-case measurements and runtime fingerprint are in
`eval/runs/independent/fixture-final.json`; ablations are saved alongside it.

## Validation

- 95 tests pass normally; the same 95 pass with `python3 -S`, which disables
  installed site-packages. Twenty-six original extraction/snippet regressions
  remain. Obsolete provider/index suites are archived on `dependent`; these are
  not the old 303 tests.
- UI → API → real fixture HTTP → ranked/cited output tested, including auth,
  malformed input, cross-origin/Host protections, SSRF/DNS checks, robots,
  request/byte/depth limits, cancellation and late-result exclusion.
- All 300 DEV queries parse; dev/split/original human-review fingerprints match
  `dependent`. No sealed query text was used. CSV grades were not invented.
- The UI JavaScript passes `node --check`; launcher passes `bash -n`.
- Actual launcher serves `/ui` with HTTP 200 at `http://127.0.0.1:8765/ui`.
  `/health` reports `OwnSearch 2.0.0`, `mode: independent`, `database: false`.
  A real API cache-only request records zero network attempts.

## Public observations and limits

One direct Python tutorial probe returned zero ranked results initially. After
query-qualifier link prioritization it fetched and returned the actual tutorial
page in 5,081.941 ms under the same six-second/five-page budget. These probes
occurred at different times and are not an accuracy or controlled latency study.

A separate starting-page probe fetched six of seven configured targets: Wikipedia,
Python, BBC pages/feed and Guardian feed. Stack Overflow `/questions` was blocked
by robots and was not requested. This does not establish domain-wide access or
query relevance. Raw observations are in `public-starting-sites.json`.

Independence removes search-provider quotas; it does not remove website access
rules, network latency or machine capacity. This is bounded search across starting
sites and observed links, not an exhaustive web index. It cannot discover every
unknown page from words alone. Cold crawling takes seconds; cached fixture search
is measured in milliseconds. Memory cache disappears on restart. Some queries will
return few or no results, and no live relevance accuracy improvement is claimed.
Answers are source excerpts, not independently verified facts or guaranteed truth.

## Gate and next work

Independent-runtime acceptance passes: no provider/database path, direct discovery,
controlled extraction/ranking/filtering, bounded fetching, standard-library startup,
regressions and reproducible measurements. The old human-judged quality gate remains
unresolved; it was not passed by changing architecture. Further quality work needs
broader measured source coverage, a new independent-engine DEV capture and real
relevance grades. The original CSV review material is unchanged.

Reproduce:

```bash
python3 -m unittest discover -s tests -q
python3 -S -m unittest discover -s tests -q
python3 benchmark.py --output /tmp/independent-new-measurement.json
python3 scripts/probe_independent.py --output /tmp/independent-sites-new.json
```

Public probes require network access and respect denial/cooldown. Do not overwrite
prior captures. Research sources and ordered implementation steps are in
[plan/phase-independent-1.md](plan/phase-independent-1.md).
