# OwnSearch: existing architecture and baseline profile

Reviewed 2026-10-20, Step 1 of `main.md`. This maps implemented components; the architecture sketch in `main.md` also includes future work.

## Current request and ingestion paths

```text
CLI / HTTP / Python facade
  -> SearchEngine.search: parse operators, intent and requested format
  -> optional live answer/entity lookup (Yahoo / Wikidata / Wikipedia)
  -> local BM25F candidate retrieval and operator filters
  -> document aboutness, date, quality, intent and authority features
  -> positional and passage rerank, relative cutoff, diversification
  -> snippets/evidence, source errors, coverage, optional direct answer
  -> if local coverage is insufficient: bounded live discovery and local rerank

crawl / ingest / WARC
  -> persistent Frontier leases, host queues and retry state
  -> safe Fetcher, robots policy and extraction
  -> Processor: canonical identity, metadata, links and deduplication
  -> DocumentStore (SQLite, compressed bodies)
  -> Indexer: incremental field postings and positional segments
  -> IndexManager: snapshots, cache, atomic manifest, deletes and merges
```

| Area | Implemented code and limits |
| --- | --- |
| Entry points | `main.py`, `ownsearch/cli.py`, `ownsearch/server.py`, `ownsearch/engine.py`. CLI and HTTP share the facade/parser. |
| Query processing | `query.py`, `intent.py`, `textproc.py`, `dates.py`. Resource-trained naive Bayes, operators, basic script detection and Hindi stemming, calendar/duration grammar. Script heuristics are not reliable language identification. |
| Retrieval and ranking | `ranking.py` performs fielded BM25, phrase/entity candidate constraints, explicit filters and constrained partial fallback. `engine.py` applies document-level and positional/passage signals and diversification. |
| Index | `indexer.py`, `segments.py`. Fields are title, headings/description, URL, anchors, body and metadata. Text is normalized/stemmed; there is no separate unfolded exact field or n-gram/vector index yet. |
| Storage | `store.py`, `db.py`: document/links/frontier SQLite transactions, compressed text, hash/simhash and quality metadata. |
| Crawler and extraction | `crawler.py`, `frontier.py`, `pipeline.py`, `extract/`, `fetcher.py`, `robots.py`. Existing host politeness, redirect/IP checks, leases, size limits and format parsers. Independent bulk discovery/frontier budgets and forced-recovery evidence remain incomplete. |
| Live sources | `knowledge.py`: serialized and cached entity/fact lookup. `market.py`: configurable Yahoo lookup/chart with dated quote/history validation. `discover.py` and `live.py`: feeds, optional SearXNG and focused source-link discovery with shared request/deadline bounds. Providers are not concurrently fused by RRF. |
| Output | `evidence.py`, `engine.py`, `cli.py`: real-text snippets, source headings for lists, bounded passages, untrusted-content flags, source status and separate answers. Fact corroboration is still incomplete. |
| Serving | `auth.py`, `server.py`, `gateway.py`, `metrics.py`: authentication/scopes, rate limits, worker/gateway handling and metrics. Sustained production load, readiness and recovery validation remain open. |
| Configuration | `config.py`: defaults, data-directory JSON, environment variables, then explicit overrides. Evaluation explicitly disables live services and uses disposable storage. |
| Tests and evaluation | `tests/` contains parser, retrieval, source-mock, local HTTP, index and extraction checks. `eval/` adds the versioned baseline and uncertainty estimates; source-specific answer correctness remains separate from webpage metrics. |

## Five largest measured query stages

Measured on the 57-document synthetic fixture corpus, 59 queries, three uncached-result repeats. These are the largest instrumented components in this workload, not proof of production-scale bottlenecks. Query parsing includes intent classification and resource lookup. Text reads include decompression; passage selection includes passage scoring. Timings include wrapper overhead.

| Rank | Stage | Calls | Total ms across all runs | Per-call p95 ms |
| --- | --- | ---: | ---: | ---: |
| 1 | query_parse_and_intent | 177 | 122.813 | 0.851 |
| 2 | passage_selection | 192 | 33.425 | 0.506 |
| 3 | candidate_retrieval | 177 | 21.335 | 0.267 |
| 4 | document_text_reads | 309 | 15.419 | 0.080 |
| 5 | document_metadata | 156 | 12.527 | 0.149 |

The complete stage profile is in `eval/baseline.json`. Fixture build/index time was 99.297 ms; the index occupied 72083 bytes. Query latency p50/p95/p99 was 1.919/3.044/4.099 ms. These tiny-corpus offline measurements do not establish large-index, network, concurrent-load, or cold-process latency.

## Next evidence needed

The corpus is too small and reused to establish broad accuracy or language support. Step 2 should measure normalization correctness and index-size/latency changes against this baseline; later stages need larger held-out judgments, live-discovery measurements, and provider-stage profiling. Weak typo/Hinglish retrieval and corpus coverage are visible problems, not solved by these timings.
