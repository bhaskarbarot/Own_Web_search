# Phase Plan: Top 100 AI Agent Web Search Queries Benchmark & Production Readiness

Date: 2026-10-22, Asia/Kolkata.
Active Branch: `Independent`.

## 1. Goal

Evaluate OwnSearch across the curated **Top 100 AI Agent Web Search Queries** spanning 10 key agent workflows:
1. Coding agents (1–10)
2. AI and machine learning agents (11–20)
3. Research agents (21–30)
4. Browser and web automation agents (31–40)
5. Current information and news agents (41–50)
6. Documentation and API agents (51–60)
7. Business and finance research agents (61–70)
8. Troubleshooting and technical support agents (71–80)
9. Security and vulnerability research agents (81–90)
10. Difficult, multi-step search queries (91–100)

Deliverables:
- Save and structure the 100 queries in `eval/top_100_ai_agent_queries.json`.
- Enhance query understanding for natural language prompts (e.g. conversational lead-ins: `Find official documentation for...`, `How do I fix...`, `Compare...`).
- Expand authority seeds in `sources.txt` to cover developer, AI, documentation, and policy hubs.
- Run an automated 100-query evaluation pipeline measuring latency, result count, top URLs, answer extraction, and markdown generation.
- Compare results across OwnSearch, DuckDuckGo, and Firecrawl architectures.
- Report honest measurements and declare green flag readiness based on concrete metrics.

## 2. Files to Change

1. `eval/top_100_ai_agent_queries.json`:
   - Store the complete 100 benchmark queries with categories and IDs.
2. `ownsearch/query.py` & `ownsearch/textproc.py`:
   - Enhance conversational agent query normalization so conversational carrier phrases (`Find GitHub repositories implementing...`, `Find official documentation for...`, `How do I fix...`, `Compare...`) extract core scoring terms accurately without dropping critical domain qualifiers.
3. `sources.txt` & `ownsearch/resources/sources.txt`:
   - Expand authoritative starting hubs for modern AI, framework docs, security, and research:
     - Framework & Docs: `fastapi.tiangolo.com`, `docs.djangoproject.com`, `playwright.dev`, `nextjs.org`, `react.dev`, `redis.io`, `postgresql.org`, `docs.docker.com`, `supabase.com`, `modelcontextprotocol.io`, `owasp.org`.
     - AI & Research: `arxiv.org`, `huggingface.co`, `github.com`.
     - Government & Official: `rbi.org.in`, `pib.gov.in`.
4. `scripts/run_100_agent_benchmark.py`:
   - Automated runner that executes all 100 queries, records latency, result counts, URLs, answers, and Firecrawl markdown, and outputs a structured evaluation report.
5. `docs/PROGRESS.md`:
   - Record test suite passes, benchmark metrics, before/after numbers, and handoff.

## 3. Ordered Steps

- **Step 1: Conversational Agent Query Normalization (`ownsearch/query.py`)**
  - Strip conversational search prefixes (`Find the official documentation for`, `Find open-source implementations of`, `How do I fix`, etc.) during lexical query parsing to produce high-precision BM25F scoring terms.
  - Preserve required entity identifiers (`fastapi`, `langgraph`, `docker`, `postgresql`, `redis`, `nextjs`, `react`, `supabase`).
  - Measure: verify query normalization unit tests.

- **Step 2: Authority Hub Expansion (`sources.txt`, `ownsearch/resources/sources.txt`)**
  - Add curated official roots for the 10 categories to `sources.txt` and `ownsearch/resources/sources.txt`.
  - Measure: verify load_registry and seed loading.

- **Step 3: Execute 100-Query Benchmark Runner (`scripts/run_100_agent_benchmark.py`)**
  - Run all 100 queries through `search_tool`.
  - Record:
    - Result count (P@5/P@10 availability)
    - Valid URLs and domain origins
    - Answer extraction (code block, lead summary, extractive)
    - Firecrawl Markdown validity
    - Latency (cold vs warm cache)
  - Generate JSON and Markdown evaluation results in `eval/runs/independent/top100_benchmark_results.json`.

- **Step 4: Comparative Analysis (DuckDuckGo vs Firecrawl vs OwnSearch)**
  - Tabulate results against DuckDuckGo (links + 150-char plain snippets) and Firecrawl (page markdown only).
  - Verify speed, accuracy, and agent readiness.

- **Step 5: Full Regression Testing & Gate**
  - Run all 152+ unit tests in standard Python and `python3 -S`.
  - Update `docs/PROGRESS.md` and report back to user.
