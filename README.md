# OwnSearch — self-owned web search engine

Pure Python 3.10+ standard library. No paid APIs, no external search providers, no `pip install`.

## Quick start

```bash
python3 main.py crawl https://example.org/ --max-pages 100        # polite crawl (robots.txt, sitemaps, feeds)
python3 main.py search "your query" --pretty
python3 main.py ingest ./my_documents                               # HTML, PDF, DOCX/XLSX/PPTX/ODT, EPUB, text, images
python3 main.py serve                                               # HTTP API on 127.0.0.1:8765
python3 -m unittest discover -s tests -t .                          # 56 tests
```

## For AI agents

```bash
python3 main.py create-key --agent agent1            # per-agent key, rate limit, quota, scopes
python3 main.py cluster --nodes 4 --crawl-threads 4  # gateway + 4 search nodes + crawler/indexer
```

`GET /search?q=...&limit=10&freshness=week&site=example.org&filetype=pdf` with `Authorization: Bearer <key>`.
Responses include results, evidence passages (with PDF page numbers), dates, retrieval timestamps, a coverage
report, and prompt-injection flags. Other endpoints: `/document`, `/fetch`, `/crawl`, `/ingest`, `/feedback`,
`/stats`, `/metrics`. Python: `from ownsearch.engine import web_search_handler`.

Query syntax: `"phrase"  -exclude  site:x.org  filetype:pdf  intitle:x  after:2025-01-01  a OR b`.

## What is built

| Area | Module |
|---|---|
| Safe fetcher (SSRF/DNS-rebinding protection, gzip/deflate, retries, conditional GET) | `fetcher.py` |
| robots.txt (RFC 9309), crawl-delay | `robots.py` |
| Persistent frontier: per-host politeness, retries/backoff, adaptive recrawl, leases | `frontier.py` |
| Crawler, sitemap + RSS/Atom discovery | `crawler.py`, `pipeline.py` |
| Extractors: HTML, own PDF parser (fonts, xref, encryption), Office, EPUB, feeds, images, OCR (local Tesseract if installed) | `extract/` |
| Duplicate detection (SimHash), quality/spam signals | `quality.py` |
| Own segment index: compressed postings, positions, fields, deletes, merges, crash recovery | `segments.py`, `indexer.py` |
| Ranking: BM25F, phrase/proximity, PageRank, freshness, diversification, trainable weights | `ranking.py`, `linkgraph.py` |
| Evidence passages, injection screening | `evidence.py` |
| API, auth, rate limits, metrics, gateway/load balancer | `server.py`, `auth.py`, `gateway.py` |
| Common Crawl / WARC bulk import, NDCG eval + ranker training, benchmarks | `warc.py`, `evaluation.py`, `bench.py` |

## Measured on this machine
- Local test site: 120+ pages crawled, readable text, no duplicate results (tests/test_crawl.py)
- 60k docs: query p50 29 ms, p95 59 ms (single process)
- 30k docs, 7 concurrent agents via `cluster --nodes 4`: ~102 queries/s uncached, p95 98 ms, 0 errors

Limits: coverage is only what you crawl/import; one machine cannot match Brave's index size.
v0.1 is archived in `backup/` (not committed).
