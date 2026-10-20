# OwnSearch — self-owned web search engine

The bundled discovery backend lives in [`searxxxing/`](searxxxing/OWNSEARCH_README.md).
It reuses the copied SearXNG source rather than requiring a separately hosted instance:

```sh
python3 main.py discovery setup
python3 main.py discovery serve
# In another terminal:
python3 main.py search "your query" --pretty
```

The copied backend still contacts external search engines. Its license and authorship
are preserved; no broad-web accuracy or cold-latency target is certified by bundling it.


Python 3.10+. Normal search is now **live-web-first**: configured search providers discover URLs, selected pages are inspected in memory, and no prebuilt document database or GPU is required. Configure a working SearXNG instance or optionally your own Brave API key. With neither configured, general web discovery is explicitly unavailable. No paid API is enabled automatically.

See [live-web setup, flow, storage and limits](docs/LIVE_WEB.md) and [implementation/verification report](docs/LIVE_WEB_REPORT.md). Your old corpus and crawler are preserved as optional local capabilities; passing unit tests does not prove 90% internet accuracy.

## Quick start

```bash
python3 main.py providers --check                              # verify your configured provider
python3 main.py search "your query" --pretty
python3 main.py search "your query" --answer --pretty           # cited source excerpt when supported
python3 main.py serve                                          # live API on 127.0.0.1:8765
python3 -m unittest discover -s tests -t .                          # full regression suite
```

## For AI agents

```bash
python3 main.py create-key --agent agent1            # per-agent key, rate limit, quota, scopes
python3 main.py cluster --nodes 4 --crawl-threads 4  # gateway + 4 search nodes + crawler/indexer
```

`GET /search?q=...&limit=10&freshness=week&site=example.org&filetype=pdf` with `Authorization: Bearer <key>`.
Responses include results, short evidence passages, dates when known, retrieval timestamps, source/fetch status, a coverage report, and prompt-injection flags. Live mode provides `/search`, transient `/fetch`, `/providers`, `/health`, `/stats`, `/metrics`. Persistent `/crawl`, `/ingest`, `/feedback` require an explicit local-mode service. Python: `from ownsearch.engine import web_search_handler` uses the same configured coordinator.

For optional corpus ingestion/crawling, use the existing `crawl`/`ingest` commands. `search --no-live` searches that corpus offline; `OWNSEARCH_SEARCH_MODE=local python3 main.py serve` serves the legacy storage endpoints. Cluster/index benchmarks below concern this optional local-index capability.

Query syntax: `"phrase"  -exclude  site:x.org  filetype:pdf  intitle:x  after:2025-01-01  a OR b`.

## What is built

| Area | Module |
|---|---|
| Database-free live search, provider coordination, temporary evidence and ranking | `coordinator.py`, `webproviders.py`, `webmodels.py`, `webfetch.py`, `webranking.py` |
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

## Historical local-index measurements
- Local test site: 120+ pages crawled, readable text, no duplicate results (tests/test_crawl.py)
- 60k docs: query p50 29 ms, p95 59 ms (single process)
- 30k docs, 7 concurrent agents via `cluster --nodes 4`: ~102 queries/s uncached, p95 98 ms, 0 errors

These are local-index measurements, not cold live-web latency or open-web accuracy. Live coverage depends on configured providers; optional local coverage depends on what you crawl/import.
v0.1 is archived in `backup/` (not committed).

## Local-mode relevance and direct answers

This section describes the preserved local-index pipeline. The default live-web path is documented in [LIVE_WEB.md](docs/LIVE_WEB.md); it does not ingest pages or depend on Wikimedia entity linking.

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

- `discovery_timeout` (8 seconds): shared request budget; live-web enrichment has additional conservative limits.
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

## Current engineering checkpoint

Step 1 baseline and prerequisite freshness corrections are documented in
[docs/progress.md](docs/progress.md) and [docs/architecture.md](docs/architecture.md).

```bash
python3 eval/run_eval.py --output /tmp/ownsearch-baseline.json
```

This evaluates 59 synthetic queries with per-language bootstrap intervals using
a disposable offline index. It does not establish 90% open-web accuracy.

## Current upgrade and setup

The implementation, measured results, file changes and remaining accuracy gates are in [the upgrade report](docs/UPGRADE_REPORT.md). Passing fixtures is not a 90% open-web accuracy claim.

```bash
sh scripts/setup.sh base
.venv/bin/python main.py search "your query" --pretty
.venv/bin/python eval/run_eval.py --output /tmp/ownsearch-eval.json
```

`sh scripts/setup.sh full` installs optional runtimes; it does not download or validate model weights. Configure local model paths and calibrated language margins before enabling them. See [dependencies and licenses](docs/DEPENDENCIES.md).

The API uses background page discovery by default and returns `discovery_status`; repeat a query after ingestion completes. The short-lived CLI explicitly waits for bounded live discovery. Use `--no-live` for local-only CLI search.

Remote Wikimedia entity queries are opt-in: set `remote_knowledge_enabled` to true in `data/ownsearch.json`. Local labels can be imported using `entities-import path.jsonl --limit 10000`; existing public cached entity records are migrated locally. `entities-import-cache` repeats that operation explicitly. Docs discovery can read maintainer-published URLs through `package_lookup_url`; an empty URL disables it. A self-hosted SearXNG URL is optional; no public full-web search endpoint is enabled automatically.

Existing indexes remain readable. Back up the data directory before running `python3 main.py reindex` to populate new analysis fields; old code cannot read newly written nine-field segments. New ingestions preserve original text; old lost source distinctions require recrawling.

Language priors: `--prefer-lang hi-IN`; strict filter: `--lang hi`; temporal zone: `--timezone Asia/Kolkata`. Timezones default to UTC and are never inferred from browser language.

```bash
python3 benchmark.py --source-data-dir data --reindex --output /tmp/ownsearch-benchmark.json
python3 scripts/fetch_eval_samples.py --output-dir /tmp/miracl-metadata
python3 scripts/import_trec_eval.py --help
python3 scripts/validate_feeds.py --report /tmp/feed-health.json
python3 scripts/calibrate_intent.py --help
```

Benchmarking uses a temporary corpus copy. Public evaluation requires the corresponding passage corpus and original judgments; missing judged passages are rejected. The bundled Hindi/Gujarati/temporal/output resources remain active fallbacks and are not removed prematurely.
