# Live evaluation — Phase 0

The current plan is [docs/plan/phase-0.md](../docs/plan/phase-0.md), with the
handoff and measured changes in [docs/PROGRESS.md](../docs/PROGRESS.md).
Search behavior is frozen at `baseline-v0` during this phase.

- `queries.jsonl`: frozen live-v1, 500 authored queries including all 100 original
  benchmark queries. **Do not browse the full file during phases 0–4.**
- `dev.jsonl`: the 300 development cases that normal commands may read.
- `splits.json`: fixed dev/sealed IDs and SHA-256 fingerprints; 200 cases sealed.
- `legacy/queries.jsonl`: original 59 synthetic fixture cases, byte-preserved.
- [RUBRIC.md](RUBRIC.md): judgments, uncertainty, provenance and metric definitions.

The split was made by sorting SHA-256 of IDs, then taking the first 60% as dev.
It cannot make developer-authored queries or previously used cases independent.
The engine never reads this evaluation data during normal search.

## Reproduce the baseline

Run the existing configured discovery backend in a separate terminal if needed:

```bash
python3 main.py discovery serve
```

Capture all dev queries with normal fetch/safety limits and one-second pauses.
Each result is checkpointed; resume refuses changed engine/settings/protocol:

```bash
python3 eval/live_eval.py record --output eval/runs/baseline-dev.json
# After an interruption, with the same configuration:
python3 eval/live_eval.py record --output eval/runs/baseline-dev.json --resume
```

Cold wall time bypasses OwnSearch's response cache. Immediate repeat wall times
are recorded separately on a deterministic 30-query subset. With the default
TTL of zero these repeats are not response-cache hits. OS and upstream caches
are uncontrolled. Source errors, robots denials and failed fetches remain in
raw responses. Configuration is fingerprinted without storing credentials.

Reproduce metrics, pooling and CSV preparation without making network calls:

```bash
python3 eval/live_eval.py metrics --recorded eval/runs/baseline-dev.json --output eval/runs/baseline-dev-metrics.json
```

This one command writes reproducible query-bootstrap 95% CIs, cold/warm
p50/p95/p99, zero-result rates, source statuses and coverage. Relevance metrics
remain null without supplied judgments. URL provenance gaps are reported
separately from fabricated-URL count, which requires actual audits. Pooling uses
OwnSearch plus recorded provider candidates; it is not an independent gold set.

Additional available search sources can be imported explicitly with
`--extra-source path.jsonl` (repeatable). Each row is
`{id, query, source, checked_at, results: [{url, title, snippet}]}`; every query
must match a fixed dev case and timestamps must describe real observations.
Do not add invented URLs or fabricated source successes.

## Human review (chosen for this run)

The user selected CSV review; no LLM judge is configured or run.

- `human_review_queue.csv`: every unjudged pool row, grouped by query.
- `human_review_candidates.csv`: seeded 10% sample of unjudged candidates.
- `human_review.csv`: seeded 10% sample of actual judgments for checking;
  header-only until judgments exist.
- `runs/pool-dev.jsonl`: captured evidence with provenance and fingerprints.
- `runs/pool-dev-blinded.json`: evidence with provider names/ranks removed.

Make a copy of the queue or candidate CSV. Fill `human_grade` (0–3),
`human_rationale`, `human_reviewer` and `reviewed_at` (ISO date/time). Review
against the full request and the captured evidence, using the rubric. Complete
all pool URLs for a query to obtain a defensible quality score for that query.
A random sample of isolated URLs will usually leave query pools incomplete.

```bash
python3 eval/live_eval.py import-review --csv /path/to/your-reviewed-copy.csv --output eval/runs/human-judgments-v1.jsonl
python3 eval/live_eval.py metrics --recorded eval/runs/baseline-dev.json --judgments eval/runs/human-judgments-v1.jsonl --output eval/runs/baseline-dev-reviewed.json
```

For later rounds use `import-review --existing-judgments ...` with a new output
filename. Original labels and human review decisions remain separate. Automatic
regeneration refuses to overwrite nonempty human fields in the generated CSVs.
LLM judging is optional through `live_eval.py judge --command 'your adapter'`;
see RUBRIC.md for its JSON stdin/stdout protocol. It is off unless explicitly
configured, and LLM output is always labeled not independently verified.

Phase 0 remains gated while complete query-pool judgments are missing. Do not
start Phase 1 or run the sealed set to fill that gap. Answer correctness and
citation support are separate later measurements.

## Regression checks

```bash
python3 -m unittest discover -s tests -t .
python3 eval/run_eval.py --output /tmp/ownsearch-legacy-check.json
```

The first command needs localhost sockets for HTTP fixtures, but does not call
public providers. The second preserves the previous offline protocol below.

---

# Step 1 retrieval baseline

Run from the repository root:

```bash
python3 eval/run_eval.py --output /tmp/ownsearch-baseline.json
python3 -m unittest discover -s tests -t .
```

The runner uses only the standard library. It loads `corpus.json` and `legacy/queries.jsonl`, creates disposable storage, fixes the evaluation clock to the corpus timestamp, disables external providers and forbids HTTP calls. It never opens the production index in offline mode. Its output includes fixture/code fingerprints, per-query and per-language metrics, query-bootstrap 95% confidence intervals, and instrumented stage timings.

Defaults: three result-cache-disabled repeats, 1,000 bootstrap samples, seed 20261020. `--repeats`, `--bootstrap-samples`, and `--seed` are configurable. Python/OS caches are not flushed. Each query's median latency is used for aggregate percentiles; first-pass and repeat times are retained.

Fixtures represent synthetic retrieval expectations, not verified world facts. URLs and named examples in this directory are evaluation data, not production lookup rules. Most cases reuse earlier development fixtures, so this is not held-out validation. Ranking metrics use queries with relevant indexed fixtures; known-empty cases have separate abstention scores. Standard P@5 divides by five even when only one relevant page exists; a ceiling is reported alongside it. Language labels are evaluator-provided and do not assert that the engine detected them correctly.

`baseline.json` records the post-repair checkpoint; `before-correctness-fixes.json` uses the same fixtures against the previous code. `comparison.json` contains paired delta intervals. Missing live/answer measurements remain null or explicitly unmeasured. For a real live run, supply `--live --data-dir /path/to/disposable-real-index --queries /path/to/real-web-judgments.jsonl`; every case must declare `judgment_scope: real_web`. Do not relabel synthetic fixture judgments as real-web evidence.

See `docs/architecture.md` for current code paths and measured stages, and `docs/PROGRESS.md` for failures fixed, limitations and next work.
