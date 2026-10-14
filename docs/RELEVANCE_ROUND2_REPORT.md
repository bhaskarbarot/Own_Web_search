# OwnSearch relevance enhancement checkpoint — 2026-10-14

The existing architecture is preserved. Retrieval, entity evidence, official-source discovery, provider deadlines, and Yahoo Finance validation have changed. The full suite passes 129 tests. This checkpoint does **not** establish 90% general accuracy or warrant an overall green flag: the broader relevance benchmark regressed, general web coverage is limited, and Ashoka's birthplace is still unverified.

## Root causes and changes

| Problem | Cause found | Change |
| --- | --- | --- |
| Hundreds of weak matches | Optional phrasing words and fragmented aliases entered fallback retrieval; sparse conjunction results were supplemented with weak partial matches | Generate candidates from content terms and complete entity alternative phrases. Keep explicit OR separate. Remove partial filling; allow restricted fallback only for sufficiently covered longer, unlinked queries |
| Modi article matched Ashoka | A body mention was treated as evidence that the document concerned the entity | Require title/URL or substantial introductory and repeated entity evidence. Use source-published topic identifiers to distinguish reference pages about an entity from monuments and related entities |
| Scattered words ranked highly | Document-wide word overlap outweighed passage coherence | Apply phrase, proximity, weighted passage coverage, and relative score filtering. Inferred capitalized names receive a soft boost rather than a mandatory filter |
| Official docs missing or boosted without relevance | Discovery depended on limited roots; authority did not sufficiently reflect content and repository scope | Follow entity URL properties and reference links, prioritize roots, and inspect anchors/sitemaps. Gate authority on content matching; restrict repository authority to the relevant URL path |
| Unverified fact presented confidently | Wikidata property values were accepted without independent corroboration | Preserve references and mark current fact answers unverified. Unverified answers cannot earn a green flag |
| Financial values accepted despite incomplete input | Weak symbol matching and insufficient time/array/range checks | Preserve Yahoo lookup/chart integration, require company identity, validate positive finite prices and timestamps, history coverage/order/gaps, source timezone, adjusted closes, and calculation inputs. Retain delayed-data and informational notices |
| Long live queries | Sequential provider work and repeated cache misses accumulated latency | Shared discovery/search budget, bounded provider and knowledge timeouts, persistent source caches, early exit on useful results, bounded reranking, and actual current-request timing |
| Coverage mistaken for accuracy | Nonempty output and host judgments were insufficient evidence of correctness | Separate answer evaluation from webpage evaluation; skip unreviewed judgments and audit the complete user checklist without calling coverage accuracy |

No production query-specific answer or result URL mapping was added. Query examples, expected URLs, source identities, and synthetic documents appear in evaluation fixtures only. Calendar words and written duration numbers are parsing grammar. Existing source endpoints and the public repository user-agent contact remain source configuration.

## Files changed

- Retrieval and ranking: `ownsearch/query.py`, `ownsearch/ranking.py`, `ownsearch/engine.py`.
- Sources, discovery, caching, and deadlines: `ownsearch/knowledge.py`, `ownsearch/discover.py`, `ownsearch/live.py`, `ownsearch/config.py`.
- Financial and date handling: `ownsearch/market.py`, `ownsearch/dates.py`, new `ownsearch/resources/calendar_days.tsv`.
- Measurement: `ownsearch/evaluation.py`, new `ownsearch/answer_evaluation.py`, `scripts/check_relevance.py`, new `scripts/evaluate_acceptance.py` and `scripts/audit_query_checklist.py`.
- Tests and judgments: `tests/test_data_driven_relevance.py`, `tests/test_quality_and_providers.py`, new `tests/test_relevance_regressions.py`, `tests/relevance_hosts.json`, new acceptance/checklist/review fixtures under `tests/fixtures/`.
- Evidence: JSON reports and test log under `docs/evaluation/round2/`, plus this report.

The user-provided `query.txt` was read, not rewritten. Existing CLI answer rendering is retained; no CLI rewrite was needed. Production data and configuration were not used as mutable evaluation targets; frozen copies and live investigation indexes are under `/tmp`.

## Reproduced retrieval failures

The reproduction used the same 799-document frozen corpus and cached knowledge for both versions. The reported 798-document examples reproduce as 670 and 727 matches with the extra indexed document. Before is the starting checkout at commit `979154f`, not the much earlier checkpoint whose reported metrics were NDCG 0.750, MRR 0.736, P@5 0.172.

| Query | Before matched documents | After eligible documents | Important result |
| --- | ---: | ---: | --- |
| Nvidia live price | 6 | 2 | Planet Python removed; market service disabled in this frozen run |
| Today's Trump headlines | 106 | 2 | Broad candidates removed; dated relevant pages retained |
| Samrat Ashok birthplace | 670 | 0 | Modi removed; suitable Ashoka page absent from frozen index; fact flagged unverified |
| TCS 6-month analysis | 0 | 0 | No frozen webpage coverage; market disabled |
| Inheritance in OOPS | 727 | 0 | Pattern-matching PEPs and aggregator removed; sourced entity definition remains available |
| Claude docs on MCP | 5 | 1 | Relevant reference retained; official guides require live discovery |
| Python requests timeout parameter documentation | 19 | 2 | Still imperfect without successful linking: unrelated PEP/buildbot results remain in this frozen run |

The engine now reports eligible document matches separately from retrieval candidates. A lower count alone is not proof of correctness. In particular, the frozen Requests result remains a failure even though live discovery subsequently found its official guide.

Evidence: [before](evaluation/round2/seven-before.json), [after](evaluation/round2/seven-after.json).

## Relevance metrics

| Evaluation scope | P@5 before → after | MRR@10 before → after | NDCG@10 before → after |
| --- | --- | --- | --- |
| Seven synthetic regression queries, 364 documents | 0.2571 → 0.2571 | 0.9286 → 1.0000 | 0.9473 → 1.0000 |
| Existing 50-query URL benchmark, same frozen corpus | 0.1840 → 0.1720 | 0.7333 → 0.7133 | 0.7560 → 0.7202 |
| Seven host/source-scope judgments, frozen corpus | 0.0571 → 0.0286 | 0.2857 → 0.1429 | 0.1177 → 0.0302 |

The synthetic benchmark supplies identical entity fixtures to both versions and includes 350 distracting documents. It isolates the reported regressions, not open-web accuracy. Its nine relevant documents across seven queries impose a P@5 ceiling of 9/35 = 0.2571 because missing result positions count as zero. NDCG of 1.0 here does not imply 100% general correctness.

The existing benchmark regressed. Recall@10 fell from 0.82 to 0.78; zero-result rate increased from 0.06 to 0.08. Conservative filtering loses some relevant pages, so broader ranking work remains. Host judgments also cannot distinguish a relevant biography from an unrelated page on the same host; their decline is reported rather than discarded.

Measured local benchmark latency: median 85.47 → 62.60 ms, p95 1199.37 → 937.93 ms, mean 251.19 → 172.16 ms. These runs were not a controlled production load test; cache and system conditions matter.

Evidence: [acceptance before](evaluation/round2/acceptance-before.json), [acceptance after](evaluation/round2/acceptance-after.json), [legacy before](evaluation/round2/legacy-before.json), [legacy after](evaluation/round2/legacy-after.json), [hosts before](evaluation/round2/hosts-before.json), [hosts after](evaluation/round2/hosts-after.json).

## Final live check and direct answers

The final run used an isolated index enriched during investigation, existing source caches, and an eight-second budget. These are measured **warm-run** times, not cold-start guarantees. The final run reported no provider errors; earlier investigation artifacts preserve genuine timeouts, blocks, and transient failures.

| Query | Measured time | Webpages | Answer/result observed |
| --- | ---: | ---: | --- |
| Nvidia live price | 526.98 ms | 2 | Yahoo NVDA quote with source timestamp and notice; webpages concern the company, not the price itself |
| Today's Trump headlines | 218.74 ms | 2 | Relevant publisher-dated headlines within the UTC calendar day |
| Samrat Ashok birthplace | 369.48 ms | 1 | Ashoka biography; Wikidata birthplace claim explicitly unverified |
| TCS 6-month analysis | 1357.75 ms | 0 | Yahoo TCS.NS history, 183-day request, 126 observations against 131 estimated weekdays; adjusted-close analysis |
| Inheritance in OOPS | 375.11 ms | 0 | Sourced entity definition of inheritance in object-oriented programming |
| Claude docs on MCP | 324.99 ms | 2 | Official MCP local and remote server guides with Claude content |
| Python requests timeout parameter documentation | 662.73 ms | 1 | Official Requests Quickstart timeout section |

Evidence: [canonical final live report](evaluation/round2/live-seven-final.json). Older `live-seven.json` and investigation reports are intermediate snapshots, not the final result. The canonical report correctly retains `green_flag: false`.

Answer tests assess identity, timestamps, known fixture values, history calculations, and unverified/unavailable states separately from webpage ranking. Real financial answers are source-attributed provider observations; this run is not independent price verification and does not establish a live answer-accuracy percentage. The inheritance card matches its cited source but is not a full tutorial.

An external source spot-check confirmed that the [official MCP local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers) discusses Claude Desktop and the [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/) contains timeout parameter documentation. Independent historical review did **not** establish corroboration for the birthplace claim: accessible material from [Nayanjot Lahiri's *Ashoka in Ancient India*](https://www.jstor.org/stable/j.ctvjk2w8j) and [Bihar tourism's history page](https://tourism.bihar.gov.in/en/about/bihar) did not provide sufficient independent birthplace evidence. This is not proof that the claim is false. It remains unverified, and automated cross-source fact corroboration is not implemented. A comprehensive comparison against the user's own web-search outputs remains pending; the supplied project context did not include those comparison outputs.

## Checklist coverage and remaining quality gaps

The complete `query.txt` checklist has 150 queries in 30 categories. The frozen local audit returned webpages for **51/150** queries. That is coverage, not accuracy, and says nothing about the correctness of those pages. Human judgments have not been supplied; the review template marks cases unreviewed, and evaluation does not invent an accuracy score.

Three substantial quality areas remain before considering the requested general green flag:

1. **General coverage and judged accuracy:** no general web search provider is configured; the small existing corpus is heavily weighted toward Python. Establish representative human relevance/answer judgments and improve discovery across all categories. The 90% target is unmeasured and unachieved by the evidence available.
2. **Broader ranking quality:** recover the 50-query benchmark regression, improve failed-linking fallback and long/ambiguous queries, and compare against actual user web-search outputs. Synthetic success cannot substitute for this work.
3. **Independent answer corroboration:** implement evidence-backed fact validation; retain unavailable/unverified states when proof is absent. Financial source validation and arithmetic checks do not establish independent market truth.

Operational limits also remain: cold provider failures may consume the configured budget; source blocks cannot be made successful by local code; today's boundary currently uses UTC rather than the user's local timezone; financial coverage uses a weekday estimate without exchange holiday calendars. An eight-second budget bounds discovery work but is not a hard operating-system cancellation guarantee for every underlying operation or load condition.

Evidence: [category audit](evaluation/round2/category-audit.json), `tests/fixtures/daily_search_qrels.review.json`.

## Tests and reproduction

`python3 -m unittest discover -s tests -t .` passed **129 tests in 11.671 seconds**. Tests isolate live providers through disabled services, fixtures, mocks, and local HTTP servers. `git diff --check` passed. [Saved test log](evaluation/round2/test-results.txt).

```bash
python3 -m unittest discover -s tests -t .
python3 scripts/evaluate_acceptance.py --output /tmp/ownsearch-acceptance.json
python3 scripts/audit_query_checklist.py --checklist query.txt --data-dir data --output /tmp/ownsearch-category-audit.json
```

For a live check, use a disposable copy of the data directory so newly discovered pages do not alter a comparison baseline:

```bash
python3 scripts/check_relevance.py --data-dir /tmp/ownsearch-round2-live --live --budget 8 --output /tmp/ownsearch-live-check.json
```

Live results and timings will change with source data, availability, and cache state. Review the answers and passages rather than treating test success or a nonempty result as a green flag.
