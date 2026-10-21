# Independent removal record

The old implementation and obsolete tests remain on `dependent` at `489d8dc`.
The active runtime on `Independent` no longer uses search providers or databases.
Parser and snippet regressions are retained; new crawler/API/security suites
replace obsolete provider/index suites. Human-review CSVs, sealed datasets and
ignored user data remain intact.

Deleted bundled engine: `searxxxing/` (995 tracked files).
Deleted ignored service installations: `.runtime/searxng/`, `.runtime/searxxxing/`.

Other tracked deletions:

- `eval/build_dataset.py`
- `eval/live_eval.py`
- `eval/run_eval.py`
- `ownsearch/answer_evaluation.py`
- `ownsearch/background.py`
- `ownsearch/bench.py`
- `ownsearch/bundled.py`
- `ownsearch/crawler.py`
- `ownsearch/db.py`
- `ownsearch/discover.py`
- `ownsearch/engine.py`
- `ownsearch/entities.py`
- `ownsearch/evaluation.py`
- `ownsearch/feeds.py`
- `ownsearch/frontier.py`
- `ownsearch/fusion.py`
- `ownsearch/gateway.py`
- `ownsearch/html_extract.py`
- `ownsearch/indexer.py`
- `ownsearch/ingest.py`
- `ownsearch/knowledge.py`
- `ownsearch/linkgraph.py`
- `ownsearch/live.py`
- `ownsearch/market.py`
- `ownsearch/metrics.py`
- `ownsearch/pipeline.py`
- `ownsearch/plugins/__init__.py`
- `ownsearch/plugins/intent.py`
- `ownsearch/plugins/ner.py`
- `ownsearch/plugins/rerank.py`
- `ownsearch/plugins/semantic.py`
- `ownsearch/plugins/translation.py`
- `ownsearch/provider_health.py`
- `ownsearch/providers/__init__.py`
- `ownsearch/ranking.py`
- `ownsearch/resources/news_feeds.tsv`
- `ownsearch/resources/news_feeds.txt`
- `ownsearch/resources/validate_feeds.py`
- `ownsearch/segments.py`
- `ownsearch/spell.py`
- `ownsearch/store.py`
- `ownsearch/transliterate.py`
- `ownsearch/vertical.py`
- `ownsearch/warc.py`
- `ownsearch/webfocus.py`
- `ownsearch/webproviders.py`
- `requirements-full.txt`
- `scripts/audit_query_checklist.py`
- `scripts/benchmark_query_md.py`
- `scripts/calibrate_intent.py`
- `scripts/check_relevance.py`
- `scripts/eval_live_web.py`
- `scripts/eval_phase1_compare.py`
- `scripts/eval_phase1_health.py`
- `scripts/eval_phase1_schema_health.py`
- `scripts/eval_phase1_variants.py`
- `scripts/evaluate_acceptance.py`
- `scripts/evaluate_relevance.py`
- `scripts/fetch_eval_samples.py`
- `scripts/import_trec_eval.py`
- `scripts/probe_query_variants.py`
- `scripts/probe_vertical.py`
- `scripts/setup.sh`
- `scripts/validate_feeds.py`
- `scripts/validate_market_run.py`
- `tests/test_baseline_tools.py`
- `tests/test_benchmark_eval.py`
- `tests/test_bundled.py`
- `tests/test_crawl.py`
- `tests/test_data_driven_relevance.py`
- `tests/test_evaluation_set.py`
- `tests/test_focused_discovery.py`
- `tests/test_index.py`
- `tests/test_live_eval_protocol.py`
- `tests/test_live_http.py`
- `tests/test_live_web.py`
- `tests/test_phase1_compare.py`
- `tests/test_provider_health.py`
- `tests/test_quality_and_providers.py`
- `tests/test_relevance_regressions.py`
- `tests/test_search.py`
- `tests/test_server.py`
- `tests/test_spelling_and_discovery.py`
- `tests/test_unicode_upgrades.py`
- `tests/test_upgrade_pipeline.py`
- `tests/test_vertical_apis.py`
- `tests/test_warc_eval.py`
- `tests/test_web_quality.py`
