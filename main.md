# OwnSearch Upgrade: Engineering Plan (main.md)

Goal: upgrade the EXISTING OwnSearch into a multilingual, high-relevance web search engine. Improve the current code; do not rebuild it.

## 0. Rules (apply to every step)

1. No hardcoded answers, no special-casing of example queries, no fake search or crawl results.
2. Preserve working features and public interfaces. CLI output (including `--pretty`) stays backward compatible.
3. All 135 existing tests must pass after EVERY step. A failing test blocks the next step.
4. Never claim an improvement, a language, or "production ready" without a measured result (with bootstrap confidence intervals). "Supported" means: passed its per-language eval, for the install profile tested.
5. Delete old files only after their replacements pass tests.
6. Anything needing a credential, model, or external provider is configurable and documented. No paid API by default, none mandatory.
7. Licenses: record the actual license name and link from the model/library page, or write `UNVERIFIED`. Never write "verified" from memory.
8. Heavy parts (embeddings, reranker, NER, translation) are optional, lazy-loaded plugins. They never block core BM25 search. If a plugin is missing, search still works.
9. Work in small steps. After each step: run tests, run the eval, write results to `docs/progress.md`, stop.

## 1. How to work within a limited coding-agent budget

- One step (section 4) = one session. Paste only that step plus section 0.
- Each step lists files touched, a "Done when" checklist, and tests. Do not start the next step until all boxes are ticked.
- Ask the agent for a diff summary and test output only, not long explanations.
- Keep `docs/progress.md` as memory between sessions: current step, baseline numbers, open problems.
- Highest-value order if budget runs out: Step 1 (baseline) > 2 (normalize) > 3 (exact/entity ranking) > 4 (spelling) > 5 (languages) > the rest.

## 2. Architecture summary

```
query -> normalize -> detect lang/script -> entity link (local) -> intent -> date parse
      -> expand/spell-check (from index vocab) -> retrieve (BM25F word + exact + ngram [+ vector])
      -> fuse (RRF) with providers (optional) -> rerank (optional, time budget) -> snippets -> results
crawl -> fetch (safe) -> extract -> detect lang -> dedupe -> index incrementally
```

Install profiles:

| Profile | Contents | Claim |
|---|---|---|
| base | regex, stopwordsiso, dateparser, holidays, charset-normalizer, simhash lib | Only languages that passed eval in this profile |
| full | base + onnxruntime + sentence-transformers (multilingual-e5-small, int8) + lingua + transliteration + optional faiss/qdrant, reranker, NER, translation | Only languages that passed eval in this profile |

## 3. Known risks to design around

- Char n-grams help only INSIDE one language (typos, inflection). They do not give cross-language search. Cross-language needs embeddings or translation.
- n-grams can make similar names worse ("Kumkum Bhagya" vs "Kundali Bhagya"). Exact-phrase/entity score must clearly beat the n-gram field.
- Short queries make language detection unreliable. Use priors (script, user setting, Accept-Language).
- Hinglish (Latin-script Hindi) is hard: spellings vary ("mausam/mosam"). Needs phonetic keys plus fuzzy match, and its own eval.
- e5 cosine scores cluster high (about 0.7 to 1.0). Fixed thresholds like 0.5 are invalid. Use calibrated top-1/top-2 margin.
- Naive Bayes trained on English cannot classify Hindi/Gujarati. Its non-English answer is `general`.
- dateparser false positives: "may", "march", "sat", "second".
- Index size can grow 3 to 5x with n-grams. Measure.
- Wikipedia-based eval sets (MIRACL etc.) test ranking, not your crawl coverage.
- NLLB-200 weights are non-commercial (CC-BY-NC). Prefer IndicTrans2 or argostranslate, after checking their licenses and each language pack's license.

## 4. Steps

### Step 1: Inspect + baseline (Phase 0). No behavior change.
Do:
- Map the codebase: crawler, index, query processing, ranking, snippets, API/CLI, config, tests. Write `docs/architecture.md` (what exists, where the bottlenecks are, measured not guessed).
- Run all 135 tests. Record pass/fail.
- Build the eval set `eval/queries.jsonl`: at least 50 queries covering English, Hindi, Gujarati, Hinglish, misspellings, coding, official docs, factual, news, comparison, named entities, cast/list, and queries with NO relevant indexed page. Each has graded relevance judgments or expected URLs. No query may be tuned for specifically.
- Write `eval/run_eval.py`: Precision@5, Recall@10 (where ground truth exists), MRR@10, NDCG@10, zero-result rate, latency p50/p95/p99, live-discovery success rate, bootstrap 95% CI.
- Save `eval/baseline.json`.
Done when:
- [ ] 135 tests pass, count recorded
- [ ] baseline.json exists with all metrics, per language
- [ ] architecture.md lists the top 5 measured bottlenecks

### Step 2: Normalization + tokenization (Phase A)
Files: `textproc.py` (+ tests)
Do:
- ONE `normalize(text, lang)` used for BOTH documents and queries.
- Keep two forms: `exact` (original tokens) and `folded` (for matching). Never destroy the original.
- casefold; NFKC; accent folding for Latin only (keep Indic and Arabic marks; avoid damaging Vietnamese/Turkish/Persian in the exact field); remove ZWJ/ZWNJ in folded only; normalize nukta forms explicitly (NFKC does not do this); strip Arabic tashkeel in folded only; map Indic/Arabic digits to ASCII in folded only.
- Tokenize with `regex` (`\p{L}`, `\p{M}`, `\p{N}`), never ASCII `\w`. Segmentation for CJK/Thai via grapheme clusters or optional jieba/fugashi/pythainlp, lazy.
- Stopwords via `stopwordsiso` for BM25 keyword scoring ONLY. Verify it has `hi` and `gu`; if not, record the gap. Never strip stopwords inside phrase or entity matching. Keep `stopwords_en.txt` as fallback.
- Grapheme-cluster n-grams (`regex` `\X`): 3-grams for Latin/Indic, 1 to 2 for CJK/Thai. Separate BM25F field `ngram`, boost configurable and tuned on eval.
Done when:
- [ ] 135 tests still pass
- [ ] tests: Devanagari conjunct `कृत्रिम`, Gujarati text, ZWJ, digit mapping, CJK, Thai, Turkish İ
- [ ] same function proven used on both index and query path
- [ ] index size growth (MB) and p95 latency recorded vs baseline

### Step 3: Exact-phrase + entity ranking (fixes entity confusion)
Files: `ranking.py`, `engine.py`
Do:
- Add `exact` field (unfolded tokens with positions) for phrase and entity matching.
- Ranking features, learned or tuned on eval, not hardcoded per topic: exact phrase (strongest), BM25F word, BM25F ngram (lower), title/heading coverage, term proximity, passage relevance, URL signals, source quality, verified freshness, same-language boost.
- Hard rule: freshness, popularity, domain authority and semantic similarity can never outrank strong query relevance.
- Multiword names are matched as phrases. Similar names must not be treated as identical.
Done when:
- [ ] regression test: "Kumkum Bhagya" ranks exact matches above "Kundali Bhagya" (built from indexed fixture pages, no special-casing in code)
- [ ] eval vs baseline: NDCG@10 / MRR@10 not worse, CIs reported
- [ ] 135 tests pass

### Step 4: Spelling correction + query expansion
Files: `query.py`, new `spell.py`
Do:
- Build a per-language term-frequency vocabulary FROM THE INDEX (not hand lists). Use a SymSpell-style lookup with edit distance 1 to 2.
- Never override the original query. Show "did you mean" and optionally run the corrected query as a lower-weight second query, merged by RRF.
- Do not correct: quoted phrases, code, URLs, names found by the entity linker, numbers.
- Expansion: stemming/lemmatization per language only when appropriate (Porter for English; Hindi light suffix stripper stays; n-grams cover other languages). Synonyms only from data (Wikidata aliases, WordNet where available), added as lower-weight terms.
Done when:
- [ ] misspelling queries in eval improve, with CIs
- [ ] exact-quote queries and code queries unchanged
- [ ] original query always preserved in the response

### Step 5: Language detection + per-doc language
Files: `textproc.py`, `crawler.py`, `engine.py`
Do:
- Query language: script detection (Unicode `\p{Script=...}`; kana implies ja; Devanagari is shared by hi/mr/ne, Arabic script by ar/fa/ur, Han by zh/ja) + user setting + Accept-Language, as priors. Short text: priors dominate.
- Documents: `<html lang>`, `Content-Language`, script, then lingua or fastText (lazy, restricted to configured languages only).
- Store `lang` (BCP-47 or ISO 639-3) per document. Add `lang:` operator and a same-language boost. Never silently drop cross-language results.
Done when:
- [ ] per-doc lang accuracy measured on a labeled sample
- [ ] 135 tests pass

### Step 6: Hinglish / Gujlish (default profile)
Files: `textproc.py`, index
Do:
- At index time, store a romanized phonetic key for Devanagari and Gujarati terms (rule-based, ITRANS-like, normalized so "mausam/mosam" collapse).
- Latin queries that look like Indic romanization are matched against this key with fuzzy n-gram matching.
- Test `ai4bharat-transliteration` install first (heavy dependencies). If it fails, rule-based mapping stays the default; the library is the optional upgrade.
Done when:
- [ ] Hinglish eval queries measured separately; no claim until they pass

### Step 7: Intent classification + entity masking
Files: `intent.py`, `query.py`, `knowledge.py`
Do:
- Replace seed with `intent_seed.tsv` (curated, same format). Mask entities with TYPED placeholders (`__COMPANY__`, `__PERSON__`, `__LOCATION__`, `__PRODUCT__`, `__LANG__`), the SAME extractor on seed data and live queries.
- Entity linking default = LOCAL label index (SQLite FTS built from a Wikidata dump, restricted to popular entities, multilingual labels + Latin transliteration). Remote Wikidata API only as opt-in (privacy and latency).
- Non-English default classifier (full profile): multilingual-e5-small, ONNX int8, lazy, warmed up at startup in the background. Use `query: ` / `passage: ` prefixes. Confidence = top-1 vs top-2 margin, thresholds calibrated per language on held-out data and stored in a JSON table (not hardcoded).
- Naive Bayes stays for English. For non-English it returns `general` when the embedding model is not loaded. Calibrate its threshold with a margin as well.
- Intent classes to handle in retrieval, not only labels: informational, navigational, coding, news/current events, comparison, local, entity/cast/list.
Done when:
- [ ] intent accuracy per language on held-out queries reported
- [ ] unknown-intent queries fall to `general` and still return full-web results

### Step 8: Date/time parsing
Files: `query.py`
Do:
- dateparser, lazy import, only when a temporal cue is detected. Pass `languages=[detected_lang]`.
- Timezone from an explicit `tz` parameter (IANA name) or server setting. Default UTC. Never from Accept-Language.
- Guard false positives ("may", "march", "sat", "second"): require a temporal anchor/pattern.
- Resolve "कल" using verb tense. If still ambiguous, search both windows and say so.
- Day windows via dateparser and the offset table. The `holidays` library is ONLY for named holidays; check its coverage for the festivals you need.
- Keep `calendar_days.tsv` as fallback. Delete `temporal_phrasing.tsv` only after the new path passes tests.
Done when:
- [ ] tests for en/hi/gu temporal phrases and the false-positive words

### Step 9: Crawler, live discovery, safety (Priority 1 and 5)
Files: `crawler.py`, `engine.py`
Do:
- Keep the existing polite crawler (robots.txt, per-host queues, timeouts).
- Query-aware discovery: for the current query, find candidates from (a) sitemaps and feeds, (b) internal links of already-relevant pages, (c) optional external providers if configured. Score URLs by query terms, URL/title signals, domain quality, crawl history. Strict per-domain budgets, concurrency limits, retry limits.
- Extract clean text, title, language, dates (verified), canonical URL, passages. Trafilatura optional with the existing extractor as fallback. charset-normalizer when Content-Type is missing or wrong.
- Dedup: canonical URLs; simhash 64-bit with a minimum text length, character shingles for CJK/Thai, hamming distance 3 or less.
- Incremental indexing: new pages become searchable as soon as processed. Search never waits for crawling.
- Honesty: if live discovery fails, report it in the response. Never claim a page was crawled when it was not.
- SSRF guard: only http/https; resolve DNS and check the IP AT CONNECT TIME (stops DNS rebinding); re-check every redirect; block private, loopback, link-local, metadata (169.254.169.254), IPv6 (`::1`, `fc00::/7`, `fe80::/10`), IPv4-mapped IPv6, and decimal/octal/hex IP forms; response-size limits; crawl-trap protection (depth limits, URL pattern/parameter caps, per-domain page caps).
- Feeds: single `news_feeds.tsv` with `url<TAB>lang<TAB>region<TAB>category`. Validate lang code (BCP-47/639-3) and category from a fixed list. Validator drops dead feeds, checks entries and update frequency. Store title, short snippet and link only.
Done when:
- [ ] SSRF tests: private IP, redirect to private IP, DNS rebinding simulation, decimal IP, IPv6
- [ ] crawl-trap test; duplicate test; live-discovery success rate recorded
- [ ] failures are logged and surfaced in results

### Step 10: Provider fusion
Files: `engine.py`, new `providers/`
Do:
- Optional external providers behind a common interface, configured by the user (API key via config; none enabled by default).
- Run local retrieval and providers concurrently with timeouts. A slow or failing provider never delays or removes local results.
- Merge with Reciprocal Rank Fusion. Tag each result with its provider. Deduplicate by canonical URL.
Done when:
- [ ] tests: provider timeout, provider error, duplicate across providers, local-only mode

### Step 11: Snippets + result formatting (Priority 4)
Files: `engine.py`, snippet module
Do:
- Title, canonical URL, query-relevant snippet generated from real indexed/fetched content. Highlight query terms and the best passage.
- Intent-specific selection: coding queries prefer pages with usable code; cast/list queries prefer pages containing the list; official-docs queries prefer the official source (detected by data such as domain-quality and canonical signals, not a hand-coded site list).
- Accurate total counts and positions; provider and freshness/crawl status; honest empty-result messages (not found / not indexed / unavailable).
- Preserve the user's query and language. Keep CLI and `--pretty` output compatible.
Done when:
- [ ] snippet tests (relevance, language, highlighting), empty-result tests

### Step 12: Optional semantic and rerank plugins
Files: `plugins/`
Do:
- Vector index (FAISS or Qdrant), multilingual-e5-small embeddings with prefixes, hybrid with BM25 via RRF. Off by default (`vector_index=true`). This is the component that provides true cross-language retrieval.
- Reranker: use only if eval shows a gain. On CPU use a small reranker; `bge-reranker-v2-m3` needs a GPU. Time budget (`rerank_budget_ms`) with timeout: rerank what fits, keep BM25 order for the rest.
- Translation (optional, lazy): argostranslate or IndicTrans2; search original + translated query, merge with RRF. NLLB-200 excluded for commercial use. Check each license, record it.
- Optional NER (GLiNER or spaCy `xx_ent_wiki_sm`), off by default on CPU.
Done when:
- [ ] each plugin shows a measured gain, or stays disabled and documented
- [ ] plugin missing = core search unaffected (tested)

### Step 13: Evaluation hardening + cleanup
Do:
- Add public sets: MIRACL (has Hindi, no Gujarati), check IndicIRSuite and its license for more Indic coverage. Mr.TyDi has neither Hindi nor Gujarati. These are Wikipedia-based, so also keep the web-crawl eval.
- Per-language custom queries: at least 50 each for languages you want to claim. 50 queries give wide uncertainty (about +/- 0.1 on MRR), so report bootstrap CIs.
- "Supported" = significantly better than that language's own baseline (BM25-only) and passes the regression tests, in the profile tested. No fixed global threshold.
- Remove replaced files (`stopwords_hi.txt`, `stopwords_gu.txt`, `temporal_phrasing.tsv`, `result_formats.tsv`) only now, after tests pass.
- Write `requirements.txt` (base and full groups), README with one-command setup, `benchmark.py` (per-stage latency, index size, at realistic corpus size).
Done when:
- [ ] final report below produced from real runs

## 5. Targets (goals, not claims)

| Metric | Goal | Rule |
|---|---|---|
| NDCG@10, MRR@10 (en) | no regression vs baseline; improve if measured | report CIs |
| Entity-confusion regression | pass | must stay passing |
| Query parse | under 5 ms | measured |
| BM25 retrieval | under 50 ms p95 | measured at large corpus |
| Embedding intent (loaded) | under 50 ms p95 on CPU | measure; first load excluded by warm-up |
| Full search (core) | under 200 ms p95 | measured |
| New files per language | 0 | by construction |

Do not copy these numbers into a "result" until they were measured.

## 6. Final report template (agent fills with real data)

1. Root causes found in the existing code
2. Files changed and why
3. Improvements implemented and how they work
4. Before/after metrics per language, with confidence intervals; sample query results
5. Tests run, failures remaining, regressions
6. Config, setup commands, dependencies, license table (with links, or UNVERIFIED)
7. Known limits; languages claimed (with the profile that passed)
8. Next three highest-impact improvements, based on measured evidence

## 7. Paste-ready prompt for each session

```
Read main.md. Do ONLY Step <N>. Follow section 0 rules. Keep all 135 tests passing.
Update docs/progress.md with test results and eval numbers. Do not start the next step.
Reply with: files changed, tests run (counts), eval numbers vs baseline, open problems.
```
