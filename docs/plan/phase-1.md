# Phase 1 — discovery, provider resilience and safe query expansion

Date: 2026-10-21, Asia/Kolkata. Starting commit: b02f1dd.

## Order and authorization

The user corrected the sequence and requested completing phases one by one in
hierarchy without routine confirmation stops. Current work returns to Phase 1.
Retain the measured Phase 2 snippet fix; defer further ranking work until Phase 1
is evaluated. Phase 0 judgments are still absent. This authorizes implementation
and measurement progress, not invented quality scores or a false passed gate.

## Inspection

LiveSearch uses finite daemon workers and shared fetch deadlines. JsonProvider
has basic HTTP cooldown and request spacing, but no reusable provider health
circuit, half-open probe, response budget or health snapshot. SearXNG warnings
already preserve upstream denials. General discovery must remain enabled when
vertical routing is uncertain. Source URLs must come from actual API metadata,
not synthesized result/answer URLs. Existing evidence constraints already check
site/phrase/exclusion semantics locally; sitemap discovery currently needs an
actually fetched seed and a robots-declared sitemap.

## Ordered steps and files

1. Provider health/backoff and request-budget layer, honest statuses, injected
   failures: ownsearch/provider_health.py, webproviders.py, providers/__init__.py,
   coordinator.py, config.py. Add tests and a reproducible dev-source replay
   benchmark for two failing sources plus one healthy source. Commit separately.
2. Verify official API contracts; add independent configurable adapters one per
   commit: Wikipedia/Wikidata, GitHub, PyPI exact-project metadata (no fictional
   full-text search API), npm, crates.io, arXiv/OpenAlex and StackExchange.
   Use rate limits, bounded results and the pinned safe fetcher. Leave any
   unavailable or unqualified adapter disabled with an honest reason. Preserve
   ordinary general discovery for every intent. Capture actual permitted API
   observations and run adapter schema/safety tests after every adapter.
3. Updated by user on 2026-10-21: keep the active path free and self-hosted.
   Remove newly added Mojeek/Marginalia account integrations. Existing optional
   Brave compatibility stays disabled. Free official APIs are optional supplements,
   still subject to their limits, never a promise of unlimited external access.
4. Conservative query variants (original plus <=2 bounded keyword/facet variants),
   preserved operators/literal identifiers and Reciprocal Rank Fusion. Retain
   the original query as fallback; bounded concurrency and per-source budgets
   must apply across variants. Test failure/cancellation and no invented aliases.
5. Strengthen named-site discovery only using permitted origin/robots/sitemap
   observations; retain local site/quote/exclusion post-filtering. Discover RSS
   links from fetched HTML rather than guessing feed URLs. Follow robots, request,
   byte and time budgets for every follow-up.
6. Run the fixed dev benchmark and component ablations, full regression suite,
   preservation benchmark and two-source failure injection. Record configuration,
   source snapshots, timings, zero-result changes and all known limitations.
   Keep existing review files, baseline and sealed IDs unchanged. Update handoff
   and commit successful steps. Revert components that do not improve their
   defined metric or cause confirmed regressions.

## Measurement

Use all fixed dev IDs only. Frozen-source replay isolates orchestration from
changing upstream availability; it is not live retrieval accuracy. Real API/live
runs retain failures, timestamps, raw results and source status. Measure each
adapter's actual response/result counts; neither is an accuracy score. After
integration, measure live zero-result rate excluding explicit nonexistent entity
controls and cold/warm timing separately. Recall@10 and strict P@5 require real
pool grades; missing grades stay null with explicit gate failure.

## Risks

No judge is configured and the user chose human CSV review. Do not invent labels,
claim accuracy improvements, inspect the sealed set, or use it to fill gaps.
Some official APIs need keys or deny this network; do not bypass denials. PyPI
has exact metadata, not a general public search endpoint. API rates differ and
must constrain concurrent variants. A healthy local SearXNG response may contain
unhealthy upstream sources: preserve those warnings without discarding useful
results or pretending every upstream succeeded. Retain SSRF/DNS pinning and all
limits. Never turn an API page's modification time into its publication date.

## Phase exit gate

All tests and two-provider failure injection pass; dev zero-result rate decreases;
pooled Recall@10 improves with CI; strict P@5 does not regress. Without judgments
those quality requirements remain unmeasured. Continue all independent Phase 1
work and write the exact remaining dependency; do not declare the phase passed
or consume the sealed set without the required evidence.
