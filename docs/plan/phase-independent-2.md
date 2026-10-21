# Accuracy before speed: Independent phase 2

Date: 2026-10-21, Asia/Kolkata. Baseline runtime: 2e7b700.
Read goal.md fully, particularly Section 5. It supersedes the earlier ban on
SQLite: a bounded optional TTL cache is now expressly requested. No full index,
external search engine, paid service, query-specific URL/answer rule, or model
download will be introduced. User changes to goal.md and deleted main.md are
preserved and not included in implementation commits without need.

## Baseline and measurement first

1. Restore a DEV-only recorder/evaluator for the actual independent pipeline.
   Freeze baseline code and source config in an isolated snapshot. Capture all
   300 DEV queries; never load sealed query text. Preserve raw outputs, discovered
   pages/links, protocol/runtime fingerprints and errors. Record cold page-cache
   and immediate cache-only warm p50/p95/p99 with bootstrap 95% CIs, nonempty rate,
   request/byte budgets and failure reasons. Public-site probes are separate.
2. Graded strict P@5, NDCG@10, Recall@10, MRR and coverage ceiling require actual
   pooled relevance judgments. Existing CSVs contain zero human grades. Report
   null plus missing-grade counts; provide ungraded review CSVs, not invented
   grades or a fabricated coverage ceiling. Bound the ceiling by actual judged
   reachable pages only, and distinguish observed reachability from all the web.
3. Use one fixed protocol for each ablation. Record any shared-politeness or
   concurrency load explicitly. Never call nonempty rate accuracy. Capture user
   failure separately; do not add a runtime Gandhi rule or known article URL.

## Accuracy implementation order

A. Source registry descriptions + statistical similarity planning; preserve
   uncertainty breadth and explicit site/URL choices. Separate origins eligible
   for following real links from roots selected for fetching. Stop expanding
   zero-match article links as if they were promising evidence. Discover bounded
   native GET search forms from fetched HTML using an HTML parser; respect robots
   on generated form requests, reject non-GET/cross-origin forms and external
   search-service forms. Never guess an endpoint, article path or result URL.
B. Optional bounded SQLite page/URL cache with TTL by content class and bounded
   source memory learned from fetched, relevant passages. Honor use_cache=false,
   failed/noindex pages, fresh-request TTL and stale finance/news abstention.
C. Passage BM25 + literal entity/phrase evidence, canonical dedupe/domain caps;
   retain only measured gains. Structural signals never prove official ownership.
D. Explicit answerable/evidence/status and SOURCE EXCERPT / VERIFIED / INFERENCE
   semantics. Verification needs actual primary/independent evidence; uncertainty
   or conflicts cannot be hidden or turned into certainty by a label.
E. Remove semantic regex from active query/evidence/ranking paths. Use token
   sequences, statistical methods and real date/operator/HTML parsers. Document
   remaining syntactic regex and dependencies in docs. Preserve existing tests.

## Speed and interface gates

After accuracy mechanisms are measured, profile discovery/fetch/extraction/ranking,
then measure bounded early return, progressive output and sufficient-cache reuse.
Report cold and warm separately. Only after those gates, implement Section 7 API
wrappers/packaging; no premature pip-release or 90% accuracy claim.

## Tests, commits and handoff

Add generic regressions for irrelevant news budget consumption, a site-native
search leading to an alias-bearing article, blocked search form paths, source
uncertainty, cache expiry/stale data, namesakes, weak/conflicting evidence and
remaining parser behaviors. No expected article URL in runtime. Run retained
suite and DEV measurements per successful step; commit only task-owned paths.
Failed experiments remain off/reverted. Update docs/PROGRESS.md and a phase report
with ablation tables, CIs, limitations, missing judgments and exact next work.

Files: scripts/eval_independent.py, eval/runs/independent-phase2/, ownsearch/
sourceplan.py, native_search.py, coordinator.py, cache.py, config.py, webfetch.py,
query.py, webquery.py, evidence.py, webranking.py; sources.txt; tests; docs.
