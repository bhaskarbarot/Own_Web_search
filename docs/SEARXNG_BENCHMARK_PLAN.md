# Local SearXNG integration and real-query evaluation

1. Copy the existing clone from repo/searxng into searxxxing, preserving upstream code and licenses; install its runtime in an isolated local environment, bind only localhost, enable JSON and finite upstream timeouts. Keep service metadata/caches separate from document storage.
2. Add repeatable setup/serve/status commands (Ctrl+C stops the foreground server) and persist the OwnSearch provider configuration without secrets in tracked files. Verify actual source responses before running a larger batch.
3. Parse all 100 table cases and the additional workflows from query.md into stable, versioned records. Preserve exact query text, criteria and workflow scope; do not label a single retrieval as task completion.
4. Capture real provider and OwnSearch outputs with timestamps, status, sources and timing. Diagnose generic failures, add regression tests, and compare against captured source results rather than inventing relevance labels.
5. Review evidence for relevance/answer support separately, report sample size and uncertainty, and retain failures. Run all listed queries; ambiguous underspecified cases need explicit scope rather than invented facts. Broader 300–500-query independent accuracy remains separate.
6. Run the existing regression suite, provide actual metrics/commands/limitations, and grant no green flag unless the requested real quality and speed checks pass.

Source-copy integration and the full 100 table-case recording are complete. Eight M cases represent initial retrieval only, not completed workflows. A provisional developer review covers 20 cases; independent review, complete answer verification and a representative holdout remain pending. See [SEARCH_QUALITY_REPORT.md](SEARCH_QUALITY_REPORT.md) and the historical [BUNDLED_SOURCE_REPORT.md](BUNDLED_SOURCE_REPORT.md). The quality and cold-latency gates do not pass.
