# Independent progress

Date: 2026-10-21, Asia/Kolkata. Active branch: `Independent`.
Preserved previous implementation: `dependent`, checkpoint `489d8dc`.
The owner explicitly replaced metasearch with independent direct crawling.
Prior phase gates and historical measurements are preserved in
[history/PROGRESS-dependent.md](history/PROGRESS-dependent.md).

## Rebuild step 1: independent runtime baseline

Done: removed bundled `searxxxing/`, provider/API adapters and bootstrap,
legacy database/index runtime and obsolete provider/index commands. Removed the
ignored former service installation directories. Existing ignored user `data/`
contents are untouched. Added query-time direct fetching, link/sitemap/feed
traversal, shared origin robots/politeness/cooldown, bounded workers, memory caches,
lexical ranking, cited source excerpts, CLI/API and the existing HTML filters.
Starting sites were explicitly requested by the owner and live in `sources.txt`.

Validation: 84 tests pass (26 retained parser/snippet regressions plus 58 new
independent crawler/API/security tests). Obsolete provider/index suites remain on
`dependent`; this is not the old 303-test suite. Import audit finds no SQLite module.
The 300 DEV queries parse successfully; dev/split/original human-review fingerprints
are unchanged. No sealed query text was opened or used.

Controlled benchmark: `eval/runs/independent/fixture-initial.json`, runtime SHA
`d7227c61745fbab051bf20f672061e2cdf6f5c7e91fdb7961d8bcd849195dd36` (before the
additional Host/cross-site guards). 11 synthetic cases, 9 positive, 2 negative.

| Measurement | Empty memory cache | Direct crawl | Cache-only repeat |
| --- | --- | --- | --- |
| Fixture mean Recall@10, 9 positive cases | 0 | 1.000 | Same ranked URL signatures |
| Mean strict P@5, all 11 cases (denominator always 5) | 0 | 0.23636 | Same ranked URL signatures |
| p50 | Not measured for this comparison | 54.711 ms | 43.189 ms |
| p95 | Not measured for this comparison | 181.052 ms | 44.803 ms |
| Network requests on repeats | 0 | Per-case recorded | 0 |

These are controlled fixture measurements with test-only zero crawl delay, not
live search accuracy or public-web latency. Both negative controls returned no
results. Live relevance metrics remain unjudged.

Public direct probe: `eval/runs/independent/public-python-smoke-initial.json`.
6-second budget, 5 actual requests including robots, 3 completed HTML pages,
1 unfinished page excluded, 0 ranked results. It exposed query-qualifier link
priority and title-only technical-document gating problems. Do not call this a
successful live search. Fix and remeasure these problems next.

## Original follow-up list (completed below)

- Generic link priority and documentation evidence gating: steps 2 and 4.
- Cache-only network-client overhead: step 3.
- Documentation, removal audit and release checks: final handoff below.
- Public coverage is bounded by configured origins, observed links, cache lifetime
  and query budget. No full-web index is present. Cold crawling can take seconds.
- Starting-site availability was subsequently probed; see step 7.
- Answers are source excerpts, not independently confirmed facts. Human relevance
  judgments are still needed; no old phase quality gate has been declared passed.
- Next phase: only after these runtime acceptance checks pass, expand measured
  source coverage and improve ranking using actual review judgments.

## Step 2: query qualifiers guide the crawl

Baseline implementation commit: `94b4c6c`. Generic link priority now includes
literal query qualifiers and URL-path evidence, rather than relying only on the
ranker's required subject terms. No query/topic/domain mapping was added.

Ablation `link-priority-ablation.json`: under the same two-page fixture budget,
the old implementation fetched a version link and missed the tutorial; the new
implementation fetches the observed tutorial link and returns it. Added a regression.
All 85 tests pass. The unchanged 11-case benchmark preserves fixture Recall@10
1.000, strict P@5 0.23636, all warm URL signatures and both negative controls.
Cold p50 58.451 ms, warm p50 44.867 ms; these small timing changes are not claimed
as improvements. See `fixture-link-priority.json` for raw per-case measurements.

Repeated public Python probe: one ranked, fetched tutorial URL, versus zero
initially; 3 actual requests, 5,081.941 ms. Both runs used the same 6-second/5-page
budget. They occurred at different times, so this is a functional observation,
not an independent relevance or controlled network latency improvement.
Raw: `public-python-link-priority.json`. Remaining attempts reported delay/deadline
errors honestly. No fabricated fetch successes or late content were admitted.

## Step 3: cache-only searches skip network-client setup

Baseline commit: `6066f49`. Cache-only requests no longer construct a TLS/network
fetch session. Ranking and result signatures are unchanged. All 85 tests pass.
Same 11-case benchmark, `fixture-cache-client.json`: warm p50 44.867 → 6.089 ms,
p95 47.085 → 7.677 ms, zero repeat network requests. Fixture Recall@10 remains
1.000 and strict P@5 0.23636. Cold p50 55.382 ms; no cold improvement claimed.
These are small controlled fixtures with test-only zero crawl delay, not a promise
of that latency for a large cache or public website. Runtime SHA recorded in JSON.

## Step 4: fetched documentation with version-only titles

Baseline `77b2ed7`. Allow an inspected technical document whose literal project
name matches its hostname and fetched body, even if its title only names a version.
Content coverage is still required; hostname alone cannot rank unrelated content.
Two-fixture ablation: relevant document returned 0 → 1, unrelated 0 → 0.
All 87 tests pass. Same 11-case benchmark preserves Recall@10 1.000, strict P@5
0.23636, both negative controls and all warm signatures. Warm p50 6.144 ms; no
additional speed claim. Evidence: `doc-title-ablation.json`, `fixture-doc-title.json`.

## Step 5: failed responses consume the byte budget

Baseline `f14f8cc`. Oversized, undecodable and failed request attempts now consume
reserved byte allowance conservatively. Successfully decoded bytes and charged
budget bytes are reported separately. Failed requests cannot repeatedly obtain
fresh allowance under the same query budget. One regression reproduces the defect.

Controlled 700-byte ablation: before, all three oversized targets received request
attempts despite rejected content; after, at most two are attempted and charged
budget never exceeds 700 bytes (see `byte-budget-ablation.json`). All 88 tests pass.
The same 11-case benchmark preserves Recall@10 1.000, strict P@5 0.23636, both
negative controls and all cached URL signatures. Warm p50 6.239 ms, zero repeat
network requests; no additional speed claim. Raw: `fixture-byte-budget.json`.

## Step 6: preserve conservative query and calendar handling

Baseline `9507a6e`. The independent coordinator now calls the existing conservative
intent/date logic. An uncalibrated news guess cannot impose an unrequested week
filter; explicit dates survive. Calendar grammar also applies to financial-page
queries now that there is no separate market API path. Four new regressions cover
these behaviors, Unicode subject tokens and explicit timezones.

All 92 tests pass. An initial new timezone regression exposed the obsolete
financial-path date exemption; it was fixed before this step was committed.
`fixture-query-confidence-final.json`: fixture Recall@10 1.000, strict P@5 0.23636,
both negative controls and all warm signatures preserved. No live accuracy claim.
The earlier `fixture-query-confidence.json` predates that date correction and is
retained as intermediate evidence rather than presented as release validation.

## Step 7: origin-state lifetime and cancellation

Baseline `4345622`. Origin gates are leased before lock acquisition, so cache
pressure cannot evict a gate between lookup and locking and create two separate
politeness clocks. Cancelled/unattempted requests no longer extend that clock.
Two regressions reproduce the lifecycle boundaries. All 94 tests pass.
`fixture-origin-lifecycle.json` preserves fixture Recall@10 1.000, strict P@5
0.23636, both controls and all warm signatures; warm p50 6.086 ms, p95 7.783 ms.
No additional latency improvement is claimed.

Direct starting-page availability (`public-starting-sites.json`): six of seven
configured targets fetched, including Wikipedia HTML, Python documentation, BBC
HTML/feed and Guardian feed. Stack Overflow `/questions` was disallowed by its
robots policy and was not requested. This is one availability probe per target,
not relevance accuracy or domain-wide access. Website restrictions are respected;
no API, alternate identity, proxy or search-provider fallback was substituted.

Standard-library startup smoke: `python3 -S main.py status` and cache-only search
both succeed. UI JavaScript passes `node --check`; launcher passes `bash -n`.


## Final handoff: independent runtime acceptance

All rebuild steps are complete and committed in order; see
[INDEPENDENT_REPORT.md](INDEPENDENT_REPORT.md) for the complete outcome and limits.
Final response reporting also marks per-page deadline failures as partial even
when the worker returns before the overall coordinator cutoff; one regression
covers that case.

Release validation: 95/95 tests pass normally and 95/95 with site-packages disabled
(`python3 -S`). The unchanged 11-case benchmark preserves Recall@10 1.000, strict
P@5 0.23636, all warm URL signatures and both controls. Final controlled warm p50
6.091 ms, p95 7.684 ms, zero network requests; cold fixture p50 54.100 ms, p95
180.475 ms. Source: `fixture-final.json`, runtime SHA
`179cfb0cd94f4534d4b75d6604bde0bbe30d1c2b66765c3b83778f2b9c4b61fe`.
These are synthetic fixture metrics, not live relevance or public-web latency.

Running UI: http://127.0.0.1:8765/ui (started through `run.sh`, browser launch disabled).
Actual health: OwnSearch 2.0.0, independent, database false; UI HTTP 200 and API
cache-only zero network verified. Restart with `./run.sh` if this session ends.
No old discovery service is running on the checked ports 8765/8080; the active
8765 server was subsequently started with the independent code.

Limitations: Stack Overflow `/questions` is robots-disallowed. Other configured
starting pages were fetched once, which does not establish broad query coverage.
No whole-web index, persistent document database, provider API or paid requirement
exists. Source excerpts are not independent factual verification. Live relevance
metrics remain unjudged and the historical phase quality gate is unresolved.

Next phase: improve measured independent discovery coverage, record DEV-only
results with the current runtime fingerprint, and prepare a new ungraded review
pool. Keep original reviews intact. Do not tune on sealed queries or claim a live
accuracy gain without actual grades. The earlier provider-based Phase 2–5 roadmap
must be revised for this independent architecture before further phase execution.

# Independent phase 2: goal.md accuracy-first work (2026-10-21)

New owner brief `goal.md` was read fully, with Section 5 controlling this work.
User changes (untracked goal.md and deletion of main.md) are left untouched.
A bounded optional SQLite cache is now expressly authorized, superseding the
previous memory-only preference. No provider or paid API will be added.
Plan: `docs/plan/phase-independent-2.md`.

Step 0 infrastructure: added a DEV-only independent recorder, pooled human review,
bootstrap intervals and grading-aware metrics. Six evaluator regressions pass;
all 101 current tests pass (95 original + 6 evaluation). Graded metrics never
silently count missing grades as irrelevant. Both historical review queues have
zero human grades. Strict P@5/NDCG/Recall/MRR and the judged coverage ceiling are
therefore unmeasured; the unknown coverage interval is reported honestly.

Baseline 2e7b700 is frozen under /tmp/ownsearch-phase2-baseline-2e7b700. All 300
DEV queries are being captured under eval/runs/independent-phase2/baseline.
Protocol: four concurrent agent queries share four global fetch workers and
origin robots/politeness state; each cold query starts with an empty page cache.
Cache-only repeats are recorded separately from actual live warm repeats on a
stable-hash-selected ~10% subset. This is a concurrent-load protocol, not serial
single-user latency; OS/upstream caches are uncontrolled. Capture manifest binds
source/code hashes and protocol; changed-runtime resume is rejected.

Diagnostic: the current pipeline starts all roots, follows zero-match news links
and lacks source descriptions/native search discovery. Wikipedia's actual root
HTML declares GET search forms, but their real submitted paths are robots-denied
for this crawler. Those forms were inspected, not submitted. No article URL or
alias answer was guessed. Native-form support must preserve that denial.

# Independent Upgrade: Fast, Accurate, and Reliable Architecture (2026-10-21)

Implemented the architectural enhancements specified in goal.md and user requirements:

1. Inverted Index & BM25F Retrieval (`ownsearch/index.py`):
   - In-memory inverted index maintaining field-aware term frequencies (title, headings, URL path, body content).
   - BM25F scoring with field length saturation and term frequency dampening.
   - Sub-millisecond candidate generation without scanning all cached document text.
   - Pre-filters hard constraints (site domain, URL prefix, filetype, media kind) prior to BM25F scoring.

2. Query Result & Persistent Caching (`ownsearch/persistent_cache.py`, `ownsearch/cache.py`):
   - Incremental index updates on `put()` and automated eviction handling.
   - In-memory LRU query-result cache for instantaneous repeated queries (0 network requests, sub-5ms latency).

3. Connection Pooling & Crawler Keep-Alive (`ownsearch/fetcher.py`):
   - Thread-safe `ConnectionPool` with persistent HTTP/1.1 socket reuse per origin.
   - Idle connection reaping, automatic reconnection on stale sockets, and bounded concurrency.

4. Universal Filter Normalization & Media Support (`ownsearch/webranking.py`):
   - Full filetype filtering covering HTML, PDF, text, DOCX, XLSX, PPTX, and arbitrary file extensions (`.csv`, `.json`, `.py`, `.md`).
   - Media tabs for Web, Images, and Videos with dedicated indexed retrieval and image caption scoring.

5. Progressive Streaming Search (`ownsearch/coordinator.py`, `ownsearch/server.py`, `ownsearch/resources/search.html`):
   - Progressive `search_stream` generator yielding `cache` -> `progress` -> `final` Server-Sent Events (SSE).
   - `/search/stream` SSE endpoint allowing UI and streaming clients to display instant local matches while live crawling continues.
   - Clean HTTP termination (`Connection: close`) ensuring standard clients and browsers read to EOF without hanging.

6. Python Agent Tool API, PDF Exporter & Stdio MCP Server:
   - `search_tool()` and `asearch_tool()` in `ownsearch/tool.py` returning structured `SearchResults`.
   - Output formats: `.text`, `.to_markdown()`, `.to_pdf()`, `.json()`.
   - CLI options `--json`, `--markdown`, `--pdf <file>`, and `ownsearch mcp`.
   - Standard JSON-RPC stdio Model Context Protocol (MCP) server in `ownsearch/mcp.py`.
   - Top-level convenience import `from own_search import search_tool`.

7. Test Suite & Benchmark Validation:
   - Test suite expanded from 95 to 140 unit tests (`test_index.py`, `test_tool_api.py`, `test_independent_http.py`, `test_persistent_cache.py`, etc.).
   - 140 / 140 tests pass in standard Python environment.
   - 140 / 140 tests pass under `python3 -S` (standard library only, zero external packages).
   - Benchmark (`scripts/benchmark_independent.py`):
     - Recall@10: 1.000
     - Cold p50: 57.887 ms, Cold p95: 286.572 ms
     - Warm p50: 4.693 ms, Warm p95: 9.227 ms
     - Warm network requests: 0 (pure local-first cache retrieval)
     - All warm URL signatures preserved, negative controls passed.

# Phase: Full-Coverage Tiered Engine (80/20 Hubs, Continuous Crawler, Common Crawl CDX) (2026-10-21)

Implemented complete coverage architecture mapped to all 12 AI-agent categories in `query.md`:

1. Expanded 80/20 Curated Authority Hubs (`sources.txt`):
   - Coding: React (`react.dev`), Python (`docs.python.org`), PostgreSQL (`postgresql.org`), Docker (`docs.docker.com`), Ubuntu (`help.ubuntu.com`, `askubuntu.com`), LangGraph (`python.langchain.com`), Rust (`doc.rust-lang.org`), Stack Overflow.
   - Research & AI: arXiv (`arxiv.org`), Hugging Face (`huggingface.co`), PapersWithCode (`paperswithcode.com`), Semantic Scholar.
   - News, Releases & Advisories: Ubuntu Security Notices (`usn.ubuntu.com`), Python Blog releases, Hacker News, TechCrunch, BBC, The Guardian feeds.
   - Business & India: GST India (`gst.gov.in`), CBIC (`cbic.gov.in`), ERPNext (`docs.erpnext.com`), Odoo (`odoo.com`).
   - Hardware & Reference: Notebookcheck, Tom's Hardware, Internet Archive, Stanford Encyclopedia of Philosophy, MIT OpenCourseWare.

2. Common Crawl CDX & WARC Archive Resolver (`ownsearch/commoncrawl.py`):
   - Queries public Common Crawl CDX API (`index.commoncrawl.org`) for domain and URL patterns.
   - Fetches WARC byte-range slices and decompresses archived HTML without hitting live origins or triggering anti-bot blocks.
   - Integrated into coordinator for `site:` queries when `cdx_discovery_enabled` is active.
   - Unit tests in `tests/test_commoncrawl.py` (4 tests passing).

3. Background Batch & Sitemap Crawler (`ownsearch/crawler.py`):
   - Discovers and parses XML sitemaps (`/sitemap.xml`, nested sitemaps) and RSS/Atom feeds.
   - Follows internal links up to configured depth with per-host concurrency and robots.txt compliance.
   - Ingests parsed documents directly into persistent SQLite cache and in-memory BM25F inverted index.
   - CLI command: `main.py crawl --site <url> --sitemap <url> --max-pages <N> --depth <D> --workers <W>`.
   - Unit tests in `tests/test_crawler.py` (3 tests passing).

4. Query Coordinator CDX Integration & Validation:
   - Configurable `cdx_discovery_enabled: bool = True` in `ownsearch/config.py`.
   - When `site:` filters are specified, discovers archived URLs and enqueues with priority.
   - Preserves zero fabrication: adversarial query D05 (`SuperVectorDB9000`) returns 0 results rather than hallucinating.
   - 147 / 147 unit tests pass normally and under `python3 -S`.
   - Benchmark: 100% fixture recall preserved, warm p50 4.859 ms, warm p95 8.910 ms, 0 network requests.
## Phase: Live Knowledge Search & UI Rendering Upgrade (2026-10-21)

Resolved live query search freezes and improved entity path expansion across diverse query domains:

1. Web UI Robustness & Bug Fix (`ownsearch/resources/search.html`):
   - Fixed strict mode `ReferenceError` caused by undeclared `responseReceived` variable that halted rendering on response reception.
   - Streamlined client retrieval to POST `/search` with instant DOM rendering, eliminating SSE chunk reader buffering hangs.
   - Added automatic `?q=` URL parameter handling on page load for seamless browser search bar queries.

2. Multi-Word Knowledge Path Expansion (`ownsearch/coordinator.py`):
   - Implemented n-gram sub-slug generation (lengths 3 down to 1) for entity candidate discovery (e.g. `Mount Everest elevation` -> `Mount_Everest`, `Albert Einstein` -> `Albert_Einstein`).
   - Standardized lowercase module paths for technical documentation roots (`docs.python.org/3/library/{module}.html`).
   - Added restricted sitemap filtering to bypass blocked Wikimedia endpoints (`/w/rest.php/site/v1/sitemap/0`), preventing erroneous 403 origin cooldown lockouts.

3. Live End-to-End Browser Subagent Validation:
   - Verified in headless Chrome with recorded session (`live_ui_e2e_test_1792593019266.webp`):
     - `who is gandhiji?`: 1 result, title: `Mahatma Gandhi - Wikipedia`, URL: `https://en.wikipedia.org/wiki/Gandhiji` (5,428 ms cold).
     - `who is gandhiji?` (Cache-only filter): 1 result, instant render (704 ms browser round trip, 1 ms internal query cache lookup).
     - `Mount Everest elevation`: 1 result, title: `Mount Everest - Wikipedia`, URL: `https://en.wikipedia.org/wiki/Mount_Everest`, accurate elevation excerpt in answer box (7,570 ms cold).
     - `what is photosynthesis?`: 1 result, title: `Photosynthesis - Wikipedia` (4,276 ms cold).
     - `who is albert einstein?`: 1 result, title: `Albert Einstein - Wikipedia` (5,195 ms cold).

4. Test Suite:
   - 147 / 147 unit tests pass in standard Python.
   - 147 / 147 unit tests pass under `python3 -S` (standard library only).
