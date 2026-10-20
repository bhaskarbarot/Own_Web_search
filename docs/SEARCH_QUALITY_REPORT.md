# Search quality: recorded results and remaining work

2026-10-20. **No green flag. General 90% accuracy and millisecond cold responses are not established.**

The goal remains useful search for unfamiliar queries, without query-specific answers, result URLs or topic rules. The final code was frozen before measurement. All 81 recorded OwnSearch code/resource hashes still match that run. The eight later probes used new topics and did not trigger further tuning.

## What changed

| Files | Change and purpose |
|---|---|
| `ownsearch/webquery.py` | Conservative intent routing, explicit date grammar, literal identifiers and model-derived relation cues. Low-confidence news/finance guesses no longer restrict discovery. Forwarded queries preserve qualifiers, exclusions and operators. |
| `ownsearch/webproviders.py` | General discovery by default, general plus news for relevant fresh queries, one bounded missing-identifier retry, actual forwarded-query/upstream provenance and named upstream errors. |
| `ownsearch/webranking.py` | Stronger name/identifier/phrase constraints, document focus, content-gated documentation signals, modest upstream-order signal, stable original snippets and weak-result filtering. |
| `ownsearch/webfocus.py`, `webfetch.py`, `webmodels.py` | At most two focused same-origin links or one robots-declared sitemap from actual discovered pages; shared deadlines, robots policy, request and byte budgets. Child pages cannot borrow parent titles. |
| `ownsearch/coordinator.py` | Preserve a documentation seed for inspection, wait within budget for financial evidence, skip unnecessary HTML enrichment after a structured market answer, publisher-dated headlines, and abstention for property questions without a validated claim. |
| `ownsearch/cli.py` | Label extractive output as an unverified source excerpt. |
| `ownsearch/config.py`, `.env.example` | General category default; bounded 2 MB/page and 6 MB/request live fetch budgets. |
| `ownsearch/dates.py` | Duration syntax tolerates punctuation without silently treating decimal durations as integers. |
| `ownsearch/bundled.py` | Enable the already-copied Mwmbl adapter with a one-second timeout; other adapters remain bounded at two seconds. |
| `scripts/benchmark_query_md.py` | All 100 table cases, exact original query text, criteria, workflow scope, captured source batches, checkpoints, resume validation and code hashes. |
| `scripts/eval_live_web.py` | All-zero judgments count as failures, page and answer scores stay separate, incomplete/independent review and actual latency gate the verdict. |
| `tests/test_web_quality.py` | 25 offline regressions for generic mechanisms, including alternate names/identifiers rather than runtime overrides for benchmark examples. |

The existing live coordinator, Yahoo chart feed, CLI/API interfaces, safe fetcher and optional local search architecture are retained. Normal live searches do not ingest full pages into a persistent corpus. The copied SearXNG source and licenses are unchanged: all 1,007 regular upstream files match their manifest.

## Root causes found

- Uncalibrated naive Bayes guesses activated financial/news categories and hard date filters on unrelated queries.
- Broad upstream responses sometimes ignored distinctive names in verbose requests. Earlier query simplification also discarded useful qualifiers; the final forwarding preserves the complete original request.
- Incidental mentions, namesakes and generic page text could satisfy lexical coverage. Page relevance and requested entity/relation focus need stronger evidence.
- Dense SEO titles and adjacency could dominate ranking. Ranking also changed snippets between passes, altering later scores.
- An acronym missing from a snippet could reject a relevant page before inspection. Conversely, a relevant documentation host could get credit for unrelated content.
- Useful documentation links existed on retrieved root pages but were never inspected. Child-link title inheritance briefly contaminated relevance and was removed.
- A factual excerpt about another subject could be presented as the requested answer. The observed Ashoka result discussed Buddha's birthplace; that is not evidence for Ashoka's birthplace.
- Financial answers waited for unnecessary page fetching, and early general results could cancel the market provider before its bounded opportunity.
- An evaluator omitted all-zero relevance judgments, inflating reported quality. Returned-page counts also cannot measure accuracy.

## All 100 query.md cases

The final recording ran from **18:35:35 to 18:47:42 IST**. OwnSearch's response cache was disabled; upstream/provider caches are not under our control. Eight M cases test initial search retrieval only, not completed agent workflows. Ambiguous D cases do not acquire invented context.

| Recording | Cases | Queries returning pages | Median | p95 |
|---|---:|---:|---:|---:|
| Before, page fetching disabled | 100 | 63 | 970.98 ms | 3,088.11 ms |
| Initial improved discovery, page fetching disabled | 100 | 67 | 971.70 ms | 2,260.66 ms |
| Final, page fetching enabled | 100 | 92 | 6,406.54 ms | 8,262.91 ms |

**92 nonempty queries is not 92% accuracy.** Sixty-six final responses contain an answer object, mostly source excerpts; that is not 66 verified answers. The modes, source configuration and live provider availability differ, so these timings are not a controlled before/after speed comparison. CPU extraction/ranking can exceed the nominal eight-second request budget.

Evidence: [before](evaluation/full-web/before.json), [initial no-fetch pass](evaluation/full-web/after-initial.json), [final 100 cases](evaluation/full-web/after.json). Other stage files are development history, including interrupted passes, not additional independent benchmarks.

## Provisional relevance review, separate from accuracy

An AI-assisted developer review labels the first two cases in each of ten categories: **20 cases**, pooled before/final top-ten URLs and selected earlier candidates. It inspects recorded titles, short source excerpts and available extracted evidence. It is **not independent, blind, representative or a factual audit**. Current stock, prices, issue status, mathematical claims and workflow completion are not certified from snippets.

Grades: 0 unrelated/decisive constraint violated; 1 partial topic match; 2 directly relevant; 3 primary or particularly exact reference. Standard binary P@5/MRR count grade 1 as relevant. Strict P@5 below requires grade at least 2; missing positions count against the denominator.

| Metric, 20 cases | Before | Final |
|---|---:|---:|
| P@5, including partial relevance | 0.520 | 0.670 |
| Strict P@5, direct relevance | 0.390 | 0.560 |
| MRR@10, including partial relevance | 0.625 | 0.925 |
| NDCG@10, graded relevance | 0.464 | 0.748 |

The high MRR means a related page often appears early; it does not mean the complete request was answered correctly. Before/final source pools differ. These diagnostic figures do not isolate a causal ranking gain. NDCG is relative to the judged candidate pool, not every relevant internet page. Saved metric output includes bootstrap intervals and per-case judgment coverage.

Artifacts: [review labels](evaluation/full-web/review.jsonl), [metrics and release-gate reasons](evaluation/full-web/relevance-review.json). Labels explicitly set `independent_review: false`. No full-task accuracy percentage is assigned. The old local-corpus baseline (NDCG 0.750, MRR 0.736, P@5 0.172) describes another corpus/protocol and cannot be compared directly with these live figures.

## Original acceptance queries and direct answers

These are actual outputs of the final acceptance recording, not hardcoded runtime behavior.

| Query | Final observation | Time |
|---|---|---:|
| Nvidia live price | Structured Yahoo regular-market quote, explicit source time, delay and informational labels. No unrelated Python page in the top results. This is not a real-time trade feed. | 1,679.63 ms |
| Today's Trump headlines | One publisher-dated Newsweek headline from the requested day. Limited coverage, not exhaustive news. | 4,482.18 ms |
| Samrat Ashok birthplace | One weak blog result; **no direct answer**. Reliable birthplace evidence was not established. This is a coverage failure with safe abstention. | 4,927.68 ms |
| TCS 6-month analysis | Structured adjusted-close history; 125 observations, requested/returned dates and descriptive calculations retained. | 1,510.13 ms |
| Inheritance in OOPS | Nine pages including relevant educational references. The answer is an introductory excerpt, not a complete independently checked explanation. | 4,250.09 ms |
| Claude docs on MCP | Official Claude/MCP documentation appears first. URLs were discovered rather than inserted in code. | 6,552.54 ms |
| Python requests timeout parameter documentation | Official Requests root ranks first, but a third-party timeout page and an unrelated Python semaphore issue remain. **Still not satisfactory.** | 4,990.96 ms |

Financial arithmetic and timestamps were checked separately from webpage relevance. Quote change/percentage agree; a fresh bounded chart-feed request returned the same timestamp, price, symbol and currency. History return, drawdown, mean, volatility and moving averages were independently recomputed from the returned series, allowing for four-decimal output rounding. Internal checks pass. This is source consistency and arithmetic verification, not an independent market audit. Weekday coverage does not model exchange holidays.

Earlier same-mode development probes took 3,958.10 ms for the quote and 5,176.61 ms for history. The final observations above are faster after skipping HTML enrichment, but source timing also varies; no general speedup guarantee follows.

Nonfinancial source excerpts have no verified-answer accuracy labels. Publisher timestamps alone do not prove headline truth. Ashoka's birthplace is intentionally not inferred from a questionable passage or assumed from Wikidata.

Artifacts: [acceptance outputs](evaluation/full-web/priority-verified.json), [separate answer checks](evaluation/full-web/answer-validation.json).

## New topics outside the benchmark

After freezing code, eight new probes covered rainbows, audio formats, plant propagation, Cargo documentation, tides, Timbuktu manuscripts, origami and camera aperture. Seven returned pages; Cargo offline documentation returned zero. Tides surfaced NOAA references; other results included varying-quality guides. These observations were retained without changing code to fit them.

Median was **5,163.56 ms**, p95 **6,266.01 ms**. Four responses had source excerpts; none is counted as an independently verified answer. Mobile and desktop duplicates also remain visible in the rainbow results. A sitting-crane variant outranked the standard crane instructions. Seven nonempty results out of eight is **not an accuracy score**. This small author-selected set is a generalization probe, not an independent holdout.

See [unseen-probes.json](evaluation/full-web/unseen-probes.json).

## Checks and reproducible commands

**244 tests passed in 47.280 seconds**, including local HTTP fixtures and 25 new regressions. Public services are not called by the regression tests. All 69 OwnSearch Python modules parse; `git diff --check` passes. Source integrity and benchmark code hashes match. The experimental provider backend on port 8889 was stopped; the configured backend on 8888 remains available.

[Test log](evaluation/full-web/tests.txt), [verification details](evaluation/full-web/verification.json).

```sh
# Keep the configured discovery backend running in one terminal:
python3 main.py discovery serve

# In another terminal, use any query, including topics outside query.md:
python3 main.py search "your new query" --answer --pretty

# Record the full table set; this calls public sources and takes minutes:
python3 scripts/benchmark_query_md.py --fetch --output /tmp/ownsearch-recording.json

# Reproduce diagnostic relevance metrics on the saved final recording:
python3 scripts/eval_live_web.py --queries docs/evaluation/full-web/review.jsonl --recorded docs/evaluation/full-web/after.json --output /tmp/ownsearch-reviewed.json

python3 -m unittest discover -s tests -t .
```

## Remaining work to reach the requested goal

1. Reliable discovery despite upstream rate limits, access denials and sparse candidate sets; general paraphrase/entity/alias understanding without requiring exact spelling or word order. Cargo and research-paper retrieval demonstrate remaining failures.
2. Stronger primary-source/official-ownership evidence and requested-facet ranking. A documentation-shaped URL does not prove official ownership; the unrelated Python issue shows lexical matching is still insufficient.
3. Verified claim extraction and useful complete answers. Current generic answers are excerpts; property questions can abstain. Reliable historical facts, current availability, issue status and comparative claims remain unverified.
4. Better cold latency and progressive useful results. The synchronous enrichment path takes seconds. Millisecond local/cache timings cannot be advertised as arbitrary live-web latency.
5. Independent multilingual, category-diverse holdout judgments for retrieval, complete tasks and direct answers, with confidence intervals. Do not tune against that holdout. The 100-case table, 20 developer reviews and eight new probes are insufficient to certify general 90% accuracy.

No query-keyed answer/URL table or example-topic regex was added to the changed runtime path. **Existing regex remains in syntax, token and date parsing. Generic lexical and structural heuristics also remain; this is not full semantic understanding.** The optional semantic/NER components are not independently qualified here. Removing syntax parsing would not solve the remaining relevance problem.

The bundled backend runs locally and preserves the upstream source, but it still depends on external indexes and Python libraries. It is not an independently indexed copy of the internet. Google/Brave/Firecrawl were not subjected to a controlled paid-API comparison; unavailable services and CAPTCHA/rate-limit errors were not bypassed or represented as successes.
