# Phase Plan: Full-Coverage Tiered Engine (80/20 Hubs, Continuous Crawler, Common Crawl CDX)

## 1. Goal
Upgrade OwnSearch to support broad web coverage across all 12 AI-agent categories in `query.md`:
1. Curated 80/20 Authority Hubs: High-yield seeds in `sources.txt` spanning official tech docs, research repos, live news/CVE feeds, Indian business/gov portals, hardware specs, and general knowledge.
2. Background Batch Crawler (`ownsearch/crawler.py` & `main.py crawl`): High-throughput crawler that parses sitemaps, RSS feeds, and follow-links into the persistent SQLite cache and inverted index.
3. Common Crawl CDX Resolver (`ownsearch/commoncrawl.py`): Query free public Common Crawl CDX API (`index.commoncrawl.org`) to discover millions of archived URLs and fetch WARC slices without hitting live origins.
4. Intelligent Query Router in `coordinator.py`: Local index first (<5ms), live feed routing for news, exact phrase matching, grounded citations, and zero fabrication on unknown terms (e.g. `SuperVectorDB9000`).

## 2. Files to Create / Modify
- `sources.txt`: Expand seeds across the 12 categories with accurate topic descriptions.
- `ownsearch/commoncrawl.py` (New): Client for Common Crawl CDX API and WARC range requests.
- `ownsearch/crawler.py` (New): Multithreaded polite background crawler discovering sitemaps, RSS feeds, and internal links.
- `ownsearch/cli.py` & `main.py`: Add `crawl` subcommand with options (`--max-pages`, `--depth`, `--workers`, `--site`, `--sitemap`).
- `ownsearch/coordinator.py`: Integrate Common Crawl discovery fallback and live feed prioritization.
- `tests/test_commoncrawl.py` (New): Unit tests for CDX parsing and archive resolution.
- `tests/test_crawler.py` (New): Unit tests for sitemap discovery, robots compliance, and background ingestion.
- `docs/PROGRESS.md`: Measurement and milestone progress updates.

## 3. Ordered Implementation Steps
1. **Step 1: Curated 80/20 Authority Hubs in `sources.txt`**
   - Add high-authority sources covering React, LangGraph, Python, Docker, PostgreSQL, Ubuntu, arXiv, Hugging Face, Indian GST, ERPNext, Odoo, Reuters/BBC news feeds, Ubuntu Security Notices.
   - Test source planning and registry loading.

2. **Step 2: Common Crawl CDX Resolver (`ownsearch/commoncrawl.py`)**
   - Implement query to `https://index.commoncrawl.org/` with domain filtering, pagination, and status checks.
   - Implement WARC record fetching with range requests and gzip decompression.
   - Add unit tests with mock CDX and WARC payloads.

3. **Step 3: Background Batch & Sitemap Crawler (`ownsearch/crawler.py`)**
   - Implement `SitemapCrawler` and `BackgroundCrawler` using `ConnectionPool`.
   - Parse XML sitemaps (`/sitemap.xml`, `/sitemap_index.xml`) and RSS/Atom feeds.
   - Ingest extracted pages into `PersistentPageCache` and `InvertedIndex`.
   - Add `main.py crawl` CLI command.
   - Add unit tests in `tests/test_crawler.py`.

4. **Step 4: Coordinator Routing & Category Verification**
   - Wire CDX discovery and sitemap crawling into the coordinator when local results are scarce.
   - Run tests for exact phrases (D07), nonexistent terms (D05 zero fabrication), news recency (N01-N08), and official tech docs (C06, T01-T04).
   - Ensure all 140+ unit tests continue to pass under standard Python and `python3 -S`.

5. **Step 5: Benchmarking, Validation & Documentation**
   - Measure cold/warm search latencies.
   - Update `docs/PROGRESS.md` and commit changes.
