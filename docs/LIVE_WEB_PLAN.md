# Live web search implementation plan

Requirements: user-authored `pipeline.md` (2026-10-20). Preserve the existing SQLite/BM25 crawler as an explicit local capability; do not delete the user's data.

Old flow: CLI initializes persistent SearchEngine; parses/links; retrieves local postings; optionally fuses SearXNG snippets; deficient coverage triggers source discovery, fetch, persistent ingestion/indexing, and a second local search. API also starts persistent frontier/index workers.

1. Add a shared database-independent live coordinator and request/candidate models. Default CLI search and API serve to live mode, preserving explicit local mode and existing programmatic SearchEngine.
2. Add configured SearXNG and optional Brave API adapters, validated schemas, attribution, cooldown/rate limits, concurrent deadlines and diagnostics. No automatic public endpoint or paid dependency.
3. Reuse safe fetcher and HTML/text extraction for bounded request-only enrichment. Shared request/byte/host limits, robots, redirect checks, no page persistence. Preserve provider snippets when enrichment fails.
4. Reuse BM25 field/feature weights and evidence helpers for small in-memory candidate ranking. Apply operators, dates, aliases and evidence gates; deduplicate URLs, redirects, supported canonicals and near-identical pages. Return real media metadata and optional extractive cited passages. Preserve Yahoo answers with request-local cache mode.
5. Test empty storage, concurrency, partial errors/deadlines, source parsing, filtering, robots/SSRF/redirect/size limits, relevance, media, citations and CLI/HTTP behavior; run the existing suite and fixture evaluator. Document provider setup, costs, storage and remaining evidence gaps.

Risks: no configured general provider is present, so public integration cannot be certified; live usefulness depends on upstream coverage and availability. A 500ms legacy provider wait must not truncate normal live discovery. Provider snippets need softer lexical admission than an all-words rule, while explicit operators remain strict. Network deadlines cannot forcibly kill arbitrary Python workers; late work must be marked and ignored, with finite capacity and cooperative cancellation. Live local integration is disabled by default; explicitly enabling it accesses legacy storage. Existing auth key files remain optional service configuration, not a document corpus.

Evaluation: preserve old fixture metrics as local-only evidence. Add measurable deterministic live acceptance checks and local HTTP end-to-end tests. A separate 300–500 independently judged holdout is still required; do not fabricate labels or declare 90% web accuracy.
