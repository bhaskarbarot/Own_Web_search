# Phase 2 — ranking and result presentation

Date: 2026-10-21 (Asia/Kolkata).
Starting commit: 7012277 (engine still identical to baseline-v0).

## Authorization and prerequisites

The user explicitly requested starting Phase 2 now. This overrides the earlier
phase-order restriction for starting this work; it does not make the Phase 0
quality gate or the unexecuted Phase 1 pass. There are still no complete relevance
judgments and no Phase 1 numbers. Preserve those gaps in every measurement and
handoff. Do not invent a ranking-accuracy improvement or advance to Phase 3.

## Goal

Improve generic ranking and snippet quality one measured component at a time,
retaining architecture, source provenance and all fetch safety limits. Use only
the fixed dev split. Keep the sealed query bodies unused.

## Inspection and first small step

- ownsearch/webranking.py already computes BM25, selects passages, checks entity/
  operator constraints and deduplicates long fetched pages using SimHash.
- ownsearch/webfetch.py accepts publisher canonicals only on the fetched host.
- ownsearch/webmodels.py renders the best evidence passage with [:600], cutting
  inside words and sentences even when an earlier complete sentence would fit.
- Recorded dev evidence confirms 74 mid-word ends among 1,574 evidence-backed
  snippets. Evidence text is available for reproducing this defect offline.
- Candidate URL audit found zero known tracking-parameter rows, 17 mobile-host
  observations and one print/AMP/export-shaped observation, but no same-path
  mobile/desktop pairs. These observations do not justify guessing that distinct
  URLs are equivalent. Revisit with fetched evidence or actual canonical links.

Implement the confirmed snippet-rendering failure first, before scoring changes.

## Files and ordered work

1. Add a reproducible 300-dev-case presentation replay in
   scripts/eval_phase2_snippets.py. It must validate dev IDs, bind itself to the
   saved baseline fingerprint, compare current rendering with the recorded
   rendering and report bootstrap CIs and raw per-query changes. It calls no
   providers and never substitutes replay timings for live-search latency.
2. Add a bounded, source-preserving sentence/word clipping helper to
   ownsearch/snippet.py. Use it only at the evidence-snippet rendering point in
   ownsearch/webmodels.py. Forward query terms at the existing rendering call in
   ownsearch/coordinator.py so complete matching words are retained when a
   sentence-only cutoff would hide them. Preserve provider snippets, passage text,
   passage scores, answers, URLs, provenance and ranking inputs. Add regressions
   in tests/test_phase2_snippets.py before retaining the change.
3. Run the dev replay before and after, all regression tests, and the existing
   offline retrieval benchmark. Record deltas and limitations in docs/PROGRESS.md.
   Keep this component only if the measured mid-word-end rate decreases without
   blanking snippets or changing recorded result order/content evidence.
4. Commit the verified component and its measurements. Keep Phase 2 open while
   the ranking-quality exit gate and remaining components are unresolved.

## Remaining Phase 2 components (separate measured steps)

- URL tracking/variant identity and near-duplicate handling: require evidence of
  equivalence; retain observed URLs and meaningful ordered/query parameters.
- Passage BM25 and entity/facet scoring; optional CPU model only after ablation.
- Structural ownership/trust evidence, configurable and without topic lists.
- Namesake penalties and phrase matching.
- Domain/provider diversity with fallbacks for the currently single-provider
  setup; do not fabricate independent provider coverage.
- Passage-start boundary defects and long-sentence cases, if established by
  reproducible evidence beyond the first rendering fix.

## Measurements and risks

For this rendering component, replay all 300 recorded dev cases. Define a
confirmed mid-word end as a snippet that is a proper prefix of its captured
passage and cuts between Unicode letters/numbers/combining marks/underscores.
Compare against the same captured source text; ellipses are display markers.
Report eligible snippets, cut counts/rates, sentence-end cuts, omitted excerpts,
query-token coverage diagnostics (including complete-word matches separately
from tokens created by the old cut), source-prefix validity and unchanged ranking
identities. Bootstrap rates by query with seed 20261021 and 1,000 resamples.

This is a presentation replay, not a full ranking or live-network benchmark.
Complete fetched bodies are not saved, so passage-start boundary failures cannot
be inferred honestly from offsets alone. P@5/NDCG and their CIs remain unmeasured
until the captured pools are graded. Sentence segmentation is conservative
punctuation-based; very long unbroken text needs an honest bounded fallback.

## Exit gate

Phase 2 is not complete until strict P@5 and NDCG@10 improve against a measured
Phase 1 baseline with CIs, duplicate and snippet metrics improve, all tests pass,
and per-component ablations are saved. Neither Phase 1 reference numbers nor
relevance labels currently exist. Report this explicitly after the first step;
do not rename offline preservation or snippet-format metrics as ranking accuracy.
