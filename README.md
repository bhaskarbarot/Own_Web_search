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

## Data-driven relevance and direct answers

The relevance refactor is on `wip/data-driven-relevance`. Intent is learned from
`ownsearch/resources/intent_templates.tsv`: `{subject}` slots are excluded from
training, so repeated company or programming names never become phrasing words.
Additional examples can be supplied in `<data_dir>/intent_examples.tsv`.

Live searches link names and aliases through Wikidata/Wikipedia, discover URLs
from entity records, and walk official-site links and bounded sitemaps. News
feeds live in `ownsearch/resources/news_feeds.txt`; their headlines and publisher
dates can be indexed even when the article itself is unavailable. Ranking uses
lexical relevance, linked names, subject density and learned title phrasing.
There are no per-topic domain guesses or domain-specific ranking overrides.

```bash
python3 main.py search "Nvidia live price" --pretty
python3 main.py search "TCS 6-month analysis" --pretty
python3 main.py search "Claude docs on MCP" --pretty
python3 main.py search "python asyncio" --no-live --pretty
python3 -m unittest discover -v
```

JSON search responses include `answer` (`fact`, `entity`, `stock_quote`,
`stock_history`, or `null`). Answers carry sources; quotes carry market timestamps
and a `regular_market` scope. History identifies adjusted/ordinary closes and
whether the latest trading session is still in progress. An unavailable provider
never becomes an estimated price or an invented fact.

Settings in `<data_dir>/ownsearch.json` include:

- `discovery_timeout` (20 seconds): shared network budget for live answers/linking/discovery.
- `discovery_max_requests` (24): page requests, including robots and redirect hops.
- `discovery_sitemap_limit` (500): URLs examined per verified-site walk.
- `relevance_score_ratio` (0.30): reject scores below this fraction of the best score.
- `knowledge_enabled`: enable/disable live entity linking.
- `news_feeds_file`: feed list path; set this and `news_feeds` to empty strings to disable feeds.
- `market_lookup_url` / `market_chart_url`: configurable source templates; empty strings disable market answers.
- `searxng_url`: optional self-hosted SearXNG JSON endpoint. No paid provider is required.

Live failures are returned in `provider_errors`, and discovery repeats are cached.
Wikimedia requests are serialized within each process and cached on disk. Keep
the public repository URL as the bot contact. Freshness `day` is a rolling
24-hour window; `week` is seven days. Page discovery cannot expand the frontier
through arbitrary sitemap/page links during a query.

The tests use isolated indexes and mock services/local HTTP fixtures. The legacy
50-query evaluation remains a manual corpus benchmark, rather than a test that
reads or modifies your production index. See [the measured relevance report](docs/RELEVANCE_REPORT.md).
