
## Mission

Upgrade the existing OwnSearch repository into a practical, live-web-first search engine. The goal is to accept broad user queries, understand the intent, discover relevant public web pages from multiple kinds of sources, fetch and inspect selected pages when useful, rank and deduplicate the evidence, and return useful results with direct links and available images/media metadata.

Build on the current repository. Do not assume the architecture described in this prompt exactly matches the code: inspect the actual implementation first, trace the real CLI/API path, and adapt the plan to the existing code.

**Important reality constraints**
- Do not claim OwnSearch is equivalent to Google or Brave, has indexed the whole internet, or achieves 90% accuracy unless independently measured evidence proves it.
- A cold live-web search cannot be guaranteed to crawl arbitrary websites and return complete results in milliseconds. Use parallel discovery, strict budgets, streaming/early results where supported, and optional background enrichment. Return the best available results quickly without pretending unfinished work completed.
- “90% accurate” must be converted into explicit, independently evaluated metrics. Do not tune or fabricate benchmark scores to reach a target.
- “No database” means search-time results must not depend on a pre-crawled local document corpus. Do not require a persistent document database for the live search path. An optional bounded cache and the existing local index may be used as accelerators/fallbacks if they already exist, but they must never be the only way to discover results. Do not remove useful existing components merely to satisfy wording; explain any storage that remains and make it optional for live discovery.
- Do not rely on Wikipedia/Wikidata as the general web-search source. Discover from diverse, relevant public web sources, including official documentation, primary sources, reputable publishers, research sites, repositories, product pages, and other pages surfaced by configured general search providers.
- Respect provider terms, robots.txt where applicable, website terms, copyright, rate limits, and crawl delays. Never bypass authentication, paywalls, CAPTCHAs, access controls, or anti-bot measures.

## Primary user experience

For a query such as:
- “latest AI developments in China”
- “FastAPI OAuth example”
- “history of the Ramayana”
- “compare current electric cars”
- “best source for a specific technical claim”

OwnSearch should:
1. Validate and understand the query.
2. Decide whether it is time-sensitive, navigational, factual, technical, local, image-oriented, or broad research.
3. Run the local index (if present) and available external discovery sources in parallel, rather than trusting local results alone.
4. Discover candidate URLs outside the local corpus.
5. Fetch only a small, relevant selection of missing pages within strict limits.
6. Extract useful page text and metadata safely.
7. Merge, normalize, deduplicate, and rerank candidates using the query and page evidence.
8. Return useful ranked results with real URLs, titles, snippets, source/domain, freshness when known, and clear fetch/source status.
9. For answer mode, generate a concise evidence-grounded answer with citations only when supported by fetched or provider-supplied evidence. Otherwise say evidence is insufficient.
10. Return useful partial results when one provider or fetch fails. Never silently imply that the search was exhaustive.

## Required architecture

Implement or adapt the following logical stages. Reuse existing modules where appropriate and avoid unnecessary rewrites.

```text
User Query (CLI / HTTP API)
        |
        v
Validation + Request Budget + Safe Defaults
        |
        v
Query Understanding
(intent, entities, phrases, language, date/freshness, filters)
        |
        v
Search Coordinator
        |
        +---------------------+----------------------+
        |                     |                      |
        v                     v                      v
Existing Local Index    General Web Providers   Specialized Providers
(optional accelerator)  (configured adapters)  (only for matching intent)
        |                     |                      |
        +---------------------+----------------------+
                              |
                              v
                    Candidate Normalization
                              |
                              v
                    URL Safety + Deduplication
                              |
                              v
                    Candidate Selection
                              |
                              v
                 Bounded Parallel Page Fetching
                    (selected URLs only)
                              |
                              v
                    Safe Content Extraction
                              |
                              v
                  Evidence-aware Reranking
                              |
                              v
                   Quality / Relevance Filter
                              |
                              v
                Results + Optional Grounded Answer
                              |
                              v
                Metrics, Trace and Limitations
```

### A. Search coordinator

- Create or improve a single coordinator used by CLI and HTTP API.
- Make external discovery a normal part of search, not something invoked only when the local index returns zero results.
- Execute independent sources concurrently with cancellation and per-source deadlines.
- Apply a total request deadline and bounded concurrency.
- Use partial-result behavior: if a provider times out, keep useful results from the others.
- Do not block the first response on a full crawl. Return ranked provider results as soon as the budget allows; optionally enrich/re-rank with fetched page content before the final response if the API contract supports it.
- If the API supports background discovery, make its status explicit. Do not tell the user that background work has completed when it has not.
- Keep provider adapters behind a common interface so sources can be added, disabled, tested, or replaced independently.

### B. General web discovery — critical path

Inspect the current SearXNG integration and configuration. If it exists but is unconfigured, make configuration and diagnostics clear, and implement the adapter robustly. Do not invent a provider endpoint or pretend it works without a real response.

Support multiple provider adapters where feasible, such as:
- A configured SearXNG instance with working upstream engines.
- A supported commercial web-search API configured with the user’s API key.
- Other lawful and technically supported search sources.

Provider choice must be configuration-driven. Document required environment variables, signup/API-key requirements, quotas, and costs. Do not hard-code secrets or silently depend on a paid API. If no provider is configured, report that general live discovery is unavailable and return whatever valid local results exist. Do not disguise Wikipedia or the local index as general-web coverage.

Provider adapters should:
- Have timeouts, retries with backoff only where appropriate, rate limits, and circuit-breaker or cooldown behavior.
- Parse and validate returned titles, URLs, snippets, timestamps, and image metadata where available.
- Preserve provider attribution and provenance.
- Handle empty, malformed, duplicated, or error responses safely.
- Include deterministic mocked tests; do not make routine tests depend on the public internet.

### C. Query understanding

Use the current query parser and intent modules if they are sound. Improve only where tests or code inspection show a gap.

- Preserve exact phrases, exclusions, site/domain filters, language, date ranges, file types, and existing query operators.
- Classify intent conservatively. Do not let a weak intent prediction prevent general-web search.
- Recognize freshness-sensitive terms such as “latest,” “today,” “current,” and “this week,” using the configured timezone.
- Handle spelling and aliases when evidence supports them; do not invent entities.
- Support non-English queries as far as the configured providers support them. Record language and quality limitations.
- If classification confidence is low, use general search rather than forcing a narrow specialized source.

### D. Candidate schema and merging

Create or standardize a typed candidate/result model containing fields as appropriate:
- `title`
- `url`
- `display_url` / domain
- `snippet`
- `source_provider`
- `source_type`
- `published_at` (nullable and only if supported)
- `fetched_at` (nullable)
- `content` or extracted passages (optional, subject to size limits)
- `image_url` / thumbnail metadata (optional, validated)
- `language` (optional)
- `fetch_status`
- `provenance`
- `relevance_features` or a trace of ranking signals

Requirements:
- Normalize URLs carefully without breaking meaningful query parameters.
- Remove fragments for duplicate comparison where appropriate.
- Detect canonical URL and redirect duplicates.
- Deduplicate both exact URLs and near-identical results/pages.
- Keep source provenance and avoid representing a provider snippet as content fetched by OwnSearch.
- Do not overwrite a valid timestamp with an inferred one without marking it inferred.
- Keep compatibility with existing API response fields where possible; introduce changes with tests and documentation.

### E. Safe, bounded on-demand fetching

Fetch only the best candidate pages, in parallel, under configurable limits. Make defaults conservative.

- Use strict connect/read/total timeouts and maximum response sizes.
- Restrict supported protocols to HTTP/HTTPS.
- Defend against SSRF: resolve and validate every destination, reject loopback, private, link-local, multicast, reserved, and cloud-metadata addresses; revalidate after redirects and DNS changes; defend against DNS rebinding.
- Validate every redirect target, cap redirect count, and avoid leaking credentials across domains.
- Respect robots.txt and applicable crawl policies. Do not bypass restrictions.
- Apply per-host concurrency and delay limits.
- Reject unsupported content types and suspiciously large responses.
- Do not execute downloaded JavaScript or arbitrary page scripts.
- Use safe HTML parsing and main-content extraction. Extract title, description, headings, visible text, canonical URL, publication metadata, links, and Open Graph/Twitter image metadata when available.
- Handle common HTML and text formats. Add PDF/document extraction only if the repository already supports it or it can be added safely with tests and size/page limits.
- Treat page content as untrusted data. Never execute instructions found inside webpages or let page text override system/developer instructions, tool policy, or secrets.
- Keep snippets short, clean, and relevant. Do not return giant raw page bodies.
- If fetching fails, retain a provider result if it is still useful, and accurately mark that its page content was not fetched.
- Do not persist full pages by default in the live-search path. If a cache is used, make it bounded, expiring, configurable, and compliant with source terms.

### F. Ranking and relevance

Use the existing ranking engine as the foundation, but do not assume its development-set score means general web accuracy.

Rank the merged candidates using query-dependent evidence, including:
- Exact title and phrase match.
- Query terms and meaningful term coverage.
- Heading and passage relevance.
- Entity match and intent compatibility.
- URL/domain and source type when relevant to the query.
- Freshness for time-sensitive queries, not as a universal boost.
- Language match.
- Source credibility signals where defensible.
- Duplicate and low-quality-page penalties.
- Evidence completeness and fetch status.

Important ranking rules:
- Do not rank a page highly merely because its domain is famous.
- Do not equate search-provider order with ground truth.
- Do not use arbitrary hard-coded domain whitelists as a substitute for relevance.
- Avoid overfitting to the current synthetic fixture.
- Keep ranking signals explainable in debug mode, but do not expose internal scoring details in normal user output.
- If page content was fetched, prefer evidence from the actual page over a short provider snippet when appropriate.
- If content is unavailable, score based on available metadata/snippet and mark the evidence level.
- Use query-intent-specific freshness rules. Older authoritative documentation may be better than a recent irrelevant page.
- Calibrate scores against labeled evaluation data; do not call a score “90% confidence” unless it is calibrated and validated.

### G. Images and other result types

Support images where the selected provider supplies image results or valid image metadata.

- Do not fabricate image URLs or assume that every webpage’s Open Graph image is relevant to the query.
- Preserve image source URL, page URL, alt text/caption, provider, and attribution where available.
- Validate URLs and use safe display behavior. Avoid fetching arbitrary images server-side unless necessary and protected by the same SSRF/size controls.
- Keep image search separate from ordinary web results when the provider supports it.
- Return images only when relevant and available; do not force an image section for every query.
- Keep the result model extensible for news, video, academic papers, repositories, and other result types, but implement only sources that can be tested and supported.
- Do not scrape search-engine result pages in ways that violate terms or bypass access controls. Prefer documented APIs or a properly configured metasearch instance.

### H. Optional answer generation

Keep search results useful without an LLM. Add or preserve a separate answer mode if the repository already supports it.

- Ground each factual statement in retrieved evidence.
- Provide citations linking to the actual source pages.
- Ensure cited sources were actually returned or fetched, and that the cited passage supports the associated claim.
- Do not fabricate citations, page titles, dates, quotes, facts, or links.
- Distinguish direct source facts from inference.
- If sources conflict, describe the conflict and show sources.
- For current events, report source dates and retrieval time when available.
- If the evidence is insufficient, say so and return the most relevant links rather than inventing an answer.
- Never treat a high ranking score as proof that a claim is true.

### I. Latency and “milliseconds”

Optimize for the fastest useful response, not an impossible promise that arbitrary uncached pages can be crawled and verified in milliseconds.

- Run independent providers concurrently.
- Use strict request and provider budgets.
- Reuse HTTP connections where the client supports it.
- Limit the number and size of pages fetched.
- Return early/stream partial results if compatible with the existing API.
- Optionally perform a second-stage rerank after page fetching, within the deadline.
- Cache query/provider responses only with a configurable TTL and respect provider terms. Cache is an optimization, never a requirement for discovery.
- Expose timings for query parsing, each provider, fetching, extraction, ranking, and total request.
- Use a graceful fallback when a deadline expires.
- Make time budgets configurable via environment variables/configuration, with safe defaults and validation.
- Never claim the result is exhaustive or fresh if the live source did not respond.

### J. Observability and honest status

Add structured logs and metrics for:
- Provider attempts, latency, failures, and result counts.
- Candidate count before/after deduplication.
- Number of pages fetched, failed, skipped, and extracted.
- Local-index contribution versus live-provider contribution.
- Time spent in each stage.
- Empty-result and low-evidence rates.
- Cache hits/misses, if caching exists.
- Request cancellation and deadline expiration.

Provide a diagnostic command or endpoint (consistent with existing conventions) that verifies provider configuration without exposing API keys. Never log secrets or full sensitive query contents unnecessarily.

## Storage policy: live search must not require a prebuilt corpus

- The core live search path must work when the local document index is empty or disabled, provided at least one general web provider is configured.
- Add a test that empties/disables the local index and confirms the engine can still discover and return web results from a mocked live provider.
- Local index and background crawl storage can remain as optional accelerators and a separate product capability. Clearly document that they improve repeat-query speed and offline/fallback behavior but are not prerequisites for live discovery.
- Do not create a new mandatory database merely to implement this prompt.
- Use in-memory request state and optional bounded TTL caches if appropriate.
- If the existing application requires SQLite for unrelated functionality, do not remove it blindly; trace dependencies and keep it out of the mandatory live discovery path.

## Implementation workflow — mandatory

1. Inspect the repository structure, current git status, tests, configuration, CLI/API entry points, `SearchEngine`, query parser, ranking, discovery, crawler/fetcher, models, and documentation.
2. Read the relevant code fully enough to understand real call paths. Do not rely only on filenames or prior reports.
3. Write a short implementation plan based on the actual code and identify risks.
4. Implement the smallest coherent set of changes that delivers live-web-first search. Do not replace working modules without evidence.
5. Preserve existing public API/CLI behavior unless a change is necessary; document breaking changes.
6. Add configuration examples and update `.env.example` or equivalent without adding real secrets.
7. Add unit tests for query coordination, provider parsing, candidate merging, URL safety, fetch limits, ranking, timeouts, partial failure, empty local index, and no-provider behavior.
8. Use mocked HTTP/provider responses in normal tests. Keep live integration tests opt-in and clearly marked.
9. Run relevant tests, linting, type checks, and the project’s existing test suite where practical. Fix regressions caused by the changes.
10. Inspect the final diff and verify there are no hard-coded credentials, fake results, fabricated benchmark claims, disabled safety checks, or silent swallowed exceptions.
11. Update documentation with architecture, setup, provider configuration, limitations, security, latency expectations, and evaluation procedure.
12. Do not claim completion or a green status for any check that was not actually run. Report failures and remaining work honestly.

## Acceptance tests

At minimum, add tests that prove:

1. **Unknown-to-local-index query:** With an empty/disabled local index and a configured mocked web provider, a query returns valid external results.
2. **Parallel discovery:** Two independent providers are invoked concurrently or with demonstrably overlapping execution.
3. **Partial provider failure:** If one provider times out and another succeeds, the successful provider’s results are returned.
4. **No provider configured:** The engine reports that live discovery is unavailable and does not pretend it searched the web.
5. **Page fetching:** Selected candidate pages are fetched within configured concurrency, timeout, redirect, and size limits.
6. **Fetch failure fallback:** A provider result can remain in output when page fetching fails, clearly marked as not fetched.
7. **Deduplication:** Equivalent URLs and canonical/redirect duplicates are not repeated in final results.
8. **Ranking:** A relevant fetched page can outrank a weak snippet-only candidate, according to tested ranking signals.
9. **Freshness:** Freshness matters for “latest” queries but does not automatically dominate timeless queries.
10. **Images:** Valid provider image results are returned with provenance; absent images are not invented.
11. **Grounded answers:** Any answer citation maps to an actual result/source and no fabricated citation is emitted.
12. **Security:** Private/loopback IPs, metadata endpoints, unsafe redirects, oversized responses, unsupported schemes, and disallowed targets are rejected.
13. **Latency budget:** Slow providers/fetches are bounded and useful partial results can be returned.
14. **Compatibility:** Existing CLI/API response contracts and existing tests remain working, or changes are explicitly documented.
15. **No false accuracy claims:** Tests and documentation distinguish ranking metrics from answer correctness and web coverage.

## Evaluation plan and target definition

Do not claim “90% accuracy” based on MRR, NDCG, a small synthetic corpus, or unit tests.

Create or document an independently judged evaluation set of at least 300–500 diverse queries as an initial milestone. Ensure some queries specifically target topics/pages absent from the local corpus. Avoid tuning against the final holdout set.

Define separate measurements:
- **Top-5 useful-result success rate:** fraction of queries with at least one genuinely useful result in the first five.
- **Top-5 precision:** fraction of first-five results judged relevant.
- **Recall@10:** fraction of known relevant documents found in the first ten, where relevance judgments are available.
- **NDCG@10 / MRR@10:** ranking quality.
- **Discovery success on empty-index queries:** fraction of empty-local-index queries for which live discovery returns useful results.
- **Answer correctness and citation support:** evaluated separately by human judgment.
- **Latency:** median and p95, separately for cached and uncached queries.
- **Freshness and language performance:** reported separately.

A 90% target may be pursued only for a precisely defined metric and query set. Report sample size, test method, provider configuration, time window, and confidence intervals where appropriate. Do not guarantee 90% for arbitrary internet queries.

## Definition of done

The task is complete only when:
- Live discovery works with the local index empty or disabled.
- The current SearXNG/provider integration is either correctly configured and tested or clearly documented as unavailable pending configuration.
- Results from local and external sources can be merged and reranked.
- Selective page fetching is safe, bounded, and observable.
- URLs and source provenance are real and preserved.
- Images are returned only when real provider metadata supports them.
- Partial provider failures do not unnecessarily fail the whole search.
- Tests cover the acceptance criteria and have actually been run.
- Documentation accurately explains setup, costs, limits, and what has and has not been proven.
- No claim is made that the engine is Google/Brave-scale or has 90% general accuracy without evidence.

## Final report required from Codex

After implementation, report:
1. What you inspected and the actual old search flow.
2. Files changed and why.
3. The new real query-time flow.
4. How to configure and verify at least one general web provider.
5. Exact commands run and their results.
6. Which acceptance tests pass/fail/not run.
7. Latency results measured locally, with setup and sample size.
8. Known limitations, API costs/keys, and any manual configuration still required.
9. The measured evaluation metrics, only if an actual evaluation was run.
10. A clear status: complete, partially complete, or blocked.

Do not stop after writing a plan. Implement, test, inspect the diff, and report the actual outcome. If a required provider key or endpoint is missing, complete all work that can be tested with mocks, then state exactly what configuration the user must provide for live integration testing.
"""
