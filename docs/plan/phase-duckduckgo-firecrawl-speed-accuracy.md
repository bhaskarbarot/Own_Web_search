# Phase Plan: DuckDuckGo + Firecrawl Quality, Millisecond Speed & AI-Agent Search Tool

Date: 2026-10-22, Asia/Kolkata.
Active Branch: `Independent`.

## 1. Goal

Upgrade OwnSearch into a dual-mode search engine combining:
1. **DuckDuckGo-grade Instant Answers and Search Experience**:
   - Instant answers for queries (biographical definitions, technical documentation, code solutions, facts).
   - High precision ranking and clean search results with query term snippets.
   - Comprehensive multi-domain coverage across science, engineering, programming, and encyclopedic knowledge.
2. **Firecrawl-grade Structured Markdown & AI Agent API**:
   - Full semantic Markdown for every indexed and fetched page (`# Headings`, `- Lists`, ` ```code``` `).
   - Drop-in Firecrawl response schema (`output="firecrawl"`) for LLMs and agent frameworks.
   - Formats: `output="text"`, `output="code"`, `output="markdown"`, `output="firecrawl"`, `output="json"`.
3. **Sub-second to Millisecond Speed**:
   - Persistent SQLite Query Cache: repeat queries resolve in 1–5 ms across processes.
   - URL Alias & Redirect Caching: store both requested and final URLs to eliminate redundant HTTP redirects.
   - Early Termination: when high-confidence direct answers or top matching pages are fetched, exit crawl loop immediately (<1.5s cold instead of 6-8s).
4. **Complete Pip Packaging**:
   - Bundle `sources.txt` in package resources so pip-installed users get full hub access anywhere.

## 2. Files to Change

1. `ownsearch/persistent_cache.py`:
   - Add persistent `query_cache` table to SQLite (`key TEXT PRIMARY KEY, payload BLOB NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL`).
   - Implement persistent `get_query_result()` and `put_query_result()`.
   - Add URL alias mapping to eliminate duplicate redirect crawls.
2. `ownsearch/coordinator.py`:
   - Enable query cache lookup at start of `search()` when `use_cache=True` and freshness allows.
   - Implement early exit: when top target entity/code URL completes and satisfies query, finish crawl without waiting for non-essential links.
   - Map aliases/redirects so requested URLs hit cache.
3. `ownsearch/tool.py`:
   - Support `output="firecrawl"` returning standard Firecrawl `/search` schema (`{"success": true, "data": [{"title", "url", "markdown", "description", "metadata"}]}`).
   - Add `to_firecrawl()` method to `SearchResults`.
4. `ownsearch/config.py`:
   - Resolve `sources_file` to packaged `resources/sources.txt` if root file is absent.
5. `ownsearch/resources/sources.txt`:
   - Synchronize with root `sources.txt` containing all curated hubs.
6. `ownsearch/resources/search.html`:
   - Add DuckDuckGo-style top answer card with fast copy button and Firecrawl markdown inspection toggle.
7. `tests/`:
   - Add regression tests for persistent query cache, Firecrawl output format, alias resolution, and speed.

## 3. Ordered Steps

- **Step 1: Persistent SQLite Query Cache & Alias Resolution (`ownsearch/persistent_cache.py`)**
  - Create persistent table for query results with TTL and zlib compression.
  - Implement cache get/put with cross-process persistence.
  - Measure: warm query latency drop from 4,000ms to <10ms in fresh python processes.

- **Step 2: Coordinator Speed Up & Early Termination (`ownsearch/coordinator.py`)**
  - Check `get_query_result()` before socket allocation.
  - Early-exit condition: if high-confidence answer or matching pages exist and top entity path completed, break early.
  - Measure: cold search speed reduction from ~6s to ~1.5s.

- **Step 3: Firecrawl API Format & Package Distribution (`ownsearch/tool.py`, `ownsearch/config.py`)**
  - Add `output="firecrawl"` and `SearchResults.to_firecrawl()`.
  - Copy `sources.txt` into `ownsearch/resources/sources.txt` and update path fallback in `config.py`.
  - Measure: agent search tool tests and pip import validation.

- **Step 4: UI Enhancements (`ownsearch/resources/search.html`)**
  - Update instant answer box and markdown inspection.
  - Add latency speed badge (`⚡ took X ms`).
  - Measure: browser inspection and test suite.

- **Step 5: Full Benchmark & Regression Validation**
  - Run all 150+ unit tests in standard Python and `python3 -S`.
  - Run controlled fixture benchmark (`eval/runs/independent/`).
  - Update `docs/PROGRESS.md`.
