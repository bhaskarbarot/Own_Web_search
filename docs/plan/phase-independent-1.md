# Independent runtime rebuild

Date: 2026-10-21. Starting checkpoint: 489d8dc on `dependent`.
The user explicitly replaced the old provider architecture and phase order.
Development happens on `Independent`; the old implementation remains recoverable.

## Goal

Own query-time discovery, crawling, extraction, ranking and cited excerpts, with
no search-engine service, account, paid API, or document database in the runtime.
Use bounded memory caches only. Retain safe owned parsers and fetching code.

## Research and design

- [Google's documented stages](https://developers.google.com/search/docs/fundamentals/how-search-works/)
  separate crawling, indexing and serving. A general web index is prepared before a query.
- [Brave's crawler](https://search.brave.com/help/brave-search-crawler) discovers
  content for its search index. Owning the UI/ranker alone does not own discovery.
- [SearXNG](https://docs.searxng.org/user/about.html) aggregates other search engines;
  self-hosting it does not remove that dependence.
- Follow [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309) and the
  [sitemap protocol](https://www.sitemaps.org/protocol.html).

A query cannot reveal unknown page addresses by itself. Starting URLs come from
explicit query URLs, a site filter, an editable source file, or actual cached links.
No domain guessing, query-specific source maps, benchmark result seeding, or hidden
search API fallback. No sources configured means an honest empty response with
instructions to provide a starting site. Millisecond cold whole-web crawling and
unlimited website access are not achievable. No subscription quota is introduced;
robots rules, website denials and machine resource budgets still apply.

## Ordered implementation

1. Replace discovery coordinator with a bounded query-driven crawler and memory
   page/link caches. Share origin politeness and robots state across requests.
   Fetch only observed URLs and explicit site roots. Parse declared sitemaps and
   feeds; rank real fetched text. Preserve byte, DNS, redirect and deadline guards.
2. Replace CLI/server/launcher and connect every existing UI filter. Add starting
   URLs. Images/video must derive from fetched pages, not external search APIs.
   Answers are cited source excerpts; insufficient or risky evidence abstains.
3. Remove bundled search engine, adapters, database runtime and obsolete commands.
   Preserve their full history on `dependent`; retain and port applicable tests.
   Existing ignored user data and human-review CSVs must not be overwritten.
4. Validate with controlled HTTP fixtures, adversarial inputs, all retained and new
   tests, fixed-dev query parsing (sealed queries remain unopened), and a small
   direct public-site smoke test if network access permits. Record actual results.

Files: ownsearch/config.py, coordinator.py, webfetch.py, webmodels.py,
webranking.py, cache.py, server.py, cli.py, resources/search.html; launcher,
packaging/docs; provider/vendor/legacy index removal; tests and scripts.

## Measurement and exit criteria

- Zero provider requests and zero SQLite/document-index files created.
- Fixture discovery finds linked and sitemap-declared matching documents while
  respecting robots/nofollow, size/depth/request/deadline limits and redirects.
- Cache-only execution performs zero network requests; expiring entries cannot
  masquerade as fresh fetches. Warm speed is measured separately from cold.
- Site, language, dates, phrase/exclusion and actual file-type filters enforced.
- Relevance and citations come only from successfully fetched page text.
- UI → API → HTTP fixture → ranked/cited response verified end to end.
- No live relevance improvement claimed without human judgments. Old metasearch
  availability numbers are historical, not comparable accuracy measurements.

## Risks and handoff

Coverage is bounded by starting sites and crawl budget. A cold site can take
seconds, especially with crawl-delay. Memory caches disappear on restart.
PDF/Office parsers need isolated resource/deadline bounds for hostile files.
Legacy provider/index tests are archived on `dependent`; applicable safety and
extraction tests must remain, and new runtime coverage must be reported explicitly.
Do not mark the old human-review quality gate passed by this architecture change.
