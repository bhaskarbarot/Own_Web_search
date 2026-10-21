# Phase 1 discovery report

Current implementation: 5709c59. Date: 2026-10-21, Asia/Kolkata.
Complete: 300 live DEV queries plus 30 warm repeats. Phase gate remains pending
human relevance judgments; no accuracy improvement is claimed.

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

The complete release regression suite passes 303 tests. The separate legacy
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

Runtime 5709c59 stayed unchanged throughout capture. The free/keyless profile
enabled github,pypi,npm,crates,openalex,stackexchange,wikipedia, with at most three
eligible verticals per query. Paid sources and denied arXiv were off.

| Metric | Baseline | Free/keyless candidate |
| --- | --- | --- |
| Nonempty queries | 206/300 | 219/300 |
| Zero-result rate, excluding 13 nonexistent controls (95% CI) | 28.22% [23.34, 33.81] | 23.69% [18.82, 29.27] |
| Zero-result rate, all 300 queries | 31.33% [26.00, 36.67] | 27.00% [21.33, 32.33] |
| cold p50 | 5.116 s | 5.264 s |
| cold p95 | 8.035 s | 8.054 s |
| cold p99 | 8.250 s | 8.456 s |
| warm p50 | 5.131 s | 5.167 s |
| warm p95 | 8.024 s | 7.890 s |
| warm p99 | 8.402 s | 8.053 s |
| Recall@10 / strict P@5 / NDCG | Unjudged | Unjudged |

Paired zero-rate change excluding nonexistent controls: -4.53
percentage points, bootstrap 95% CI [-8.36, -1.05].
The candidate gained results on 21 queries and lost results on 8, for 13
additional nonempty queries overall. Both captures abstained on all 13 explicit
nonexistent-entity controls. Full raw outputs and the lost/gained cases are saved
in eval/runs/phase1; these counts are not relevance/answer accuracy.

Captures occurred at different times. Upstream availability, page changes and
uncontrolled upstream/OS caches are confounds; the paired CI does not remove
those confounds. Cold median increased rather than improved. API supplements
remain opt-in, and the candidate profile was not activated in persistent config.
Provider-health and declared-site/feed improvements remain in the normal path.

Recorded source metadata and top-10 contributions (a result can have multiple
contributors; batches can include late responses discarded by the coordinator):

| Source | Recorded successful batches | Source URL rows | Top-10 contributions |
| --- | --- | --- | --- |
| searxng | 300 | 5814 | 1553 |
| wikipedia | 168 | 1287 | 83 |
| github | 13 | 36 | 1 |
| pypi | 7 | 13 | 0 |
| npm | 0 | 0 | 0 |
| crates | 2 | 10 | 0 |
| openalex | 27 | 253 | 33 |
| stackexchange | 108 | 168 | 21 |

Raw general discovery succeeded on all 300 cold requests. Some API responses
were late/unfinished and ignored in ranking; exact statuses remain in the raw
capture. The comparison's fabricated-URL audit count is unmeasured, while source
provenance gaps are 0. Provenance is not an independent URL audit.

## Phase gate and handoff

- Passed: all 303 tests; two-source failure injection; complete fixed-dev capture;
  lower observed zero-result rate; preserved baseline/split/review fingerprints.
- Pending: graded pooled Recall@10 improvement with CI and strict P@5 preservation.
  There are 6,931 pooled query/URL pairs and zero human grades.
- The union review queue is eval/runs/phase1/review-with-references/human_review_queue.csv; its
  deterministic 10% starting sample is human_review_candidates.csv (694 rows).
  Four externally observed reference candidates fill the three formerly empty
  non-control pools. Review reference_candidates.csv explicitly; these are
  search snippets, not asserted successful full-page fetches or assigned grades.
- Query variants remain rejected after no measured gain; arXiv stays disabled
  after the recorded 429. Newly added account adapters were removed; existing
  Brave compatibility stays disabled.
- Keep Phase 1 active until the quality gate is resolved. Preserve the previous
  Phase 2 snippet fix; further Phase 2–5 work follows the ordered AGENTS.md gate.
  The sealed 200 queries remain unused.

## Reproduction and human review

Run regressions and preservation without public network (the complete test suite
uses localhost HTTP servers):

```bash
python3 -m unittest discover -s tests -q
python3 scripts/eval_phase1_health.py --output /tmp/phase1-health.json
python3 scripts/eval_phase1_schema_health.py --output /tmp/phase1-schema.json
python3 eval/run_eval.py --output /tmp/phase1-offline.json
```

The actual live candidate command (backend already installed and running):

```bash
OWNSEARCH_VERTICAL_PROVIDERS=github,pypi,npm,crates,openalex,stackexchange,wikipedia OWNSEARCH_BRAVE_API_KEY= python3 eval/live_eval.py record --output eval/runs/phase1/dev-free-candidate.json
```

A resumed capture must use the same runtime fingerprint, provider configuration
and protocol. Preserve recordings; choose a new output for a fresh run.

After complete capture, build a separate union pool and report:

```bash
python3 scripts/eval_phase1_compare.py --candidate eval/runs/phase1/dev-free-candidate.json --extra-source eval/runs/phase1/reference-candidates.jsonl --output /tmp/phase1-comparison.json --review-dir /tmp/phase1-review
```

Fill human_grade (0–3), human_rationale, human_reviewer and reviewed_at in the new
review queue. Apply eval/RUBRIC.md; leave unknown relevance blank. Recompute using
a new directory so edited CSVs and earlier evidence remain intact:

```bash
python3 scripts/eval_phase1_compare.py --candidate eval/runs/phase1/dev-free-candidate.json --extra-source eval/runs/phase1/reference-candidates.jsonl --review-csv eval/runs/phase1/review-with-references/human_review_queue.csv --output /tmp/phase1-reviewed-comparison.json --review-dir /tmp/phase1-reviewed-pool
```

Only add --independent-review for a reviewer independent of development. Existing
eval/human_review*.csv files were not regenerated by this process.

For the rejected variant experiment, create an isolated checkout of c3baf75 and
apply eval/runs/phase1/query-variants-experiment.patch there. Then run the saved
eval_phase1_variants.py or probe_query_variants.py scripts. The live probe needs
the same authorized local SearXNG configuration. The experiment is not installed
in the active runtime.


## Reference supplement provenance

The original 6,927-row review snapshot is preserved in review/. The current
review-with-references/ snapshot adds four ungraded candidates to fill three
empty multilingual pools. These are separate external search observations, not
engine retrieval successes, and do not change any coverage/latency figure.
Their exact URLs, short source excerpts and limitations are saved in
reference-candidates.jsonl. No reference was injected into runtime routing or
returned results, and sealed IDs cannot be supplemented.

- Gujarati water-storage query: a [government agricultural training PDF](https://www.manage.gov.in/nf/studymaterials/KrishiSakhis/Krishi%20Sakhi%205day%20material/Krishi%20Sakhi%20Material-%20Gujarati.pdf) observed in search; direct web-tool opening timed out.
- Korean tides query: an [NGII page](https://www.ngii.go.kr/vlbi/02/05/) observed in search; direct web-tool opening returned a fetch error.
- Arabic tides query: an [Arabic Saudi Press Agency item](https://www.spa.gov.sa/N2208079) and [English NOAA tutorial](https://cdn.oceanservice.noaa.gov/oceanserviceprod/education/tutorial_tides/lessons/tides_tutorial.pdf) observed in search. Judge topic coverage and language adequacy; no grade is assumed.

Sixteen evaluation/review tests and an explicit fixture supplement-safety check
pass after adding --extra-source: supplements affect only the review pool and
reject sealed/unknown IDs. The 303-test release suite predates only this small
reporting option; the frozen runtime did not change.
