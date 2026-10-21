# OwnSearch Comprehensive Architectural Upgrade Plan

Date: 2026-10-21, Asia/Kolkata.
Branch: `Independent`. Base commit: `40beb2b`.

## 1. Goal

Upgrade OwnSearch into a fast, accurate, reliable, local-first web search engine meeting all requirements in `goal.md`:
- Purely independent, local-first search: zero dependencies on Google, Bing, Brave, DuckDuckGo, SearXNG or external search APIs.
- Sub-10ms warm/cached search via an in-memory & persistent inverted index with BM25 ranking and early filtering.
- Incremental indexing and separation of local search from live crawling, with progressive updates.
- Robust crawling with connection pooling, conditional HTTP requests (ETag / If-Modified-Since), politeness, and strict security (SSRF, robots.txt, size/deadline budgets).
- 100% filter correctness across all modes (`web`, `images`, `video`), result counts (1–50), file types (PDF, HTML, text, DOCX, XLSX, PPTX, custom extensions), freshness, language, sites, timezones, and query operators.
- Grounded citations and honest evidence reporting for answers.
- Clean public Python API (`search_tool`, `asearch_tool`), CLI, and MCP server.
- Responsive HTML UI with progressive search status.

## 2. Files to Change / Create

1. `ownsearch/index.py` (New): Inverted index for terms, doc metadata, images, and videos. Fast BM25 scoring with early filtering. Incremental add/remove.
2. `ownsearch/cache.py`: Integrate `InvertedIndex` into `PageCache` and query-result caching.
3. `ownsearch/persistent_cache.py`: Persist index metadata and support incremental index updates.
4. `ownsearch/fetcher.py` & `ownsearch/webfetch.py`: Connection pooling (keep-alive reuse), conditional requests (If-Modified-Since / ETag), streaming body reader with size caps.
5. `ownsearch/coordinator.py`: Cache-first retrieval, separation of local search and live crawling, progressive callback/streaming, dedicated image/video retrieval, unified query plan.
6. `ownsearch/webranking.py`: Evidence scoring, title & phrase weighting, canonical deduplication, domain caps.
7. `ownsearch/query.py`: Query normalization, filetype aliases, operator validation.
8. `ownsearch/tool.py` & `ownsearch/__init__.py`: Public API `search_tool`, `asearch_tool`, `SearchResults`, export helpers (Markdown, JSON, PDF export).
9. `ownsearch/mcp.py`: Model Context Protocol server (`ownsearch mcp`).
10. `ownsearch/server.py` & `ownsearch/resources/search.html`: Progressive streaming endpoint (`/search/stream`), responsive UI with immediate cache display and progressive updates.
11. `tests/`: Comprehensive regression tests for index, filters, streaming, connection pooling, file types, and public API.
12. `docs/PROGRESS.md`: Record baseline and post-step measurements.

## 3. Ordered Small Steps

- **Step 1: Inverted Index & Fast BM25 Retrieval Engine (`ownsearch/index.py`)**
  - Implement posting lists with field-aware term frequencies (title, headings, path, content).
  - Implement BM25 with `FIELD_WEIGHTS` and `FIELD_B`, early boolean & metadata filtering.
  - Implement dedicated image and video indexing.
  - Unit tests for index operations, phrase queries, filtering, and incremental updates.
  - Measure warm retrieval latency on fixture queries (target: < 5 ms).

- **Step 2: Integration of Index with In-Memory & Persistent Page Cache**
  - Update `PageCache` and `PersistentPageCache` to maintain the index incrementally upon `put()` and `prune()`.
  - Add query-result caching with TTL for identical queries under unchanged index state.
  - Regression tests for cache restart, eviction, and zero-rescan lookups.

- **Step 3: Crawler Optimization: Connection Pooling & Conditional Requests**
  - Implement HTTP/HTTPS connection pooling per origin with thread-safe leasing.
  - Add `If-Modified-Since` and `ETag` conditional request support on re-crawling.
  - Preserve strict SSRF, redirect limits, robots.txt, and byte budget tracking.
  - Benchmark cold crawl latency with connection reuse.

- **Step 4: Filter Normalization & Dedicated Media/Document Retrieval**
  - Validate and normalize all query operators and UI parameters into a single execution plan.
  - Verify every filetype: HTML, PDF, text, DOCX, XLSX, PPTX, and custom extensions.
  - Dedicated search modes: `web`, `images`, `video`.
  - Regression tests for every filter combination.

- **Step 5: Separate Local Searching from Live Crawl & Progressive Results**
  - Implement immediate cache retrieval followed by progressive crawl updates.
  - Add SSE streaming endpoint (`/search/stream`) in `server.py`.
  - Update `resources/search.html` to render immediate results and update dynamically as crawling progresses.

- **Step 6: Public Agent API (`search_tool`, `asearch_tool`), CLI & MCP Server**
  - Implement `search_tool`, `asearch_tool`, `SearchResults` object.
  - Implement PDF export capability for search results (`results.to_pdf()` or `export="results.pdf"`).
  - Implement `ownsearch mcp` server over stdio.
  - Package exports in both `ownsearch` and `own_search`.

- **Step 7: Final Regression Suite, Benchmarks & Documentation**
  - Run the entire test suite and benchmark suite.
  - Record ablation and metrics in `docs/PROGRESS.md`.

## 4. Risks and Mitigation

- **Risk**: Index memory usage balloons with large document sets.
  - *Mitigation*: Cap indexed text length, store compressed passages, limit postings to top terms, enforce entry bounds.
- **Risk**: Asynchronous progressive updates could cause race conditions in candidate ranking.
  - *Mitigation*: Immutable snapshot passes during intermediate ranking; thread-safe queue updates.
- **Risk**: Regressions in existing tests.
  - *Mitigation*: Run the 129 existing unit tests after every single step. Add new targeted tests for new features.
