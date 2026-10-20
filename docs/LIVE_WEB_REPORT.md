> Update: the bundled source is now configured and has passed three real smoke queries. See [BUNDLED_SOURCE_REPORT.md](BUNDLED_SOURCE_REPORT.md). The unconfigured-provider state below records the earlier verification phase; broad independent accuracy remains unverified.

# Live-web-first implementation report — 2026-10-20

**Status: partially complete.** The implementation is verified with deterministic providers/local HTTP; public-web activation and independent accuracy evaluation remain pending. No general provider endpoint or API key is configured in this checkout. No 90% general accuracy or Google/Brave equivalence is claimed.

## Inspection and root cause

Read the user-authored `pipeline.md`, CLI/API and agent entry points, actual `SearchEngine` call paths, configuration, provider workers, discovery, robots/pinned fetcher, extraction, query/intent parser, ranking, index/store, market cache, tests and evaluation artifacts. The old normal CLI constructed a persistent SQLite/index engine before searching. Local ranking could be followed by limited discovery and persistent page ingestion/reindexing. SearXNG was optional/unconfigured and its legacy 500ms result wait could discard slower sources. Remote Wikimedia was disabled. The Ramayan query found no relevant page among 821 local documents and had no general discovery source.

A large local corpus or GPU does not fix that missing source. The new path discovers URLs through configured general providers and fetches a small selection without needing to build a corpus.

## Files changed

- New `ownsearch/coordinator.py`: shared live CLI/API/agent coordinator, finite source workers, per-source/global cutoffs, partial responses, optional memory cache/local accelerator, diagnostics, transient `/fetch`, source excerpts and metrics.
- New `ownsearch/webproviders.py`: SearXNG and optional Brave web/image JSON adapters, schema checks, rate spacing, cooldown, key redaction, narrowly scoped local-instance access, finance/feed wrappers.
- New `ownsearch/webmodels.py`: typed request/candidate models, validated link syntax, short plain-text metadata, provenance and media fields.
- New `ownsearch/webfetch.py`: shared request/decoded-byte budgets, origin locks/delays/robots, bounded parallel enrichment, redirect/canonical metadata, request-only page contents.
- New `ownsearch/webranking.py`: small in-memory BM25/feature ranking reusing existing weights/evidence helpers; explicit filters, named-subject aboutness, finance/docs relevance, freshness and URL/content deduplication.
- `ownsearch/config.py`: live defaults and finite resource/cache/provider controls.
- `ownsearch/cli.py`, `ownsearch/server.py`, `ownsearch/engine.py`: connect default CLI search, API serving and agent facade to the coordinator; preserve explicit local `SearchEngine` and offline CLI. Add `providers`, `--no-fetch`, `--images`, `--answer`, live statuses and transient fetch behavior.
- `ownsearch/fetcher.py`: preserve meaningful query strings when requested; validate original redirect URLs and remove caller credentials across origins.
- `ownsearch/market.py`: optional request-local cache mode, preserving quote/history validation and disclaimers without opening SQLite in live mode.
- `ownsearch/extract/__init__.py`, `ownsearch/extract/html.py`: distinguish explicit publication metadata from URL-inferred dates; expose Twitter image metadata. Conflicting provider/page dates retain provenance and explicit page metadata governs freshness.
- `ownsearch/providers/__init__.py`: worker response type admits typed source batches while preserving legacy list responses.
- New `tests/test_live_web.py`, `tests/test_live_http.py`: 41 additional acceptance tests including actual localhost provider/page/API flows.
- New `scripts/eval_live_web.py`, `eval/live_web_queries.example.jsonl`: record live runs, assess independent reviewed relevance, and separately assess hash-bound answer/citation judgments. The eight example cases are intentionally **unreviewed**.
- `.env.example`, `.gitignore`, `README.md`, `main.md`, `docs/progress.md`, `docs/LIVE_WEB_PLAN.md`, `docs/LIVE_WEB.md`: configuration, credential exclusions, architecture, storage policy, compatibility and evaluation procedure. `pipeline.md` was read and preserved unchanged.

No existing corpus, credential file, branch or old crawler/index capability was deleted. No commit, merge, push or public deployment was performed.

## New real request flow

```text
query validation + deadline + optional memory result cache
  -> bundled query/intent/language/date/operator parser
  -> concurrent configured general providers + matching finance/news sources
     + explicitly enabled existing local accelerator
  -> candidate URL validation, normalization and provenance merge
  -> query/phrase/entity/date/source constraints + in-memory candidate scoring
  -> bounded selected-page fetching with robots, pinned DNS/IP checks and shared limits
  -> safe HTML/plain-text extraction (no JavaScript/OCR execution)
  -> evidence-aware reranking, duplicate/weak-result filtering
  -> source-linked results and optional cited source excerpt / financial answer
  -> actual provider/fetch status, partial-work state, timings and limitations
```

There is no persistent ingestion/reindex step in this path. Page contents are request-local; the optional bounded memory result cache is disabled by default. The old local index can accelerate searches only when explicitly enabled. API key files remain optional service configuration, not a document corpus.

Live `/fetch` returns bounded transient document-shaped content with null IDs and no indexing. Persistent `/crawl`, `/ingest` and `/feedback` return 409 in live mode; the old endpoints remain available through an explicit local-mode service. Search-scoped keys can query configured search providers; page fetching requires fetch/admin permission. The normal CLI no longer describes external results as matches in a local database.

## Provider activation

The checkout has **neither a SearXNG endpoint nor a Brave key**. The local Docker client is present but its configured Docker Desktop socket does not exist, so an instance could not be exercised. No provider endpoint, key or successful public search was invented.

For SearXNG, first run an authorized instance with JSON output enabled, then set its actual root URL:

```bash
export OWNSEARCH_SEARXNG_URL=http://127.0.0.1:8888
export OWNSEARCH_SEARXNG_ALLOW_PRIVATE=true
python3 main.py providers --check
python3 main.py search "your own unfamiliar query" --pretty
```

The localhost example is usable only when a service is actually running there. Follow the official setup/API links and operating constraints in [LIVE_WEB.md](LIVE_WEB.md). Alternatively supply your own `OWNSEARCH_BRAVE_API_KEY`; account quotas and possible charges apply, and there are no automatic billable retries. No paid service is mandatory or enabled without configuration. A general discovery source is necessary for broad coverage; fetching cannot locate arbitrary relevant URLs by itself.

## Before and after

| Scenario | Before | Implemented behavior / evidence |
| --- | --- | --- |
| Unknown topic with no local corpus | Local engine/corpus dependency; zero results without a discovery source | A mocked general provider returns a result with SQLite patched to fail and no data directory created. |
| Existing useful local result | Discovery could be skipped/truncated | Explicit local and general sources both run; tests verify overlapping provider execution. |
| One slow/failed provider | Could hide late useful results or force fallback | Other provider results survive; unfinished/timeout work is attributed and late results ignored. |
| Selected live page | Fetch -> persist -> index -> search again | Fetch -> request-only extraction -> rerank -> output; zero persistent page writes. |
| Fetch denied/fails | Discovery/reindex needed for useful output | Relevant provider snippet remains labeled not fetched/error; no fabricated page content. |
| Exact Ramayan command, current unconfigured checkout | 0 local results and vague linking error | Still no claim of a web result: explicit general-provider-unavailable message, no local corpus dependency and no existing data mtime changes. |
| Citation/answer | Specialized direct answers, incomplete fact corroboration | Yahoo answers preserved; optional generic answer is an actual cited source excerpt, not an assertion of independently verified truth. |

## Commands actually run and results

Tests were run with clean temporary working directories and actual-source `PYTHONPATH` to avoid opening the user's existing corpus through legacy test defaults.

- Before implementation: `python3 -m unittest discover -s tests -t .` in the disposable source copy: **172 passed, 42.325s**. An initial sandbox-only attempt could not bind localhost sockets/access the existing database; it was rerun with the required local test permissions.
- New acceptance tests: `python3 -m unittest tests.test_live_web tests.test_live_http -q`: **41 passed, 4.425s** in the prepared copy.
- Actual final source, standard-library profile: `PYTHONPATH=/home/pc-117/Documents/own_web_search_engine python3 -m unittest discover -s /home/pc-117/Documents/own_web_search_engine/tests -t /home/pc-117/Documents/own_web_search_engine`: **213 passed, 50.512s**.
- Actual final source, base dependencies: the same discovery command using the previously installed base-profile interpreter: **213 passed, 51.475s**.
- Actual `python3 main.py providers`: general discovery correctly reported **not configured**, with no keys printed.
- Actual user Ramayan command: exited successfully, reported unavailable general discovery; all existing `data/` file mtimes were unchanged. This is a configuration diagnosis, not a relevance pass.
- `python3 eval/run_eval.py --output ...`: actual-source local fixture evaluation completed; scores below. This remains an optional local-engine benchmark.
- `scripts/eval_live_web.py --queries eval/live_web_queries.example.jsonl --no-fetch --output ...`, with market/feeds explicitly disabled: eight unconfigured-source records, **zero reviewed queries**, no accuracy score/green flag.
- Python syntax checks: 66 runtime modules parsed; compileall passed. No lint/type-check tool is configured/installed, so no separate lint/type-check pass is claimed.
- `git diff --check`: passed; additional trailing-whitespace inspection included new source files.
- Final wheel built and installed in an isolated target. All **66 packaged runtime modules match the actual checkout**; installed provider/coordinator smoke returned a mocked result without creating a data directory. The first no-build-isolation attempt lacked setuptools; the declared isolated build succeeded.

Artifacts: `docs/evaluation/live-web/` contains final actual-source test logs, CLI smoke, local fixture results, unconfigured example records, local-HTTP timing sample and wheel verification.

## Acceptance criteria

| # | Check | Result |
| --- | --- | --- |
| 1 | Unknown/empty local corpus with configured mocked provider | Pass; no SQLite or data directory required |
| 2 | Independent provider execution overlaps | Pass; synchronization-barrier test |
| 3 | One provider fails/times out, another succeeds | Pass; successful rows retained |
| 4 | No provider configured | Pass; explicit unavailable status, no pretend search |
| 5 | Selected page fetch concurrency/deadline/size/redirect limits | Pass; shared budgets and local HTTP tests |
| 6 | Failed fetch retains a useful snippet with accurate status | Pass |
| 7 | URL/fragment, canonical, redirected identity and near-copy deduplication | Pass |
| 8 | Relevant inspected evidence can outrank a weak snippet | Pass; incidental named-entity and unrelated finance-page regressions |
| 9 | Freshness applies to temporal requests, not every query | Pass; explicit date/language/operator constraints and conflicting metadata checks |
| 10 | Images are supplied metadata with real provenance | Pass with mocked provider schemas; public image API not run |
| 11 | Answer citations refer to an actual source/result | Pass for supported extractive mode; no unrestricted LLM synthesis |
| 12 | Unsafe IP/DNS/redirect/scheme, robots and size rejection | Pass; existing safe fetcher tests plus new live tests retained |
| 13 | Slow sources/fetches bounded, partial output honest | Pass locally; arbitrary public-host latency not certified |
| 14 | CLI/API compatibility and old feature tests | Pass; documented live-mode null IDs/storage-endpoint changes |
| 15 | No false accuracy claim | Pass; unreviewed cases have null metrics; answer review separate |

## Measured latency and ranking

**Actual localhost HTTP provider + selected HTML page**, no result cache, deterministic test DNS, test-only intranet permission, host delay zero: **20 samples**, p50 **110.85ms**, p95 **118.513ms**, maximum **124.84ms**. Server setup/shutdown occurs outside the measured search duration. These are coordinator/local-fixture timings, not real public-internet latency or the production two-second host-delay configuration.

Optional local fixture benchmark (57 synthetic documents, 59 queries; two expected-empty queries excluded from ranking means) remains **P@5 0.2000, MRR@10 0.947368, NDCG@10 0.914425**. It is unchanged from the prior local-engine checkpoint and does not measure new general-web coverage. No before/after public ranking comparison is available without a working provider and independent labels.

## Remaining limitations

- Public SearXNG/Brave integration, real query coverage, real image results, cold public-web latency and provider quotas need verification after configuration.
- 300–500 independently judged diverse holdout queries, category/language breakdowns and separate human answer/citation labels are not available. No 90% claim can be made.
- Generic answer mode is extractive. It does not fully answer every complex question, independently corroborate historical claims, resolve all source conflicts, translate every language or use a universally accurate intent model.
- The live path supports HTML/plain text; PDF/Office/OCR stay in explicit local ingestion. Failed/unsupported fetches may leave useful provider metadata but less evidence.
- No SSE/token streaming or background enrichment is implemented in the new path. It returns one bounded final response with explicit unfinished source status. Python cannot forcibly stop arbitrary blocked extension code; capacity/deadlines/cooperative cancellation and ignored late output are used.
- Ranking weights/admission thresholds are engineering defaults reused from the existing engine, not calibrated probabilities or independent web-relevance proof. Conservative operators/metadata checks can omit relevant pages with insufficient evidence.
- Optional old entity/vector/translation models remain local capabilities; they are not silently downloaded or required by live search. Provider language/spelling coverage remains an external dependency.

The implementation removes the mandatory corpus dependency. Real-world usefulness remains dependent on configuring and validating a lawful general discovery source.
