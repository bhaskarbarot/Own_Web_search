# Live-web-first search

The current normal CLI `search`, CLI `serve`, and agent `web_search_handler` use `LiveSearch`, a shared coordinator. They do not open a document database, build an index, start a crawl frontier, or save full pages. A configured general search source discovers URLs outside the local corpus. No GPU is required by this path.

## Query flow

```text
CLI / HTTP / agent facade
  -> validate + global deadline + optional memory cache
  -> existing Unicode/operator/language/date/intent parser
  -> concurrent configured SearXNG / Brave and matching finance/news sources
     + optional existing local index (disabled by default)
  -> validate public-link syntax + preserve meaningful URL query parameters + merge provenance
  -> in-memory BM25 field scoring and query constraints
  -> fetch selected pages concurrently: robots + pinned DNS/IP + size/request/host limits
  -> existing safe HTML/text extractor, no JS/OCR execution
  -> rerank using actual page evidence, deduplicate URL/canonical/redirect/near-identical pages
  -> results + evidence + optional quoted source excerpt / direct financial answer
  -> source statuses, timings, coverage limitations and cancellation state
```

General discovery runs even when local results exist. Provider snippets can be returned without inspecting their pages; the output distinguishes them from fetched evidence. Page fetching enriches selected results and never requires a persistent ingestion/reindex step. Full-page text exists only in request state. No broad entity dump or local corpus is needed.

## Configure a provider

Nothing automatically connects to a random public instance or subscribes to a paid service. At least one usable general provider is necessary for broad web discovery. With none configured, searches report unavailable discovery and may still return an applicable finance/feed answer or an explicitly enabled local result.

### Bundled source

The repository now includes the source copy in [`searxxxing/`](../searxxxing/OWNSEARCH_README.md).
Run `python3 main.py discovery setup`, then keep `python3 main.py discovery serve`
running in a terminal. Setup connects the existing provider adapter to the localhost
copy. `discovery status` checks instance identity; `providers --check` sends an actual
search probe. This uses no hosted SearXNG instance, Docker or Valkey server. It still
uses external search engines and upstream Python packages. The small metadata caches
in `.runtime/searxxxing/cache` belong to the copied backend, not OwnSearch's page corpus.

### Optional separately configured SearXNG

Run an instance you control or use an authorized endpoint supplied to you. Enable JSON output in its `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

Set the root URL, not `/search?q=...`:

```bash
export OWNSEARCH_SEARXNG_URL=http://127.0.0.1:8888
export OWNSEARCH_SEARXNG_ALLOW_PRIVATE=true
python3 main.py providers --check
python3 main.py search "your own unfamiliar query" --pretty
```

That localhost example works only after a service is running at that address. The private-address exception is scoped to that configured instance and port; it does not permit fetching private result pages or following API redirects to other private targets. Do not set the legacy `allow_private_hosts` switch for a public deployment.

See the [official installation instructions](https://docs.searxng.org/admin/installation-docker.html) and [Search API documentation](https://docs.searxng.org/dev/search_api.html). A 403 can mean JSON is disabled; upstream errors/CAPTCHAs or unavailable engines must be resolved through normal provider operation, never bypassed. SearXNG aggregates other sources; it does not independently index the internet. There is no OwnSearch API subscription required for this adapter, but hosting/network costs and upstream service terms still apply.

### Optional Brave API

Create your own account/key and choose an appropriate plan, then set `OWNSEARCH_BRAVE_API_KEY` in your shell or secret manager. Do not commit it. The adapter uses the documented web/image JSON endpoints with the subscription token in a header. It is disabled without a key; account quotas and billing apply. Check current [Brave API documentation](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started) and your account before enabling it. No plan, free quota, storage right, or price is assumed here.

Both adapters apply finite timeouts, bounded output/response parsing, per-process request spacing and cooldowns after rate limits/repeated failures. There are no automatic billable retries. Cache use must comply with your provider's terms. Diagnostics never print keys. Example environment settings are in `.env.example`; they are not automatically loaded.

## Commands and API

```bash
python3 main.py providers                   # configuration only; no network
python3 main.py providers --check           # actual diagnostic provider request
python3 main.py search "your query" --pretty
python3 main.py search "your query" --no-fetch --pretty
python3 main.py search "your query" --answer --pretty
python3 main.py search "your query" --images --pretty
python3 main.py serve                       # no document DB/frontier/index worker in live mode
```

`--answer` returns a clearly labeled extractive source passage when meaningful query coverage exists. It does not synthesize a universal factual answer or claim independent corroboration. The citation points to a returned result and preserves the actual passage. Injection-flagged evidence is excluded from answer excerpts. Source snippets, factual truth, and complete question answering are different things. Existing Yahoo quote/history answers retain their source, data timestamps and delayed-data/informational disclaimers; live mode uses a request-local cache for those calls.

`GET /search` and `POST /search` retain query/result/evidence/coverage fields. New options are `fetch_pages` (default true), `search_type` (`web` or `images`) and `answer_mode` (default false). A search-scoped key may use configured search APIs; fetching arbitrary result pages additionally requires `fetch` or `admin`. `/providers` reports configuration without issuing a probe. Existing authentication, API quotas, `/health`, `/stats` and `/metrics` remain available. Live result IDs are `null` because no persistent documents are created.

API `live:false` disables network discovery. It can use a local corpus only when the optional local accelerator is explicitly enabled; CLI `--no-live` directly selects the legacy offline engine.

`POST /fetch` remains available to fetch-scoped keys, returning the existing document-shaped response with `id: null`, `persistent_storage: false` and bounded transient text. It does not index/persist content, even when the legacy `index` flag is supplied. Live mode returns **409** for `/ingest`, `/crawl`, `/feedback`, which require legacy storage. Use an explicit local-mode service when that optional capability is wanted. `/document` can read an enabled local accelerator's stored documents, but does not promise that a transient live result can be retrieved later by ID.

## Storage and compatibility

Default live search creates no data directory, document/market/entity database, segment, frontier or query log. The optional memory response cache is off (`live_cache_ttl=0`); enabling it retains bounded result metadata and short evidence passages for its TTL, not full pages. Disabling the cache does not disable discovery. Optional authentication keys remain small service configuration and are independent of document storage.

Your old data is preserved. `SearchEngine` remains the explicit programmatic local-index class. CLI `crawl`, `ingest`, `worker`, index maintenance and corpus benchmarks remain optional legacy tools. To search that corpus or serve the legacy persistent endpoints:

```bash
python3 main.py search "local topic" --no-live --pretty
OWNSEARCH_SEARCH_MODE=local python3 main.py serve
```

Set `OWNSEARCH_LIVE_LOCAL_ENABLED=true` only if you want an existing corpus queried alongside providers; a missing corpus is not created. Enabling this optional accelerator opens the legacy store and may apply pending index changes. General providers still run.

## Budgets and evidence

Defaults: total request budget 8s; independent provider budget 3s; at most three pages, three fetch workers, a four-second enrichment window, 2MB per response, 6MB decoded response bodies per request, 16 page/robots/redirect requests. Each origin is serial and respects configured delay/robots crawl delay. Candidate output and text are bounded. Documentation can follow at most two specific same-origin page links, or one robots-declared sitemap, within the remaining global deadline and shared byte/request limits. No links are enqueued for a continuing crawl. The configured minimum interval/cooldown is per process, not a distributed provider quota service.

After enough relevant general results arrive, the coordinator permits a short configurable grace period before returning partial results. Timeouts/unfinished workers are reported, cancellation is requested, and late output is ignored. Python cannot forcibly kill arbitrary blocked extension code; finite worker capacity and HTTP/DNS deadlines bound ordinary work. CPU parsing/ranking can add overhead beyond a nominal deadline. This is a synchronous bounded final response; token/SSE streaming and background enrichment are not implemented in this path.

Timings separate parsing, provider coordination wall time, candidate ranking, fetch wall time, accumulated network/extraction worker time and final ranking. Parallel worker times are not additive wall time. Cached replies report their actual new response time and retain original trace separately. Results expose page fetch status, provenance, publication source/conflicts, actual fetched time and limitations; a result score is never a calibrated correctness probability.

Live fetching supports HTML/plain text. Existing PDF/Office/OCR extraction stays in explicit local ingestion; it is not invoked on arbitrary live results. Unsupported pages retain usable provider snippets. DNS validation checks every address and pins connections; redirects are revalidated. Caller credential headers are removed across origins. Candidate link syntax is checked before ranking; DNS safety is enforced when a request is actually made. Meaningful query-string order and repeated parameters are retained in live page requests. Same-origin canonicals can merge duplicates; cross-origin canonical claims are not trusted for deduplication. Different sites' near-identical text may be collapsed while source provenance remains.

Image search uses provider-supplied URLs/provenance without downloading images server-side. HTML Open Graph/Twitter images remain explicitly unverified page metadata; they are not automatically promoted to query-relevant image results. No image is invented. No Wikipedia-only fallback is portrayed as full-web search.

## Evaluation

```bash
python3 -m unittest discover -s tests -t .
python3 scripts/eval_live_web.py --queries eval/live_web_queries.example.jsonl --no-fetch --output /tmp/live-recording.json
python3 scripts/eval_live_web.py --queries /path/reviewed-holdout.jsonl --recorded /tmp/live-recording.json --output /tmp/live-reviewed.json
```

The example queries are **unreviewed** and produce no accuracy score. Record 300–500 diverse independently selected queries as the first milestone, with no local corpus. Keep the final holdout out of tuning. Pool top results from comparison providers and actual search output, have reviewers label usefulness/relevance 0–3, and retain query/run time, provider configuration, language, category and evidence. Do not put private queries in a public artifact.

The evaluator reports top-five useful-result success, P@5, Recall@10 where judgments support it, MRR@10 and NDCG@10 with bootstrap intervals. Missing results count against reviewed answerable queries. Relevance labels do not certify answers: attach separate human `answer_correct` and `citations_supported` labels to the recorded `answer_sha256`. Reassess the captured report with `--recorded`; do not reuse stale answer labels after changing evidence. Stratify results by language/category/time sensitivity and independently verify publication dates, claims, market timestamps and arithmetic. Report cached and cold latency separately.

Unit tests and the old 57-document synthetic development benchmark cannot establish 90% open-web accuracy. No public integration or general accuracy is certified until a configured provider responds and independent judgments are available.

## Current quality checks

See [SEARCH_QUALITY_REPORT.md](SEARCH_QUALITY_REPORT.md) for the completed 100-case recording, new-topic probes, provisional review, direct-answer checks and remaining failures. General discovery defaults to the general category; confident news or explicit fresh-date queries also use news. An uncertain uncalibrated intent does not restrict discovery. Query qualifiers and operators survive forwarding.

Property questions abstain when only an arbitrary source excerpt is available. Other extractive output is explicitly a source excerpt, not an independently verified answer. A validated market answer avoids unnecessary HTML enrichment; provider deadlines and delayed-data labels remain.

```sh
python3 scripts/benchmark_query_md.py --fetch --output /tmp/ownsearch-recording.json
python3 scripts/eval_live_web.py --queries docs/evaluation/full-web/review.jsonl --recorded docs/evaluation/full-web/after.json --output /tmp/ownsearch-reviewed.json
```

The saved labels are AI-assisted developer diagnostics with `independent_review: false`; they cannot certify 90% accuracy. A fresh independent holdout, with complete task and answer judgments, is still required. Existing regex parses syntax, tokens and dates; generic lexical/structural heuristics do not establish broad semantic understanding.
