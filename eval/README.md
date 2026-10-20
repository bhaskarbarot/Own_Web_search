# Step 1 retrieval baseline

Run from the repository root:

```bash
python3 eval/run_eval.py --output /tmp/ownsearch-baseline.json
python3 -m unittest discover -s tests -t .
```

The runner uses only the standard library. It loads `corpus.json` and `queries.jsonl`, creates disposable storage, fixes the evaluation clock to the corpus timestamp, disables external providers and forbids HTTP calls. It never opens the production index in offline mode. Its output includes fixture/code fingerprints, per-query and per-language metrics, query-bootstrap 95% confidence intervals, and instrumented stage timings.

Defaults: three result-cache-disabled repeats, 1,000 bootstrap samples, seed 20261020. `--repeats`, `--bootstrap-samples`, and `--seed` are configurable. Python/OS caches are not flushed. Each query's median latency is used for aggregate percentiles; first-pass and repeat times are retained.

Fixtures represent synthetic retrieval expectations, not verified world facts. URLs and named examples in this directory are evaluation data, not production lookup rules. Most cases reuse earlier development fixtures, so this is not held-out validation. Ranking metrics use queries with relevant indexed fixtures; known-empty cases have separate abstention scores. Standard P@5 divides by five even when only one relevant page exists; a ceiling is reported alongside it. Language labels are evaluator-provided and do not assert that the engine detected them correctly.

`baseline.json` records the post-repair checkpoint; `before-correctness-fixes.json` uses the same fixtures against the previous code. `comparison.json` contains paired delta intervals. Missing live/answer measurements remain null or explicitly unmeasured. For a real live run, supply `--live --data-dir /path/to/disposable-real-index --queries /path/to/real-web-judgments.jsonl`; every case must declare `judgment_scope: real_web`. Do not relabel synthetic fixture judgments as real-web evidence.

See `docs/architecture.md` for current code paths and measured stages, and `docs/progress.md` for failures fixed, limitations and next work.
