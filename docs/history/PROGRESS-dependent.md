# OwnSearch quality improvement handoff

Date: 2026-10-21, Asia/Kolkata. Instructions: win_win.md and AGENTS.md.

## Ordered roadmap and gates

| Phase | Work | Required evidence before advancing |
| --- | --- | --- |
| 0 (awaiting review) | Freeze baseline, dataset, split, judging and metrics | Reproducible dev recording and judged quality measurements with CIs |
| 1 (in progress) | Provider resilience, intent-safe vertical discovery, operators, query variants | Lower zero-result rate, better pooled recall, no strict P@5 regression, failure-injection pass |
| 2 (snippet component retained; remaining work deferred) | URL deduplication, passage relevance, trust signals, entity focus, snippets | Better strict P@5/NDCG, reduced duplicates and broken snippets, component ablations |
| 3 (pending) | Profile, progressive delivery, deadlines and bounded freshness-aware caching | Cold/warm latency measurements and unchanged quality within uncertainty |
| 4 (pending) | Evidence-grounded claims, conflict handling and abstention | Citation support, answer correctness and unsupported-claim measurements |
| 5 (sealed, pending) | Once-only baseline/final holdout comparison; no code changes | Full saved report, uncertainty, limitations and human review |

This is the original execution order from win_win.md. On 2026-10-21 the user
explicitly requested starting Phase 2; its initial presentation work is recorded
below. Phase 0 and Phase 1 gates remain unresolved, not implicitly passed. Numeric targets are goals,
never claims about unmeasured performance.

## Current phase and preserved baseline

**Current: Phase 1 implementation/evaluation complete; quality gate pending human grades.**
Runtime 5709c59 stayed fixed throughout the complete 300-dev/30-repeat capture.
All 303 release regressions pass. Two-source failure injection passes, with all
300 frozen-source ranked URL signatures preserved. New account search adapters
were removed; unhelpful query variants were measured and reverted.

The free/keyless candidate lowered empty queries (excluding 13 nonexistent
controls) from 81/287 = 28.22% to 68/287 = 23.69%. Paired change −4.53 percentage
points, 95% CI [−8.36, −1.05]. It gained 21 cases and lost 8. Cold median changed
5.116 → 5.264 s, p95 8.035 → 8.054 s. These are temporally separate live runs,
not causal relevance proof. API supplements remain opt-in in persistent config.

Current review: eval/runs/phase1/review-with-references/human_review_queue.csv
(6,931 pairs), starting sample human_review_candidates.csv (694 pairs), and
reference_candidates.csv (4 observed, ungraded candidates for three previously
empty non-control pools). The first 6,927-pair snapshot in review/ is preserved.
No grades were fabricated; search observations are not full-page fetch successes.
Read docs/PHASE1_REPORT.md and comparison-with-references.json in eval/runs/phase1 for full results,
source contributions, limitations, commands and phase gate.

Retain the verified Phase 2 snippet component and defer further ranking work.
The user requested autonomous work through the hierarchy, without routine
confirmation stops. Earlier judgments remain missing and are never invented.

Historical Phase 2 start: Its first rendering
component is implemented and measured below. Phase 0 still awaits human grades
and five reference pools; at that historical point Phase 1 had not been executed. Do not infer that the
missing gates passed, or advance to Phase 3. See docs/plan/phase-2.md.

At the Phase 0 handoff the engine was unchanged. The retained Phase 2 component changes only snippet
presentation in snippet.py, webmodels.py and its coordinator call. The Phase 0
source manifest below is a historical snapshot, not a claim about the current
engine. Baseline data, review CSVs and the sealed split remain unchanged.

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
after capture, restoring the session's initial service state. During Phase 0 no provider
configuration, optional models, local corpus or production search code changed.

After the gate is resolved, plan Phase 1 against these saved dev outputs:
provider health/backoff, individually measured public vertical adapters,
operator handling and conservative query variants. Leave the sealed set unused
until Phase 5.


## Phase 2, step 1 — query-aware snippet boundaries

Date: 2026-10-21 (Asia/Kolkata). Starting code commit: 7012277.
User instruction: “great now start phase 2 ok”. This authorizes starting Phase 2
before the earlier gates; it does not supply missing judgments or Phase 1 scores.

### Change and scope

The confirmed defect was a fixed [:600] slice in WebCandidate.result. On the
recorded dev cases it cut 74 snippets between source word characters. Added
sentence_excerpt in ownsearch/snippet.py and applied it at that rendering point.
The coordinator forwards analyzed query terms so a short complete sentence does
not remove complete query-word matches in a longer following sentence. A whole-
word fallback handles that case and long sentences; an ellipsis marks truncation.
Original source excerpts, evidence passages, scores, URLs and ranking inputs are
preserved. No discovery, URL-merging, ranking-weight, model or fetch-policy change.

A first sentence-only variant was rejected: it removed 42 complete query-word
matches that were visible before. The retained query-aware variant preserves
all 5,981 complete matches while removing the confirmed extra mid-word cuts.
The old naive lexical count was 5,983: the extra two were cut-off final words
("sale" from "sales" and "introduce" from "introduced"), not complete source
words. Both raw and complete-word diagnostics are retained, rather than hiding
the distinction.

### Recorded-dev component ablation

Replayed **all 300 dev cases**, with 1,610 returned snippets and 1,574 evidence-
backed snippets across 204 queries. This is offline **presentation replay** of
captured passages, not re-running discovery, fetching or ranking.

| Rendering component | Confirmed mid-word ends | Rate / eligible snippets | Complete query-word matches | Ends at sentence punctuation | Omitted snippets |
| --- | ---: | ---: | ---: | ---: | ---: |
| Recorded fixed-width renderer | 74 | 4.70% | 5,981 | 1,350 | 0 |
| Sentence-only variant (rejected) | 0 | 0% | 5,939 | 1,459 | 0 |
| Query-aware sentence/word renderer (retained) | 0 | 0% | 5,981 | 1,430 | 0 |

Before mid-word-end rate 95% CI: **3.61–5.92%**. After: **0–0%** on this recorded
sample. Paired rate delta: **−4.70 percentage points**, 95% CI **−5.92 to −3.61**.
Intervals resample the 204 queries with eligible evidence, 1,000 times, seed
20261021. This does not establish zero broken snippets for arbitrary live pages.

There are 116 changed snippets, 0 invalid source prefixes, 0 newly omitted
excerpts, 0 complete query-word losses in any individual changed snippet, and unchanged recorded result identities, ranks and scores. These are
rendering invariants. They are not new independently judged strict P@5/NDCG
scores, which remain null. The old and new renderers can be ablated explicitly.

Offline retrieval preservation (59 legacy synthetic cases):

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| P@5 | 0.200000 | 0.200000 | 0 |
| Recall@10 | 0.880117 | 0.880117 | 0 |
| MRR@10 | 0.947368 | 0.947368 | 0 |
| NDCG@10 | 0.914425 | 0.914425 | 0 |
| Zero-result rate | 0.084746 | 0.084746 | 0 |

**269 tests passed in 48.072 s**, including 11 new snippet/measurement regressions.
The original fixed-width failure was reproduced before the fix; its failure
log is retained. No public providers were called for this rendering step.

### Saved artifacts and reproducible commands

- eval/runs/phase2/snippets-before.json
- eval/runs/phase2/snippets-sentence-only-rejected.json
- eval/runs/phase2/snippets-after.json (query-level metrics and changed excerpts)
- eval/runs/phase2/offline-before.json and offline-final.json
- eval/runs/phase2/confirmed-failure.txt and tests-after.txt

```bash
python3 scripts/eval_phase2_snippets.py --renderer recorded --output /tmp/snippets-before.json
python3 scripts/eval_phase2_snippets.py --renderer sentence-only --output /tmp/snippets-sentence-only.json
python3 scripts/eval_phase2_snippets.py --renderer current --output /tmp/snippets-after.json
python3 eval/run_eval.py --output /tmp/legacy-after.json
python3 -m unittest discover -s tests -t .
```

The replay binds to the captured input SHA-256 and validates all run IDs against
the fixed dev split. Its output records source hashes. Renderer timing is local
observational work and must not be presented as a live latency improvement.
The saved Phase 0 raw capture, human-review CSVs and dataset hashes are unchanged.

### Phase 2 gate and next work

PASS for this component: confirmed extra mid-word endings reduced; complete query
word matches retained; no source-prefix violations or omissions on the captured
sample; all tests pass; legacy offline quality unchanged.

**Phase 2 is not complete.** Its strict P@5/NDCG improvement gate is unmeasured:
there are still no relevance judgments and no measured Phase 1 reference. The
retained change does not alter result scoring, but that does not replace the
required independent judgments for later ranking changes. Do not advance to
Phase 3.

Still pending: evidence-backed URL variant/near-page deduplication, passage BM25
ablation, structural ownership/trust prior, namesake discrimination and domain/
provider diversity. Inspection of the saved provider rows found zero tracking-
parameter examples, 17 mobile-host rows and one variant-shaped row; no confirmed
same-path mobile/desktop pair was present. Blind stripping would risk merging
different pages without a measurable dev improvement, so it was not implemented.

Passage-start truncation and provider-supplied partial excerpts remain open.
The separate --answer excerpt path is unchanged and still needs its later-phase
evidence and boundary work.
Complete original fetched bodies were not captured, so the replay cannot infer
those boundaries honestly. Sentence detection uses punctuation and word fallback,
not a language model; very long unbroken tokens produce only an ellipsis rather
than a fabricated partial identifier. No such omissions occurred in this dev run.

Human next action remains reviewing eval/human_review_queue.csv (copy first) and
collecting references for eval/empty_pool_queries.csv. Those grades are needed
to qualify scoring/selection changes and eventually evaluate the full Phase 2 gate.


## Phase 1, step 1 — provider health and request budgets

2026-10-21, Asia/Kolkata. Starting commit b02f1dd. Plan: docs/plan/phase-1.md.
The user corrected the order and requested completing all phases hierarchically;
work returns to Phase 1 without reverting the measured snippet fix.

Added per-provider budgets, failure backoff, immediate suspension on access
and rate denials, one half-open probe, Retry-After HTTP-date handling, and health
snapshots in source statuses. Late inflight successes cannot erase newer
suspensions. JSON/schema failures count toward the circuit. Budgets constrain
requests across queries; no automatic retry or alternate bypass is added.

Controlled ablation on all 300 fixed dev queries, using recorded source rows and
two injected HTTP 403 sources plus one healthy fixture (not a live benchmark):

| Measurement | Previous provider layer | Health layer |
| --- | ---: | ---: |
| HTTP attempts to the two denied sources | 6 | 2 |
| HTTP attempts to healthy recorded-source fixture | 300 | 300 |
| Ranked URL signatures | reference | identical for every dev query |
| Two-source failure-injection gate | checked | pass |

Raw evidence: eval/runs/phase1/health-ablation.json. Each denied source is now
contacted once before suspension, rather than three times. Suppressed calls have
explicit circuit_open status. Result counts in this fixture are not live accuracy.
All five legacy offline metrics are unchanged; NDCG@10 remains 0.914425, Recall@10
0.880117, P@5 0.200000, MRR@10 0.947368, zero-result rate 0.084746.

**276 tests passed in 44.953 s**, including seven new health regressions.
Artifacts: health-full-tests.txt, health-offline.json and health-ablation.json in
eval/runs/phase1/. Continue with independent adapters, one tested/measured commit
at a time. No Phase 1 quality gate has been declared passed: strict P@5 and pooled
recall still need real relevance labels. The sealed set remains unused.


### Phase 1 adapters — Wikimedia

2026-10-21, parent 3daeead. Added independent opt-in Wikipedia and Wikidata API
adapters, per-query routing, bounded vertical concurrency and honest skipped
statuses. General discovery is preserved; vertical-only configuration is not
described as a general web index. Official API contracts: docs/DISCOVERY_APIS.md.

All 300 dev IDs were considered; stable-hash probes selected two applicable
cases per API. Wikipedia: 177 eligible cases, two successful requests, 20 actual
returned URLs. Wikidata: 12 eligible cases, two successful requests, zero matches.
These are source availability measurements, not relevance judgments.

50 relevant regression tests pass; all five offline preservation metrics are
unchanged. Raw probes and tests are saved in eval/runs/phase1/. Result URLs are
read from fullurl/concepturi; missing/unsafe URLs are discarded. Revision dates
are not used as publication dates. Adapter defaults stay opt-in pending the
combined dev ablation. Continue to GitHub; no new user confirmation is required.


### Phase 1 adapter — GitHub

2026-10-21, parent a2968ef. Added opt-in public repository/issue search,
source-provided URLs, explicit open-issue qualifiers, source issue creation
timestamps, optional header-only token and provider-specific spacing/hourly
budget. Successful quota exhaustion is deferred without being called a failure;
Retry-After and rate-limit reset headers are respected.

Stable-hash probe across 300 dev IDs: 14 eligible; two successful actual API
requests returned one row. Raw output: github-live.json. Thirteen focused tests
pass (github-tests.txt); all five offline preservation scores remain unchanged
(github-offline.json). API rows are ungraded, not a claimed recall gain.
Continue to PyPI exact metadata without a confirmation stop.


### Phase 1 adapter — PyPI

2026-10-21, parent 2c0ffa0. Added independent opt-in exact-project metadata
lookup. Explicit names are validated; URLs come from returned project metadata,
not guessed package/documentation paths. Missing projects do not poison health.

All 300 dev cases considered; eight eligible. Two actual probes returned three
URLs in total, with one source error retained and one successful response.
Fifteen focused tests pass; all offline preservation metrics are unchanged.
See pypi-live.json and pypi-offline.json. No accuracy/recall inference is made
from these counts. Continue to npm.


### Phase 1 adapter — npm

2026-10-21, parent 254cabc. Added independent opt-in npm registry search.
Two of 300 fixed dev cases were applicable; actual probes recorded one error
and one successful response, with ten source-provided URLs overall. Eight
vertical-adapter tests pass and all five offline scores remain unchanged.
Source errors remain in npm-live.json. Continue to crates.io.


### Phase 1 adapter — crates.io

2026-10-21, parent 55482fd. Added independent opt-in Rust crate metadata
search using only returned documentation/home/repository URLs. Missing links
are not guessed. All 300 dev IDs considered; 2 eligible.
Actual probe statuses: error, ok;
returned URLs: 10. Nine vertical tests pass;
all offline preservation scores unchanged. See crates-live.json and
crates-offline.json. Continue to research APIs.


### Phase 1 adapter — arXiv

2026-10-21, parent 2008b66. Added safe Atom metadata discovery, real alternate
URLs, first-publication dates, single-connection pacing and bounded metadata
cache with honest source timestamps. Entity declarations are rejected.

All 300 dev IDs considered; 32 applicable. The live probe
returned rate_limited and zero results; probing
stopped when the service circuit opened. No denial was bypassed or called a
success. Fifty relevant tests pass, including Atom and source-cache regressions.
All offline preservation scores unchanged (arxiv-offline.json). arxiv-live.json
retains the actual service response error. Continue to OpenAlex alternative.
# Phase 1 adapter — OpenAlex

2026-10-21, parent fd59d16. Added independent research metadata search,
source-returned URLs, actual publication dates and bounded reconstruction of
supplied abstract words. Optional HTTPS header credentials; keyless basic calls
were verified. All 300 dev IDs considered; 32 eligible; two actual probes both
succeeded with 20 URLs total. These are availability observations, not relevance
grades. Twenty-one targeted tests pass; legacy offline scores unchanged. Quota
tests cover decimal zero and relative reset seconds. Continue to StackExchange.


### Phase 1 adapter — StackExchange

2026-10-21, parent fdb95f9. Added independent opt-in advanced question search,
source-provided links/body/publication timestamps and bounded one-minute metadata
cache. Successful-response backoff and exhausted quota suspend requests; cached
metadata retains original retrieval times. All 300 dev IDs considered; 110
eligible; two actual probes succeeded with ten URLs overall. Twenty-three
targeted tests pass; legacy offline quality metrics unchanged. No relevance
improvement is inferred. Continue to optional general APIs.


### Phase 1 optional adapter — Marginalia

2026-10-21, parent 509cb21. Added current API header-key integration and retained
returned licensing in provenance. Three schema/HTTPS/default-off tests pass;
legacy offline scores unchanged. No configured key, so no real API success or
coverage/accuracy improvement claimed. Remains disabled. Continue to Mojeek.


### Phase 1 optional adapter — Mojeek

2026-10-21, parent 2467d28. Added independent opt-in JSON adapter with HTTPS-only
credential transport, redacted body errors, and publication vs modification
date separation. Five optional-adapter tests pass; all legacy offline scores
unchanged. No key is configured; no live probe or availability claim. Storage
rights documented; source stays disabled for this capture. General adapters
complete. Continue to conservative query variants and RRF.


### User clarification — free/self-hosted scope

2026-10-21, parent e33299f. User explicitly rejects adding paid/limited account
tools and requests continuing with their own engine. Removed the newly added
Mojeek/Marginalia runtime adapters and configuration. No paid provider was called,
no account created and no credentials provisioned. Historical artifacts remain
for audit. Existing Brave compatibility remains disabled; it is not required.
Free public APIs remain independently optional and must obey external limits.
The local crawler/index and self-hosted general discovery remain the foundation.
Continue query variants/site/feed work; do not claim unlimited external service.


### Phase 1 query variants — measured and rejected for activation

2026-10-21, parent a21cfa9. Tested original + at most two conservative lexical
variants, shared worker/health budgets, original-request budget priority, preserved
operators/negation/quotes and RRF with one vote per URL per variant. Seven targeted
query tests plus eight health tests passed; complete experimental suite passed
298 tests with localhost socket access (sandbox-only run could not bind).

All 300 fixed dev frozen-source cases: nonempty 204 → 204; 48 prefixes compacted,
119 cases had variants, original text preserved in all 300. Small paired LIVE
probe: nonempty 2/4 → 2/4, with slower responses. After dispatch-priority fix,
repeat 1/4 → 1/4; upstream responses changed between probes. These counts are
not relevance/recall. There is no measured coverage gain, so runtime variant
integration was reverted per rule 7 rather than enabled by default. Full patch
saved as query-variants-experiment.patch, with raw results/tests and reproducible
probe/replay scripts (apply patch in an isolated checkout to run those scripts).

Retained an independent recorder correction: delegate adapter accepts() so live
measurements route verticals honestly. No previous result source, review CSV or
sealed query was changed. Continue site/sitemap/feed discovery; variants remain
an unresolved Phase 1 improvement, not claimed complete.


### Phase 1 focused discovery — site origins, sitemaps and feeds

2026-10-21, parent c3baf75. Added an explicit-site origin fetch target when general
discovery has no candidate for the named site; it cannot become an unfetched
result. A declared sitemap index may yield one actual same-origin child (two
maps total). Fetched HTML may supply one same-origin feed and at most two actual
entry candidates; honors nofollow and existing session robots/DNS/byte/request/
deadline checks. New feed discovery distinguishes publication from update dates.

Focused regression suite: 84 tests pass. The confirmed empty-general/site case
returns zero without the new origin path and one actually fetched declared-map
article with it (five fixture HTTP requests: robots, origin, declared index,
child, article). A declared feed yields one observed entry; no invented feed,
private link, cross-origin index recursion or unfetched-origin result is accepted.
These are deterministic contract fixtures, not live relevance measurements.
Full-dev preservation replay and complete suite are recorded alongside the live
combined capture below. Continue to provider-schema health audit and final dev run.

Focused-discovery verification complete: full suite 298 tests passed (45.662 s).
The 300-dev frozen-source preservation run retained every ranked URL signature
(204 nonempty), and two-failing-source injection passed.
Denied fixture calls 6 → 2, healthy calls 300 → 300. Legacy offline scores
remain unchanged. Fixture/preservation results do not establish live accuracy.


### Phase 1 final health audit — schema failures

2026-10-21, parent 934a702. Confirmed that HTTP-200 wrong-result-schema responses
were reset as successes before adapter validation. Moved schema/body-error checks
before health success. Four malformed fixture calls previously produced four
HTTP requests, four false successes, zero failures and a closed circuit; now
three requests produce three failures, zero successes, and the fourth is
suppressed with circuit_open. Successful-body backoff/error backoff still applies.
Timeout/unfinished statuses now retain health snapshots. Sixty-four focused tests
pass; full suite and 300-dev preservation are being recorded before source freeze.
Free-only candidate profile documented without enabling paid providers or arXiv.

Final source checks passed: 299 tests (46.104 s), all 300 frozen dev URL
signatures preserved, injected denied requests 6 → 2 with 300 healthy requests
retained. All five legacy offline retrieval scores unchanged. Runtime will now
be frozen for a complete dev capture with free/keyless supplements, with paid
providers and denied arXiv off. Query variants stay reverted. Existing baseline,
review CSVs and sealed split remain untouched.


### Phase 1 review tooling (runtime unchanged during capture)

2026-10-21, runtime 5709c59. The comparison tool compares complete matching dev
captures, reports paired bootstrap deltas, and creates a new baseline/candidate
union review directory. Existing review files are untouched. CSV import accepts
only explicit 0–3 human grades with matching evidence hashes, rationale, reviewer
and timestamp; it preserves edits and rejects stale labels. Undefined recall is
excluded rather than converted to zero. Partial judged query coverage cannot
turn the phase gate green. Four targeted review/comparison tests pass; baseline
self-comparison returns identical zero-rate CIs and a false, ungraded quality gate.
No runtime source file changed after capture began.


### Phase 1 complete capture and exact remaining gate

2026-10-21, runtime 5709c59; reporting parent 7ed8a5a. All 300 fixed dev cases and
30 warm repeats captured; 303 release tests passed (51.861 s). Source fingerprint
stayed unchanged. Baseline capture, fixed split and all original review files
retain their saved hashes (preservation-final.json). Sealed queries run: 0.

Observed zero-result rate excluding nonexistent controls: 28.223% → 23.693%.
Paired bootstrap delta −4.530 percentage points, CI [−8.362, −1.045]. All 13
nonexistent controls still abstain. There were 21 gains and 8 losses; raw cases
are saved in nonempty-changes.json. Cold p50 5115.58 → 5264.03 ms; p95
8034.89 → 8054.04 ms. Warm p50 5131.04 → 5166.56 ms; p95 8024.21 → 7890.32 ms.
OS/upstream caches and availability were uncontrolled. Do not claim an accuracy
improvement or activate the API profile from these availability counts alone.

The general source completed every cold request. Many API responses were
unfinished and discarded at the cutoff; recorded source batches can also include
late metadata. Exact statuses and raw outputs are retained. Public API denials
were not bypassed. Paid/account search integrations remain removed/disabled.

Recall@10, strict P@5 and NDCG deltas remain null: zero grades over the 6,927-pair
union pool. Three non-control pools still need actual reference URLs. New CSVs
live in eval/runs/phase1/review; original eval/human_review*.csv stay untouched.
The comparison tool imports completed CSV fields into a new output directory
without replacing human edits. Fabricated-URL audits are unmeasured; provenance
gaps are 0, which is not independent proof of URL existence.

Phase 1 gate: tests PASS, failure injection PASS, observed zero-result drop PASS;
recall improvement and strict P@5 preservation UNMEASURED; overall NOT PASSED.
Next required work is human review under eval/RUBRIC.md and the commands in
docs/PHASE1_REPORT.md. Keep working within Phase 1 after grades arrive; AGENTS.md
requires: “Do NOT start the next phase.” This is an evidence dependency, not a
request for repeated authorization. Existing Phase 2 snippet work is preserved;
further Phase 2–5 work follows the gate. The user already authorized proceeding
through the hierarchy when those prerequisites are met.


### Phase 1 reference evidence completed, grades still required

2026-10-21. Continued independent work rather than leaving the three empty
reference pools for the user to locate. Found four real external-search
observations for those three multilingual IDs. Saved short source excerpts and
exact observed URLs; Gujarati/Korean direct opens failed and are not reported
as fetched. Arabic includes Arabic/English candidates whose language adequacy
requires human review. No relevance grades assigned, no engine results changed.

Current pool: 6,931 query/URL pairs; no empty non-control pools; zero grades.
Current CSVs are in eval/runs/phase1/review-with-references/ (full queue 6,931,
starting sample 694, focused reference candidates 4). Original review/ snapshot
and eval/human_review*.csv remain unchanged. The comparison CLI now accepts
--extra-source; all 16 review/evaluation tests pass, with explicit checks that
reference supplements cannot alter recorded results or include sealed IDs.
The complete release suite remains 303 passed; runtime is unchanged since it.

Phase 1 gate remains NOT PASSED solely because required relevance comparisons
are ungraded. Use comparison-with-references.json and docs/PHASE1_REPORT.md for
the complete current handoff and CSV import command. Continue the authorized
phase hierarchy after real judgments satisfy the gate; do not substitute
nonempty/source availability counts for Recall@10 or strict P@5.
