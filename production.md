# OwnSearch Production Enhancement Plan

**Project:** OwnSearch --- self-hosted search engine for AI agents\
**Purpose:** Actionable enhancement plan based on the CLI output, API
response, and crawl/search logs shared so far.

> **Important:** This document is based on observed behavior, not a
> fresh inspection of the current source tree. Inspect the actual
> implementation before editing it. Treat the requirements below as
> acceptance criteria, not as claims that the features already exist.

## 1. Current status

### Confirmed by the supplied tests

-   `main.py` exposes search, crawl, seed, serve, create-key, list-keys,
    revoke-key, benchmark, evaluation, indexing, and maintenance
    commands.
-   `create-key` requires `--agent`.
-   `GET /search?q=python&limit=3` returned `HTTP 200 OK` with a valid
    Bearer key.
-   The API response contains ranked results, snippets, evidence
    passages, coverage information, query-understanding metadata,
    provider status, and `took_ms`.
-   One request completed in about **82 ms** with **697 indexed
    documents**. This is a single-request smoke test, not a capacity
    benchmark.
-   The server staying in the foreground when running
    `python3 main.py serve --crawl-threads 1` is normal.

### Issues suggested by the logs

1.  **Relevance/freshness:** `latest news india` with a week freshness
    filter returned Python-related pages. Investigate parsing, corpus
    coverage, filtering, and ranking.
2.  **Phrase/site filter:** `"list comprehension" site:docs.python.org`
    returned zero results in a small index. First verify that a matching
    document is indexed; then inspect parsing and filter stages.
3.  **Unbounded discovery risk:** a crawl limited to 20 fetched pages
    reportedly discovered nearly 10,000 sitemap URLs and grew the
    frontier to roughly 10,820 URLs.
4.  **Shutdown:** a second Ctrl+C reportedly interrupted a thread join
    during shutdown.
5.  **Credential exposure:** an API key was pasted into shared output.
    Revoke it and create a replacement; do not reuse or repost it.
6.  **Scale unproven:** seven-agent concurrency, sustained load,
    large-corpus quality, and PDF/Office/OCR quality have not yet been
    demonstrated.
7.  **Coverage honesty:** the response showed `local_index: true` and
    external providers disabled. Do not imply that a local index is the
    entire live web.

**Current verdict:** the API smoke test passes. Production readiness is
not yet established.

## 2. Priority order

  ------------------------------------------------------------------------
  Priority                Work                    Completion evidence
  ----------------------- ----------------------- ------------------------
  P0                      Revoke exposed key;     Old key rejected; new
                          test authentication and key works; no secrets in
                          scopes                  logs

  P0                      Fix/measure search      Relevance test set
                          relevance               passes

  P0                      Enforce crawl and       A small crawl cannot
                          sitemap budgets         flood the frontier

  P0                      Graceful shutdown and   SIGINT/SIGTERM/restart
                          recovery                tests pass

  P1                      Verify operators and    Parser, CLI, API, and
                          freshness               retrieval tests pass

  P1                      Seven-agent load        Latency/error targets
                          testing                 met on target hardware

  P1                      Extraction/evidence     Each advertised format
                          fixtures                has a passing fixture

  P2                      Monitoring, backups,    Recovery and operational
                          deployment hardening    checks demonstrated
  ------------------------------------------------------------------------

------------------------------------------------------------------------

## 3. P0 --- API-key security

### Required changes

-   Revoke the key exposed in the shared terminal output immediately.
-   Use a distinct key per agent/service so it can be audited, limited,
    and revoked independently.
-   Store keys in environment variables or a secrets manager. Never
    commit them to source control or put them in logs/screenshots.
-   The CLI says only a hash is saved; verify that raw keys are never
    persisted.
-   Never log the `Authorization` header or full key.
-   Enforce scopes on every route. A key with `search,fetch` must not be
    able to crawl, ingest, administer keys, or use admin-only actions.
-   Return `401` for missing/invalid/revoked credentials and `403` for a
    valid key without the required scope.
-   Enforce rate limits and daily quotas. Test whether they are shared
    across cluster workers or are per-process, and document the actual
    behavior.

### Commands

Check the exact revoke syntax first:

``` bash
python3 main.py revoke-key --help
python3 main.py list-keys --help
```

Then revoke the exposed key and create a replacement:

``` bash
python3 main.py create-key --agent agent1 --rps 10 --burst 20 --daily-quota 0 --scopes search,fetch
```

Keep the new key private.

### Security acceptance tests

-   [ ] Exposed key returns `401` after revocation.
-   [ ] New key can search.
-   [ ] `search,fetch` key cannot access crawl/ingest/admin endpoints.
-   [ ] Missing and malformed keys are rejected.
-   [ ] Logs never contain raw API keys or Authorization headers.
-   [ ] Rate limit and daily quota boundaries are tested.
-   [ ] Revocation works promptly in single-process and cluster modes.

------------------------------------------------------------------------

## 4. P0 --- Search relevance and ranking

### Observed problem

`latest news india` with a week filter returned Python-related pages.
This may be caused by query parsing, an irrelevant candidate set,
missing Indian-news coverage, incorrect freshness handling, or ranking.
Diagnose each stage; do not fix this merely by boosting newer pages.

### Required search pipeline

Make these stages explicit and testable: 1. Parse query and operators.
2. Normalize terms consistently with indexing. 3. Separate required
terms, optional terms, phrases, exclusions, site/filetype/language/date
filters, and freshness intent. 4. Retrieve candidates. 5. Apply hard
filters where appropriate. 6. Rank by topical relevance. 7. Apply
freshness as a controlled signal only when requested or confidently
inferred. 8. Deduplicate near-identical results and apply per-host caps.
9. Build query-relevant snippets/evidence. 10. Return honest local-index
coverage information.

### Ranking requirements

-   Exact phrase, title, URL, and term-proximity matches should
    contribute meaningfully.
-   A document should not rank highly merely because it contains one
    common word.
-   If the existing ranker lacks a strong lexical baseline, evaluate
    BM25 or an equivalent method before replacing the ranker.
-   PageRank/popularity should be secondary to topical relevance.
-   Explicit `after:` and `before:` constraints must be applied as date
    filters with documented boundary semantics.
-   A new but irrelevant page must not outrank a strongly relevant page
    solely because it is new.
-   Do not trust a publication date if it is actually the crawl date or
    an uncertain modified date.
-   Provide debug/evaluation output for score components without
    exposing it unnecessarily to normal API users.
-   Do not add vector search or a vector database as a reflexive fix.
    Establish and measure the lexical baseline first.

### Build a versioned evaluation set

Create a file such as `tests/search_cases.jsonl`. Each case should
record the query, known relevant document/domain, expected filters, and
expected behavior. Include: - `python asyncio` -
`"list comprehension" site:docs.python.org` - `latest news india` with a
one-week filter - `site:docs.python.org asyncio` - `python -packaging` -
`intitle:asyncio python` - `filetype:pdf python tutorial` -
`after:2026-10-01 python` - `before:2026-01-01 python` -
`python OR javascript` - a query intentionally absent from the local
index

For deterministic tests, use known documents that are definitely
indexed. For the Indian-news test, seed a small, documented set of
relevant news pages and verify their dates; do not judge the ranking
against an index that contains no relevant news.

### Acceptance criteria

-   At least 90% of deterministic operator cases behave as expected on
    the test corpus.
-   Human-judged relevance is recorded for the top results and compared
    against a saved baseline.
-   The Indian-news query does not put Python documentation at the top
    when relevant news pages are present.
-   If the local index lacks suitable documents, coverage messaging says
    so.
-   Every ranking change is tested for regressions.

------------------------------------------------------------------------

## 5. P0 --- Crawl budgets and frontier control

### Observed problem

A crawl with `--max-pages 20` reportedly expanded the frontier to
roughly 10,820 URLs after sitemap discovery. The page-fetch limit must
not permit unbounded URL discovery.

### Enforce separate budgets

Configure and test independent limits for: - Pages fetched per run. -
URLs discovered per run. - URLs accepted from one sitemap. - Sitemap
nesting depth. - Links accepted from one page. - Total pending frontier
size. - URLs per host/domain. - Response bytes per page and total bytes
per run. - Total crawl duration. - Redirects followed. - Retries per
URL. - Concurrent requests per host and total workers. - Maximum
decompressed response size.

Use conservative defaults. `--max-pages 20` must cap pages fetched by
that run; sitemap and link discovery must also have separate hard caps.
Print the effective limits in the crawl summary.

### URL and politeness requirements

-   Track URL discovery source: seed, page link, sitemap, RSS/Atom,
    redirect, or retry.
-   Normalize scheme/host casing and remove fragments. Handle default
    ports consistently.
-   Do not blindly strip query parameters; some parameters identify
    actual content.
-   Restrict schemes to HTTP/HTTPS.
-   Respect `robots.txt` and supported crawl-delay rules. Document
    behavior if robots retrieval fails.
-   Use host-level queues, delays, and backoff for `429`, `503`, and
    transient errors.
-   Distinguish permanent errors from retryable errors.
-   Use `ETag`/`Last-Modified` conditional requests where useful.
-   Keep crawl scope explicit: seed URL, host, registrable domain, or
    allowlist. Do not silently widen scope because a sitemap links
    elsewhere.
-   If the HTTP API can fetch user-supplied URLs, prevent SSRF to
    loopback/private/link-local addresses unless explicitly enabled for
    trusted local use.
-   Limit redirects, downloads, decompression, and processing time to
    reduce abuse risk.

### Crawl summary should include

Attempted, fetched, indexed, updated, unchanged, skipped, disallowed,
failed, timed-out; URLs discovered by source; frontier size
before/after; bytes downloaded; per-host errors; elapsed time; active
limits; and why the run stopped.

### Acceptance criteria

-   A synthetic 10,000-URL sitemap cannot exceed configured
    sitemap/frontier budgets.
-   A 20-page run never fetches more than 20 pages.
-   Byte, duration, redirect, retry, and frontier limits are enforced.
-   Host politeness and robots exclusions pass tests.
-   Interrupted jobs remain recoverable.

------------------------------------------------------------------------

## 6. P0 --- Graceful shutdown and recovery

### Required behavior

-   On first SIGINT/SIGTERM, stop accepting/scheduling new work, then
    let current work finish or cancel it safely within a defined grace
    period.
-   Flush pending index changes and persist frontier state.
-   Close sessions, sockets, files, and workers.
-   Join workers with bounded waits; do not wait indefinitely.
-   On a second Ctrl+C, escalate predictably and avoid a confusing
    traceback where feasible.
-   Ensure partial fetches/index writes cannot corrupt persistent data.
-   On restart, recover in-progress URLs and pending writes safely.
-   Avoid holding global storage/index locks while waiting on slow
    network calls or workers.
-   Use atomic replacement or transactional writes for critical state
    where applicable.

### Tests

-   [ ] One Ctrl+C exits within the documented grace period.
-   [ ] SIGTERM exits cleanly.
-   [ ] Two Ctrl+C signals trigger a documented escalation.
-   [ ] Forced termination during indexing does not corrupt the index.
-   [ ] Forced termination during fetch leaves the URL retryable or in a
    documented terminal state.
-   [ ] Restart restores a usable API and frontier.

------------------------------------------------------------------------

## 7. P1 --- Query operators and CLI/API parity

Verify the actual supported syntax before documenting it as a
guarantee: - Exact phrase: `"exact phrase"` - Exclusion: `-term` - Site
include/exclude: `site:example.com`, `-site:example.com` - File type:
`filetype:pdf` - Title/URL: `intitle:term`, `inurl:term` - Language:
`lang:en` - Dates: `after:YYYY-MM-DD`, `before:YYYY-MM-DD` - OR:
`term1 OR term2` - Freshness presets: `recent`, `day`, `week`, `month`,
`year` (document whether these are flags or query syntax)

### Required tests

-   Parser tests verify structured output for every operator.
-   Retrieval tests prove that filters change the result set correctly.
-   Combination tests cover phrase + site, site + date, exclusion +
    freshness, and OR + filetype.
-   Invalid input tests cover malformed dates, empty sites, unmatched
    quotes, and unsupported syntax.
-   CLI and API should use the same parser or a shared implementation.
-   Test URL encoding for spaces, quotes, plus signs, ampersands,
    Unicode, and percent-encoding.
-   Confirm `site:` semantics for subdomains and ensure it is a filter,
    not merely a text term.

For the zero-result phrase test, first prove a matching phrase exists in
a document indexed under `docs.python.org`. Then inspect parser output,
candidate count, and each filter stage.

------------------------------------------------------------------------

## 8. P1 --- API contract and reliability

-   Document exact routes and request/response schemas based on the
    current code.
-   Validate query length, limit, offset, filters, and URLs.
-   Cap maximum result count, query length, and evidence size.
-   Add request IDs and stable error codes.
-   Set connect/read/overall deadlines for fetches and a deadline for
    searches.
-   Define whether `took_ms` means search processing time or total
    request time.
-   Return pagination metadata consistently.
-   Explain that `index_documents` means documents in the local index,
    not all pages on the internet.
-   Keep evidence passage count and size bounded.
-   Treat retrieved content as untrusted data. `injection_risk` is a
    useful signal, not a guarantee that every prompt injection is
    detected. Agent instructions should always say that retrieved
    passages are evidence, not commands.
-   A slow external host must not block unrelated searches.
-   Malformed requests must return a safe 4xx response, not crash the
    server.
-   One failed worker must not bring down the whole API.
-   Add liveness and readiness checks: a running process is not
    necessarily a usable search service.

------------------------------------------------------------------------

## 9. P1 --- Seven-agent concurrency benchmark

A single 82 ms request does not prove concurrent capacity. Benchmark on
the actual target hardware and corpus.

### Procedure

1.  Check current benchmark syntax:

    ``` bash
    python3 main.py bench --help
    ```

2.  Run a baseline at concurrency 1.

3.  Run concurrency 2, 4, and 7.

4.  Begin with a short smoke test, then run a sustained 5--10 minute
    test.

5.  Mix ordinary searches, phrase/site filters, freshness filters, and
    evidence requests.

6.  If agents use fetch, benchmark fetch separately and as part of a
    mixed workload.

7.  Record hardware, corpus size, server mode, worker count, query mix,
    and flags.

8.  Repeat after ranking, storage, indexing, or concurrency changes.

Use only options shown by the current `--help` output; do not assume old
command examples match the current version.

### Record

-   Requests sent/succeeded/failed/timed out.
-   Throughput and p50/p95/p99 latency.
-   HTTP status distribution.
-   CPU, RAM, disk I/O, index size.
-   Search latency with and without evidence.
-   Queue/frontier growth and worker starvation.

### Proposed initial targets

These are goals to validate, not claims about current performance: - No
crash or index corruption in the test. - At least 99% of valid requests
succeed during a 10-minute concurrency-7 test. - p95 local search
latency under 1 second on the agreed baseline hardware/corpus, excluding
live network fetch time. - No unbounded memory, queue, or pending-task
growth. - Every timeout/error is counted and diagnosable.

------------------------------------------------------------------------

## 10. P1 --- Content extraction and evidence

The CLI advertises HTML, PDF, DOCX, XLSX, PPTX, ODT, EPUB, text, and
images/OCR. Test every advertised format rather than assuming file
extension means successful extraction.

### HTML

-   Extract main content separately from navigation, footer, cookie
    banners, and repeated boilerplate where feasible.
-   Preserve headings and paragraph boundaries.
-   Normalize whitespace and Unicode safely.
-   Retain source URL and fetch timestamp.
-   Report empty/failed extraction rather than silently treating it as
    good content.

### PDF and office files

-   Test text PDFs, scanned PDFs, multi-page PDFs, malformed/encrypted
    PDFs, and large PDFs.
-   Preserve PDF page numbers in indexed passages.
-   Test DOCX, XLSX, PPTX, ODT, and EPUB independently.
-   Preserve spreadsheet sheet names and cell context.
-   Enforce file size, page count, decompression, and processing-time
    limits.
-   Record extraction failures by type.

### OCR

-   Verify required OCR dependencies and versions.
-   Test clean scans, rotated pages, low-resolution images, and
    non-English content if supported.
-   Record confidence when available; do not present low-confidence text
    as certain.
-   Limit OCR resource use so large files cannot exhaust the service.

### Evidence passages

-   Prefer passages containing query terms/phrases.
-   Preserve source URL, title, retrieval time, date and date-source,
    plus page/sheet metadata when relevant.
-   Do not merge unrelated text into a misleading passage.
-   Keep passage-to-document references stable.
-   Represent unknown dates as unknown; never invent dates.

Create small fixture files with known expected text and metadata for
every supported format. Include corrupt, empty, oversized, duplicate,
and instruction-like-content cases.

------------------------------------------------------------------------

## 11. P1/P2 --- Indexing, deduplication, and maintenance

-   Verify incremental indexing and repeated-ingestion behavior.
-   Separate canonical URL identity from content-level duplicate
    detection.
-   Track normalized URL, content hash, fetch time, modification time,
    status, and extraction status where applicable.
-   Test updates, deletions/tombstones, segment merges, and interrupted
    commits.
-   Ensure `optimize` and PageRank maintenance do not corrupt active
    searches.
-   Report active documents, pending deletions, segment count, index
    generation, and storage size in `stats`.
-   Define an optimization schedule/threshold so segment count does not
    grow indefinitely.
-   Back up index metadata, document store, and frontier together; test
    restoration.

Acceptance: - Re-ingesting identical content does not create unbounded
duplicate active documents. - Near-duplicate logic does not remove
distinct pages that share boilerplate. - Per-host caps do not hide every
useful result from a domain. - Updates become searchable within a
documented interval.

------------------------------------------------------------------------

## 12. P2 --- Date quality and freshness

Keep `published_at`, `fetched_at`, and `last_modified` distinct. Track
the source/confidence of a publication date: structured metadata,
visible date, HTTP header, inferred, or unknown.

-   Do not present crawl date as publication date.
-   Use timezone-aware timestamps and normalize internally to UTC.
-   Document inclusive/exclusive behavior for `after:` and `before:`.
-   Define how undated documents behave under freshness filters.
-   Treat future/ambiguous dates carefully.
-   Freshness ranking must not overpower topical relevance.
-   Explain that freshness depends on the local index and recrawl
    schedule.

Test date-window boundaries, missing dates, future dates, time zones,
and modified-versus-published dates using fixed test fixtures.

------------------------------------------------------------------------

## 13. P2 --- Logs, metrics, and diagnostics

### Structured logs

Include timestamp, severity, request ID, operation, duration, agent
identifier, status/error code, timeout, candidate/result counts, crawl
host/status, index generation, and active worker count where useful.

Do not log API keys, Authorization headers, full page bodies, or private
document content by default. Redact query parameters that may contain
sensitive information.

### Metrics

Track: - Request count and latency distribution. - Errors/timeouts by
route. - Active requests and queue length. - Per-agent rate-limit
hits. - Crawl success/failure rates and frontier size. - Document count,
segment count, commit duration, and storage size. - Extraction failures
by file type. - CPU, RAM, disk, and restarts.

Liveness should only establish that the process is alive. Readiness
should establish that storage/index initialized and a simple search can
be served. Startup diagnostics should report data directory, bind
address, workers, enabled providers, and crawl limits---never
credentials.

------------------------------------------------------------------------

## 14. Deployment and recovery

Before exposing the API beyond localhost: - Bind privately by default;
public listening must be explicit. - Use HTTPS/TLS at the service
boundary. - Restrict network access with a firewall. - Keep
admin/key-management routes unavailable to ordinary agent keys. - Run as
a dedicated low-privilege OS user. - Use a service supervisor with a
restart policy and graceful-stop timeout. - Monitor disk space and
protect against full-disk failure. - Back up index, store, and frontier
together; perform a restore drill. - Define data retention/deletion
policy for crawled content and logs. - Pin/update dependencies and run
automated tests in CI. - Remove secrets from Git and rotate any exposed
credentials. - Document recovery from machine restart, full disk,
corrupt segment, and failed crawl.

A localhost smoke test does not prove public deployment security.

------------------------------------------------------------------------

## 15. Honest coverage messaging

OwnSearch is a crawler and local index unless other discovery/search
providers are configured. It cannot guarantee that every page on the
internet is indexed or every query finds every relevant page.

Expose: - Active local document count. - Whether all required terms
matched or only partial terms. - Whether the topic appears
under-covered. - Whether external providers are disabled. - Whether
results are constrained by crawl scope, freshness, or index state.

A larger corpus helps only if pages are crawled politely, extracted
correctly, and ranked well. Fix relevance and crawl budgets before
scaling.

------------------------------------------------------------------------

## 16. Implementation phases

### Phase A --- Safety and reproducibility

1.  Revoke exposed key and rotate credentials.
2.  Test scopes, revocation, rate limits, and quotas.
3.  Save sanitized baseline stats and query outputs.
4.  Add a repeatable query regression test.
5.  Test shutdown and index recovery.

**Exit:** security/shutdown tests pass and baseline is reproducible.

### Phase B --- Search correctness

1.  Inspect parser and CLI/API parity.
2.  Diagnose the Indian-news/freshness failure.
3.  Diagnose phrase + site behavior using known indexed documents.
4.  Add qrels and record baseline ranking metrics.
5.  Test exclusions, dates, OR, filetype, language, title, and URL
    filters.

**Exit:** operator tests pass and relevance is measured.

### Phase C --- Crawl control

1.  Enforce separate page, discovery, sitemap, frontier, byte, host, and
    duration budgets.
2.  Add host politeness, retry/backoff, and error classification.
3.  Report effective limits and frontier changes.
4.  Test with a synthetic large sitemap and a controlled small site.

**Exit:** a small crawl cannot unexpectedly flood the frontier.

### Phase D --- Reliability and concurrency

1.  Benchmark concurrency 1/2/4/7.
2.  Record latency percentiles, throughput, errors, CPU/RAM, and disk.
3.  Fix bottlenecks revealed by measurements.
4.  Run a sustained load and restart/recovery test.

**Exit:** service targets pass on the intended hardware.

### Phase E --- Extraction and operations

1.  Add fixtures for every advertised format.
2.  Verify OCR and page/sheet evidence metadata.
3.  Add health checks, logs, and metrics.
4.  Test backup/restore.
5.  Document deployment and troubleshooting.

**Exit:** every advertised feature has a repeatable test and recovery is
demonstrated.

------------------------------------------------------------------------

## 17. Production checklist

-   [ ] Exposed API key revoked and replaced.
-   [ ] Scopes, revocation, quotas, and rate limits tested.
-   [ ] No secrets in logs, fixtures, source, or repository history.
-   [ ] Query parser and CLI/API semantics tested.
-   [ ] Freshness/news query returns relevant results when relevant
    documents are indexed.
-   [ ] Exact phrase/site test checked against known indexed content.
-   [ ] Page, sitemap, frontier, byte, host, and time budgets enforced.
-   [ ] Robots rules and politeness tested.
-   [ ] Ctrl+C, second Ctrl+C, SIGTERM, and recovery tested.
-   [ ] Seven-agent benchmark recorded.
-   [ ] PDF/Office/EPUB/OCR fixtures pass for each advertised format.
-   [ ] Health/readiness, safe errors, and metrics available.
-   [ ] Backup and restore tested.
-   [ ] Public deployment has TLS and network restrictions.
-   [ ] Coverage messaging accurately describes local-index limits.

Do not mark a task complete because code was written; mark it complete
only when its test passes.

## 18. What to provide for the next review

Share: 1. The updated source ZIP/repository snapshot, excluding API
keys, secrets, private crawled data, and unnecessary data directories.
2. Sanitized `python3 main.py stats` output. 3. Search/operator
regression results. 4. Crawl summary including effective budgets and
frontier growth. 5. Concurrency benchmark output and machine CPU/RAM
details. 6. Shutdown/restart test results. 7. Extraction fixture
results.

The next review should inspect the changed source and test evidence,
then update this plan based on what genuinely passes. This file is an
enhancement plan, not a claim that all requirements are already
implemented.
