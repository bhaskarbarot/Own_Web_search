# OwnSearch implementation and verification report — 2026-10-20

The implementation continues on `wip/data-driven-relevance`; the crawler, SQLite store, segmented BM25F index, CLI and API architecture remain intact. The user authorized continuing through the plan's remaining stages without stopping after each checkpoint.

**The implementation and regression checks are complete for the base/fallback paths described below. An overall green flag and 90% open-web accuracy are not established.** The historical birthplace claim is uncorroborated. Optional model paths remain disabled and have not demonstrated a measured gain. Larger independent language/crawl evaluations remain necessary.

## Root causes addressed

- Matching discarded Unicode distinctions and did not retain an unfolded positional field. Preserve originals separately, share folding between queries and documents, and enforce literal quoted phrases through exact postings. Accent/compatibility-character and legacy mixed-segment regressions cover this contract.
- Partial word matches and incidental entity mentions could substitute for document relevance. Keep conservative AND/rare-term retrieval, reject weak docs titles, match complete entity aliases, and abstain on ambiguous local labels instead of splitting an ambiguous multiword name into unrelated shorter entities. Resolve ambiguity from source descriptions/property labels where available.
- A company name was sufficient for a financial webpage to rank. Require learned financial intent in its title; the timestamped direct Yahoo answer remains independent. Company profiles and Python SDK manuals no longer fill a price query's result list.
- A relevant encyclopedia page could prevent official documentation discovery. Continue until a matching source-declared docs scope is found, and report unverified official status when it is unavailable. Source URLs come from Wikidata, verified reference-page links and public package metadata. No example-query URLs or answers were added to runtime logic.
- Documentation discovery spent its budget on additional roots and sitemaps after obtaining candidate links. Fetch those candidates earlier, retaining sitemap fallback. Provider waits, DNS, network reads, frontier growth, nested sitemaps and decoded-response bytes have independent bounds. API page discovery runs in bounded background jobs; CLI explicitly waits within its live budget.
- Full body scans were used for spelling vocabulary, and metadata-only changes were not indexed. Read vocabulary from index terms, use bounded legacy fallback scans, and advance document sequence numbers for language/date/metadata changes.

## Implementation by plan stage

| Stage | Delivered | Evidence / limits |
| --- | --- | --- |
| 2 — normalization | Unicode folding/exact forms; regex graphemes with standard-library fallback; stopwordsiso keyword scoring; n-gram field | Hindi/Gujarati/CJK/Thai/Turkish/Arabic/nukta/joiner/ligature tests. Installed stopwordsiso supplies 225 Hindi and 224 Gujarati words. Original stored content retained for new ingestions. |
| 3 — relevance | Exact positional matching, exact-title and low-weight n-gram features, conservative fallback, source/name constraints | Similar-name, incidental-entity, phrase and seven-query regressions pass. Old six-field segments and mixed merges remain readable. |
| 4 — spelling | Index-derived deletion vocabulary, edit-distance alternatives, original query retained | Quoted text/code/URLs/numbers/linked entities protected. Vocabulary is deadline-bounded; very large vocabularies can be incomplete rather than block a query. |
| 5 — languages | Script evidence, explicit language/weighted Accept-Language prior, BCP-style tags, same-language boost, optional configured Lingua detector | Cross-language pages are not silently filtered. Short-script ambiguities are reported. This is not a language-support certification. |
| 6 — romanization | Rule-based Devanagari/Gujarati phonetic field and cautious alternatives | Romanized-language fixture metrics reported separately. No translation claim. ai4bharat installation dependency resolution succeeded but requested large GPU dependencies; actual installation/model execution was not performed. |
| 7 — entities/intent | SQLite FTS label/alias import, cached-record migration, typed masking shared with seed extraction, English NB margin interface, optional background ONNX intent adapter | Remote Wikimedia is opt-in. Non-English base intent falls back to general. Calibrator writes a per-language table from supplied held-out labels; no unmeasured calibration is shipped as accurate. |
| 8 — temporal | Guarded lazy dateparser, calendar fallback, explicit IANA timezone, ambiguous Hindi day windows, optional named-holiday lookup from library data | en/hi/gu, false-positive words, invalid timezone and DST-day regressions. Country must be explicit for holiday lookup. |
| 9 — crawl/discovery | Independent budgets, safe pinned connections/DNS deadlines, structured feeds, bounded health audit, background API discovery | Existing SSRF/robots/trap/dedup tests retained. Feed language validation is syntactic, not a complete IANA registry check. Byte budget counts decoded response bodies, not network headers or failed downloads. |
| 10 — providers | Bounded concurrent optional SearXNG retrieval and local retrieval, canonical RRF and provenance | Timeout/error/dedup/local-only tests. No public full-web search service is silently enabled. Yahoo/PyPI/Wikimedia are distinct configured data integrations. |
| 11 — output | Real content snippets, structured highlight offsets, source/crawl status, direct answers and spelling messages preserved | Financial/factual answer assessment is separate from page ranking. Matched-document counts refer to eligible retrieved candidates, not the whole web. |
| 12 — plugins | Local ONNX/e5 + offline FAISS builder, model/index generation guard, bounded CPU reranker, local Argos translation and spaCy NER adapters | Off by default; missing packages/models retain core results. No full-model gain, quantization, GPU throughput or language coverage is claimed. |
| 13 — evaluation/setup | Paired bootstrap comparisons, base/full requirements, wheel packaging, setup script, existing-corpus benchmark and public TREC import | MIRACL topics/qrels downloaded with checksums. Full public passage corpora and 50 independently judged queries per claimed language have not been evaluated. No new language is certified. |

## Relevance measurements

Same 57 synthetic documents and 59 development queries as the Step 1 baseline; corpus/query hashes must agree. Two expected-empty cases are excluded from ranking means. Precision@5 always divides by five; its fixture ceiling is 0.2421. These judgments are not an independent internet benchmark.

| Metric | Before | After | After 95% query-bootstrap CI | Paired delta 95% CI |
| --- | ---: | ---: | --- | --- |
| p@5 | 0.1895 | 0.2000 | [0.185965, 0.217544] | [0.0, 0.024561] |
| recall@10 | 0.8363 | 0.8801 | [0.807018, 0.944444] | [0.0, 0.105263] |
| mrr@10 | 0.8947 | 0.9474 | [0.894298, 1.0] | [0.0, 0.122807] |
| ndcg@10 | 0.8648 | 0.9144 | [0.846799, 0.969706] | [0.000775, 0.11238] |
| zero_result_rate | 0.1356 | 0.0847 | [0.016949, 0.169492] | [-0.118644, 0.0] |

| Query language | Cases | After MRR@10 | After NDCG@10 | NDCG 95% CI |
| --- | ---: | ---: | ---: | --- |
| en | 49 | 0.9787 | 0.9478 | [0.88704, 0.990947] |
| gu | 3 | 1.0000 | 0.9291 | [0.787155, 1.0] |
| hi | 3 | 1.0000 | 1.0000 | [1.0, 1.0] |
| hi-Latn | 4 | 0.5000 | 0.4468 | [0.0, 0.893577] |

Both intended empty cases still abstain. The seven-query adversarial fixture retains MRR@10 1.0000 and NDCG@10 1.0000; P@5 is 0.2571 because most queries have fewer than five relevant fixture pages. See `eval/upgrade-seven-before.json` and `eval/upgrade-seven-after.json`. The historical host-level 0.750/0.736/0.172 baseline belongs to different judgments and is not substituted into this comparison.

Reports: `eval/upgrade-after.json`, `eval/upgrade-stdlib.json`, `eval/upgrade-comparison.json`. Narrow fixture gains do not establish 90% accuracy across user categories.

## Real query checks

`eval/live-before.json` captures the earlier code against a temporary copy of the 821-document corpus. Subsequent isolated runs drove additional fixes; `eval/live-final.json` is the last run with warm caches and newly discovered pages. Live timings are actual and are not a controlled before/after performance experiment.

| Query | Last observed result | Assessment |
| --- | --- | --- |
| Nvidia live price | Timestamped NVDA regular-market quote; no unrelated profile/SDK filler pages | Source identity, price, currency and timestamp match captured primary chart data. It is the latest regular-market quote, not a promise of an immediate trade price. |
| Today's Trump headlines | Four publisher-dated articles within the parsed day window | A small retrieved set, not an exhaustive daily-news comparison. |
| Samrat Ashok birthplace | Ashoka reference page; Wikidata claim explicitly unverified | **Not independently corroborated; no green flag for the direct historical answer.** |
| TCS six-month analysis | TCS.NS adjusted-close history, 125 sessions | Raw-series matching, range, returns, averages, drawdown and volatility independently recomputed successfully. |
| Inheritance in OOPS | Computing inheritance reference page | Relevant entity/context; no unrelated entity card presented as the answer. |
| Claude docs on MCP | Official MCP remote-server guide plus reference page | The official source is ranked first because its content matches. |
| Python Requests timeout docs | Requests Quickstart | Official source contains the timeout parameter discussion. Earlier irrelevant PEP/buildbot pages were rejected. |

Latest timings: 1140.49, 820.66, 627.98, 47.64, 766.01, 462.71 and 5856.09 ms, respectively. These include warm provider/discovery caches. Earlier failed runs include a request exceeding its eight-second target during processing; they remain in `eval/live-release-candidate.json`. Background API discovery avoids waiting for that page-processing path. Network deadlines do not preempt all Python extraction/indexing CPU work in the explicitly awaited CLI path.

`eval/market-validation.json` records primary-feed consistency checks. It does not assert independent-provider financial correctness. `scripts/validate_market_run.py` reproduces them from a captured acceptance cache. Existing market fixtures continue to test stale/future/missing data and arithmetic independently of webpage metrics.

## Web-search comparison sources

These are review sources only, never runtime query-specific URLs:

- [Yahoo NVDA quote](https://finance.yahoo.com/quote/NVDA/) and [TCS history](https://finance.yahoo.com/quote/TCS.NS/history/): identity, exchange/currency, source timestamp and regular-close context. The NVDA regular close matched the captured chart value; overnight quotes have a different session timestamp.
- [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/): the timeout parameter is documented in the official guide.
- [MCP documentation](https://modelcontextprotocol.io/) and [Anthropic MCP entry](https://docs.anthropic.com/en/docs/mcp): primary protocol/client documentation exists outside the encyclopedia.
- [Python classes and inheritance](https://docs.python.org/3/tutorial/classes.html): a primary programming-language reference for the requested concept.
- [AP Trump reporting](https://apnews.com/article/47534d721ac1328832ca46d9286ca833): search results include publication times from different days; a search-engine snippet is not proof that an article belongs in today's window.
- [Library of Congress historical record](https://www.loc.gov/item/79312482/) and [Ashoka in Ancient India](https://www.jstor.org/stable/j.ctvjk2w8j): the accessible historical-source excerpts reviewed here do not independently confirm the emitted personal birthplace claim; this is not a finding that the claimed place is false. The Lumbini inscription concerns the Buddha's birthplace and must not be substituted for Ashoka's.

## Scale and compatibility limits

The existing-corpus checkpoint benchmark used read-only SQLite backups and temporary reindexing. Production data and credentials were not copied into source control or modified. At that checkpoint, segment files grew from 8,608,059 to 20,952,524 bytes (about 2.43x). Local p95 changed from 147.22 to 181.72 ms with wide overlapping CIs; a speed improvement is **not demonstrated**. The corpus has 821 active indexed documents, not a production-scale web index. Later discovery fixes were tested live rather than relabeled as a new controlled corpus benchmark.

The tiny fixture index grows about fourfold with the added fields; exact sizes and latency CIs are recorded by the evaluator. Old segments open without rebuilding. Newly added analysis fields require an explicit reindex for existing documents; originals already discarded by old ingestion cannot be recovered without recrawling. New nine-field segments require this code version: back up the data directory before switching an index writer back to an older branch.

## Validation and files

The actual checkout passed **172 tests in 44.065 seconds**. The base profile and standard-library fallback each passed all 172; fresh one-command setup also passed 172 and the installed CLI smoke. Final validation logs are under `docs/evaluation/upgrade/`; the suite includes all prior tests plus Unicode, local entity, language/date, discovery/provider, original-text, financial-topic and mixed-segment regressions. Both the base-dependency and standard-library fallback profiles are checked. A wheel build and packaged CLI/resource smoke check are recorded separately. Heavy model execution is not included in either result.

Runtime changes: `textproc.py`, `util.py`, `segments.py`, `indexer.py`, `ranking.py`, `query.py`, `intent.py`, `knowledge.py`, `engine.py`, `store.py`, `config.py`, `fetcher.py`, `crawler.py`, `pipeline.py`, `discover.py`, `server.py`, `cli.py`; new `entities.py`, `language.py`, `spell.py`, `transliterate.py`, `temporal.py`, `fusion.py`, `snippet.py`, `feeds.py`, `background.py`, `providers/` and `plugins/`. Resources include the intent seed, structured feed registry and holiday-cue grammar. No example answer or result URL is encoded in production logic.

Tooling/tests: `benchmark.py`, `pyproject.toml`, requirements files, `scripts/setup.sh`, calibration/public-import/feed-audit/market-validation scripts, `tests/test_unicode_upgrades.py`, `tests/test_upgrade_pipeline.py`, fixture isolation in `tests/helpers.py`, and a timeout-fixture warm-up in `tests/test_relevance_regressions.py`.

## Remaining acceptance work

1. Independently corroborate factual claims or keep them explicitly unverified. Do not convert the birthplace fixture or Wikidata output into a hardcoded answer.
2. Evaluate larger disjoint public passage sets and human-reviewed web judgments, with at least 50 cases per language before making a support claim. Gujarati/romanized and cross-language gaps remain; an English-only index cannot answer native-language queries by phonetics alone.
3. Enable a local model/reranker only after obtaining its weights, checking its artifact/license and demonstrating a held-out gain within the CPU budget. The base core works without it.
4. Establish larger-corpus and sustained-load bounds, including extraction CPU and awaited CLI discovery. The current run does not prove seven-agent production capacity or a strict CPU-preemptive global timeout.

No branch merge, push, deployment, credential rotation or production-index reindex was performed. A concurrent user rename from `query.txt` to `query.md` is preserved.
