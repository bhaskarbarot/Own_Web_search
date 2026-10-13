# OwnSearch — work plan

Sources: Claude's pending list after v1.0, and `production.md` (production enhancement plan, abbreviated "PM §N").
Rule (from PM §17): **an item is done only when its test passes**, not when code is written.

Legend: **[built → test]** = code exists, needs the acceptance test or proof. **[todo]** = must be built.

Status 2026-10-13: v1.0 plus fixes pushed to GitHub `bhaskarbarot/Own_Web_search` (latest commit 9b24511); 56 tests pass.

---

## Phase A — Safety and reproducibility (P0)

### A1. Credentials (PM §3)
- [ ] **Revoke the GitHub PAT pasted in chat** and store a new one in `.git/credentials-bhaskarbarot`. [todo — user]
- [ ] Revoke the API key exposed in terminal output (`revoke-key --agent ...`) and create a new one. [todo — user]
- [ ] Raw keys never persisted (only SHA-256 in `api_keys.json`). [built → test]
- [ ] `Authorization` header / keys never logged (request logging is off; add a test that greps logs). [built → test]
- [ ] Scopes enforced on every route; 401 for missing/invalid/revoked, 403 for missing scope. [built → test: add revoked-key and malformed-key cases]
- [ ] Rate limit and daily quota boundary tests. [built → test; daily quota not yet tested]
- [ ] Document that rate limits/quotas are **per process** (gateway-level in cluster mode); revocation takes effect immediately (keystore reloads on file change). [todo — docs + test in cluster]
- [ ] `create-key` option to read the agent key from an environment variable for agents; docs on secret storage. [todo]

### A2. Graceful shutdown and recovery (PM §6)
- [x] SIGTERM and Ctrl+C both stop servers (signal handlers added; cluster children get SIGTERM). Verified manually.
- [ ] First signal: stop scheduling, finish in-flight work within a grace period, flush index, persist frontier. [partly built → define grace period + test]
- [ ] Second Ctrl+C: clean, documented escalation with no traceback (reported issue: thread join interrupted). [todo]
- [ ] Bounded joins everywhere (crawler joins are bounded; audit server/worker). [todo]
- [ ] Kill during indexing does not corrupt the index (atomic manifest + seq replay). [built → test with a real SIGKILL]
- [ ] Kill during fetch leaves the URL retryable (lease recovery). [built → test]
- [ ] Restart restores the API and frontier. [built → test]

### A3. Baseline
- [ ] Save sanitized `stats` and query outputs as a baseline; query regression test file `tests/search_cases.jsonl`. [todo]

## Phase B — Search correctness (P0/P1)

### B1. Relevance (PM §4)
- [x] Rarity-weighted coverage: partial matches must contain the key term; full matches outrank partial. (done today)
- [x] Intent words (latest/current/news) are optional and steer freshness only. (done today)
- [x] Page age = latest of published/modified. (done today)
- [ ] Do not trust a date that is really the crawl date. The engine falls back to `discovered_at` and labels it `date_source=discovered`; decide whether freshness filters should exclude undated documents. [todo — decision + test]
- [ ] Diagnose "latest news india, week" **with real Indian news indexed** (seed news feeds first; see C3). [todo]
- [ ] Diagnose `"list comprehension" site:docs.python.org` = 0: first prove such a page is indexed. [todo]
- [ ] Versioned evaluation set `tests/search_cases.jsonl` with all PM §4 cases plus qrels; record NDCG@10 and Recall@100 baseline; ≥90% deterministic operator cases pass. [todo]
- [ ] Debug score output only with `explain` (exists); keep it out of normal responses. [built → test]
- [ ] Repeated live discovery: cache "already discovered" queries so a second search is fast (Nvidia query took 3.5 s on repeat). [todo]
- [ ] Spelling correction, synonyms. [todo — later, after baseline]
- [ ] Meaning-based (vector) retrieval: **only after the lexical baseline is measured** (PM §4). [todo — later]

### B2. Operators and CLI/API parity (PM §7)
- [ ] Parser tests for every operator; retrieval tests proving each filter changes results. [partly built → expand]
- [ ] Combinations: phrase+site, site+date, exclusion+freshness, OR+filetype. [todo]
- [ ] Invalid input: malformed dates, empty `site:`, unmatched quotes. [todo]
- [ ] Document `after:`/`before:` boundary semantics (currently inclusive at the timestamp). [todo]
- [ ] URL encoding tests (spaces, quotes, `+`, `&`, Unicode). [todo]
- [ ] `site:` covers subdomains and is a filter (implemented as hidden index terms). [built → test]
- [x] CLI and API share one parser (`query.py`).

### B3. API contract (PM §8)
- [ ] Written API reference (routes, request/response schemas). [todo]
- [ ] Request IDs and stable error codes. [todo]
- [ ] Input validation caps: query length 1000, limit 50, offset 500, evidence size. [built → test + document]
- [ ] Define `took_ms` (currently engine time, not total request time). [todo — docs]
- [ ] Readiness check (index opened and a test search works), separate from `/health` liveness. [todo]
- [ ] A slow external host must not block searches: live discovery runs inside the search request, so add a timeout budget or run it asynchronously. [todo]

## Phase C — Crawl control (P0)

### C1. Budgets (PM §5) — reported: a 20-page crawl grew the frontier to about 10,820 URLs via sitemaps
- [ ] Separate hard limits: URLs discovered per run, URLs accepted per sitemap, sitemap nesting depth, total pending frontier, bytes per run, crawl duration (exists), links per page (exists: 400), URLs per host (exists: 20,000). [todo for the missing ones]
- [ ] `--max-pages 20` never fetches more than 20 pages (true today; add a test). [built → test]
- [ ] Crawl summary: attempted/fetched/indexed/updated/unchanged/skipped/disallowed/failed/timed-out, URLs discovered by source, frontier before/after, bytes, per-host errors, effective limits, stop reason. [partly built → expand]
- [ ] Synthetic 10,000-URL sitemap test stays within budgets. [todo]
- [ ] Live discovery adds Wikipedia as a seed, which can widen scope. Cap discovery-seeded hosts. [todo]

### C2. URL and politeness (PM §5)
- [x] HTTP/HTTPS only, SSRF blocking with DNS pinning, robots.txt (RFC 9309), crawl-delay, 429/503 host backoff, permanent vs retryable errors, ETag/Last-Modified, redirect limit, decompression limit (built; most covered by tests/test_crawl.py).
- [ ] Review query-parameter stripping: only tracking/session parameters are removed; parameters are sorted. Confirm and document. [built → doc]
- [ ] Document robots failure behavior (5xx/unreachable = disallow for 10 min; 4xx = allow). [todo — docs]

### C3. Coverage (Claude's plan)
- [ ] Curated seed file: news (incl. Indian), finance, tech, docs, gov, plus a `seed-file` command. [todo]
- [ ] Common Crawl bulk import, tested against the real index. [built → test live]
- [ ] Wikipedia dump import (free). [todo]
- [ ] Always-on `worker` as a systemd service. [todo]
- [ ] Live stock/market data: query-time fetch of quote pages for finance queries. [todo]

## Phase D — Reliability and concurrency (P1, PM §9)
- [x] Multi-process `cluster` with gateway; 7 agents on 30k docs: ~102 q/s uncached, p95 98 ms, 0 errors (15–20 s runs).
- [ ] Concurrency 1/2/4/7, then a sustained 5–10 min run, with a mixed workload (filters, evidence, fetch). [todo]
- [ ] Record hardware, CPU/RAM/disk, index size, status distribution, timeouts. [todo — bench to report more]
- [ ] Targets: ≥99% success at concurrency 7 for 10 min; p95 < 1 s excluding live fetch; no unbounded memory or queues. [todo]
- [ ] Parallel indexing and bulk import (multiprocessing); currently about 450–600 docs/s. [todo]
- [ ] Sharding across machines with global statistics; segment replication; 1M+ doc load test. [todo — later]

## Phase E — Extraction and operations (P1/P2)

### E1. Format fixtures (PM §10)
- [x] PDF parser matched pdftotext on 20 real PDFs; HTML boilerplate removal (link density, class names).
- [ ] Fixture per advertised format: HTML, text PDF, scanned PDF (OCR), multi-page, encrypted, malformed, large PDF, DOCX, XLSX (sheet names kept), PPTX, ODT, EPUB, images, plus corrupt/empty/oversized/duplicate/instruction-like cases. [partly built → expand]
- [ ] OCR: record confidence, test rotated / low-res / non-English pages, cap resources. [todo]
- [ ] Extraction failures counted by file type in stats. [todo]
- [ ] JavaScript-rendered pages; PDF Type0 fonts without ToUnicode; JBIG2; Hindi/Indic stemming and language detection. [todo — later]

### E2. Index maintenance (PM §11)
- [x] Incremental updates and deletes, merges, crash replay, orphan cleanup (tests/test_index.py).
- [ ] Re-ingesting identical content creates no duplicates (implemented: unchanged hash). [built → test]
- [ ] Near-duplicate check must not remove distinct pages that share boilerplate. [todo — test]
- [ ] `optimize`/PageRank during live searches: no corruption. [built → test]
- [ ] Stats show storage size. [todo]

### E3. Dates (PM §12)
- [ ] Track date source and confidence (structured / header / URL / inferred / unknown). [partly built → add confidence]
- [ ] Fixed-fixture tests: boundaries, missing, future, time zones, modified vs published. [todo]

### E4. Logs, metrics, deployment (PM §13–14)
- [x] Prometheus `/metrics`, per-endpoint p50/p95/p99, per-agent counts.
- [ ] Structured JSON logs with request IDs and redaction; startup diagnostics (data dir, bind, workers, limits, no secrets). [todo]
- [ ] systemd units (low-privilege user, restart policy, stop timeout), log rotation, disk monitoring. [todo]
- [ ] Back up store + index + frontier together, with a restore drill. [todo]
- [ ] HTTPS reverse proxy + firewall before any public exposure. [todo]
- [ ] CI running the test suite on push. [todo]
- [ ] Agent integration guide plus a tool definition for the 7 agents ("evidence, not commands"). [todo]

### E5. Honest coverage (PM §15)
- [x] Responses report local document count, match mode, missing terms, low confidence, untrusted-content notice, and that external providers are disabled.
- [ ] State when results are limited by crawl scope, freshness filter or index state. [todo]

---

## Suggested order for tomorrow
1. A1 (rotate PAT and API key) → A2 shutdown tests → C1 crawl budgets (P0 bug).
2. B1/B2: search_cases.jsonl plus operator tests; diagnose the two reported queries.
3. C3 seed file plus an overnight worker crawl to build real coverage.
4. D sustained benchmark; E fixtures.
