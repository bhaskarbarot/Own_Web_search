# OwnSearch checkpoint — 2026-10-20

The user authorized continuous implementation of the remaining stages on `wip/data-driven-relevance`. Code has been applied to the actual checkout at `/home/pc-117/Documents/own_web_search_engine`; `main` was not merged or changed.

The architecture is preserved. Unicode/exact fields, conservative relevance, index-derived spelling and phonetics, language/date handling, local entity import, crawler budgets/background discovery, optional provider/model adapters, output metadata, packaging and evaluation tooling are implemented. See [the complete report](UPGRADE_REPORT.md) for the file list and per-stage evidence.

Validation:

- Actual updated checkout: **172 tests passed**, 44.065 seconds.
- Base dependency profile: **172 passed**; standard-library fallback: **172 passed**.
- Fresh one-command `sh scripts/setup.sh base`: installed successfully and **172 tests passed**, 45.290 seconds. Installed CLI ingestion/indexing/folding/pretty-search smoke passed.
- Actual-checkout evaluation reproduced the prepared code fingerprint, corpus/query hashes, all result URLs and every quality metric.
- 59-query synthetic fixture: MRR@10 **0.8947 → 0.9474**, NDCG@10 **0.8648 → 0.9144**, P@5 **0.1895 → 0.2000**. P@5 fixture ceiling is 0.2421. Paired bootstrap CIs are in `eval/upgrade-comparison.json`.
- Seven-query adversarial fixture: MRR@10 and NDCG@10 **1.0**, unchanged.
- Live: timestamped NVDA and TCS answers, four dated Trump articles, computing inheritance, official MCP docs and Requests Quickstart. Real runs and failures are retained in `eval/live-*.json`. The final run used warm caches/newly indexed pages, so its timings are not a controlled performance comparison.
- Captured raw market responses independently agree with the displayed NVDA price/timestamp and TCS series/statistics; see `eval/market-validation.json`.

**No overall green flag or 90% open-web accuracy claim.** The birthplace claim remains independently unverified. Broader disjoint language/web evaluations and sustained large-corpus/load tests remain necessary. Optional model/quantization execution is untested and disabled; missing model paths preserve core results. New language support is not certified.

MIRACL en/hi topics and qrels were fetched with checksums; its viewer is disabled, so the importer accepts separately supplied passage corpora and rejects missing judged documents. No public full-corpus score is invented. Existing fallback resources remain in use.

Existing six-field indexes remain readable, including mixed merges. Back up data before an explicit `reindex` populates new fields: older branch code cannot read new nine-field segments. Originals already lost during older ingestion require recrawling. The production index and credentials were not modified. The user's concurrent `query.txt` removal and `query.md` edits are preserved.

Evidence: `docs/evaluation/upgrade/`, `eval/upgrade-*.json`, [dependencies and configuration](DEPENDENCIES.md), [full report and remaining acceptance gates](UPGRADE_REPORT.md).
