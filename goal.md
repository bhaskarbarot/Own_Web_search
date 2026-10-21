# own_search: Project Goal (read this fully before touching any code)

This file is the single source of truth for the project. Any LLM or developer
(Codex, Claude, Gemini, Antigravity, Copilot, a human) must read it completely
before making changes. If a request conflicts with this file, this file wins
unless the owner explicitly changes it here.

---

## 1. One-sentence goal

Build a **free, open-source, local web search tool for AI agents**, installed
with `pip install own_search`, usable in a few lines of Python, with **unlimited
local use, no API keys, no accounts, no paid services and no dependency on any
existing search engine**, aiming for **90%+ accuracy on a clearly defined,
independently measured metric**.

## 2. Why this exists (the market gap)

- AI agents need a web search tool.
- Most good search tools (Google, Bing, Brave, Tavily, Serper, SerpAPI, Firecrawl
  search and others) are **paid or rate-limited**.
- The common free option (DuckDuckGo wrappers) is **limited, unreliable, and
  gets blocked or rate-limited**.
- There is no good **unlimited, local, filterable** search tool that an
  AI/ML engineer can install and use immediately.

own_search fills that gap. It runs entirely on the user's own machine.

## 3. The core idea (how it works)

We are **not** building a big index of the web. We are **not** Google.
We do **not** crawl millions of pages into a giant database. We have no big
servers.

Instead, own_search works **per query, on demand, on the user's machine**:

1. An agent (or person) sends a query plus optional filters.
2. own_search **understands the query** (entities, intent, facets, dates,
   phrases, exclusions, language).
3. It **plans where to look**: picks relevant starting sources, follows real
   links, sitemaps and feeds from pages it actually fetched.
4. It **fetches only the few relevant pages** needed, within time and byte
   budgets, respecting robots.txt.
5. It **extracts text, metadata, links, PDFs and images** from those pages.
6. It **ranks passages by direct evidence** that they answer the query.
7. It **returns text results with links, passages, citations, timestamps and
   an honest confidence/abstain signal**, shaped by the user's filters.
8. It keeps a **small, bounded, local cache** (memory plus optional on-disk
   SQLite with TTL) of pages the user's own searches already fetched, so repeat
   and related searches get faster over time. This is a cache, not a web index.

## 4. Non-goals (do NOT build these)

- No full-web crawl. No million-page database. No central server.
- No paid API as a requirement. No API keys required for core function.
- No wrapper around Google, Bing, Brave, DuckDuckGo, SearXNG, Yahoo, Startpage,
  Mojeek, Marginalia, Yandex, or any other search engine or metasearch service,
  in any form: not as a main path, not as a fallback, not as "temporary".
- No bypassing of CAPTCHAs, paywalls, logins, 403s, rate limits or robots.txt.
- No fake or invented results to look good.

## 5. STRICT RULES FOR ANY LLM WORKING ON THIS REPO

These rules are mandatory. Violating them is a defect, not a shortcut.

1. **No hallucination.** Never invent URLs, page contents, citations, benchmark
   numbers, test results, library behaviour, or "it works" claims. If you did
   not run it, do not say it passed. If you are unsure, say so and verify.
2. **No hardcoding.** No hardcoded queries, expected URLs, expected answers,
   per-topic or per-benchmark rules, or special cases for evaluation queries.
   Benchmark queries must get exactly the same treatment as any other query.
3. **No regex for meaning.** Do not use regular expressions for query
   understanding, topic detection, intent, relevance, or answer extraction.
   Regex is allowed only for strictly syntactic work where a proper parser does
   not exist (for example tokenising a URL fragment), and each use must be
   documented with a comment explaining why. Prefer real parsers: `urllib`,
   an HTML parser, a PDF parser, a date parser, tokenizers, statistical or
   small-model methods.
4. **No search-engine dependencies.** Do not import, call, scrape, proxy or
   embed Google, Bing, Brave, DuckDuckGo, SearXNG or any search/metasearch
   service. Check `pyproject.toml` before adding a dependency and justify each
   one in `docs/DEPENDENCIES.md`. Prefer the Python standard library.
5. **Fetch only what is allowed.** Respect robots.txt, rate limits, timeouts,
   response-size limits and SSRF protection. Honour site terms. Report blocked
   or failed fetches honestly instead of hiding them.
6. **Measure before and after.** Every change that claims to improve quality or
   speed must be measured on the dev set against a recorded baseline. Revert
   changes that do not help.
7. **Never tune on the sealed test set.** Run it once, at the end.
8. **Honest reporting.** Report actual numbers with confidence intervals.
   Never claim "90% accuracy" without the metric definition, the data, and the
   evidence. Separate retrieval quality from answer correctness.
9. **Add a regression test for every confirmed failure.** Keep all existing
   tests passing.
10. **Do not break the public API** (Section 7) without updating this file,
    the README and the tests.
11. **Plan, then execute in small steps.** Write a short plan, make one change
    at a time, test, measure, commit.
12. **No silent scope creep.** If something is outside this file, ask the owner.

## 6. Accuracy: what "90%+" means here

"Accurate" must be measured with defined metrics, never claimed by feeling.

**Primary targets (on the sealed test set, with 95% bootstrap CIs):**

| Metric | Target |
|---|---|
| Strict P@5 (graded relevance >= 2) | >= 0.90 on in-scope queries |
| NDCG@10 | >= 0.90 on in-scope queries |
| Citation support rate (answer claims backed by returned passages) | >= 0.90 |
| Fabricated URL count | 0 |
| Abstention precision on unanswerable / nonexistent-entity queries | >= 0.95 |
| Zero-result rate on in-scope queries | < 5% |

**Honest scope note.** Without a big index, accuracy depends on discovering the
right pages from limited starting points. So accuracy must always be reported
together with **coverage**: the share of eval queries for which a relevant page
was reachable by the engine's discovery. When the engine cannot find good
evidence it must say so (`answerable: false`) instead of guessing. A smaller
number of correct, cited results is better than ten plausible-looking ones.

**Evaluation protocol:** versioned query set (>= 500 queries across
programming, docs, news, research, business, finance, general knowledge,
local, ambiguous, adversarial, nonexistent-entity, verbose, exact-phrase,
operators, multilingual); 60% dev / 40% sealed test split by stable hash;
graded 0-3 relevance with a written rubric; pooled judgments; LLM judge
calibrated against human grades; 10% human spot-check; no judging by the
same code path that produced the result.

## 7. Target public API (what users will see)

Install and use in a few lines:

```python
pip install own_search

from own_search import search_tool

results = search_tool(
    "how does cargo offline mode work",
    max_results=5,
)
print(results.text)          # readable text with links and citations
```

Rich usage with filters (all optional, all settable from code):

```python
results = search_tool(
    query="latest PostgreSQL security fixes",
    max_results=10,
    sites=["postgresql.org"],            # include only these domains
    exclude_sites=["example-spam.com"],
    content_type="news",                 # docs | news | research | code | general | pdf | image
    date_from="2026-01-01",
    date_to=None,
    freshness="week",                    # any | day | week | month | year
    language="en",
    file_types=["pdf"],                  # pdf, image, html, ...
    exact_phrase=None,
    exclude_terms=["tutorial"],
    time_budget_s=3.0,                   # max time to spend
    use_cache=True,
    cache_ttl="auto",                    # auto picks short TTL for news, long for docs
    output="json",                       # text | json | markdown
    include_passages=True,
    include_images=False,
    export="results.pdf",                # optional: save results as PDF
)
```

Required properties of the return value:

- Ranked results with: rank, title, URL, best passage(s), source timestamp
  (when known), retrieval time, score, source type (official / primary /
  secondary / unknown), and why it matched.
- `answerable: bool`, an `evidence` list, and a plain-language `status`
  (for example "insufficient evidence", "sources conflict").
- A provider/fetch report listing blocked, failed or skipped pages honestly.
- Deterministic structure so agents can parse it reliably.

**Agent integration (must be one-line easy):**

- Plain Python function: `search_tool(...)`.
- Ready-made tool definitions: OpenAI/Anthropic function-calling schema,
  LangChain tool, LlamaIndex tool, and an **MCP server** (`own_search mcp`).
- Async version: `await asearch_tool(...)`.
- CLI: `own_search "query" --site docs.python.org --json`.

**Documents and images:**

- Find and extract text from **PDFs** and return PDF links and passages.
- Find **images** on relevant pages (URL, alt text, caption, source page).
- Optional **export of results to PDF** (and Markdown/JSON).
- (Owner to confirm exact meaning: "results in PDF" could mean finding PDFs,
  exporting results as PDF, or both. Support both unless told otherwise.)

## 8. Pipeline design (how to make it accurate and fast)

**Query understanding.** Detect entities, intent, facets, dates, exclusions,
exact phrases and language, with a small statistical or model-based component
and conservative defaults. Low-confidence intent must never narrow the
search. Rewrite verbose requests into focused queries. No regex for meaning.

**Source planning (discovery without any search engine).**
- A **user-editable source registry** (`sources.txt` / `sources.yaml`) of
  starting sites with short descriptions. This is data the user owns, not
  ranking rules.
- Source selection by similarity between the query and source descriptions,
  not by hardcoded topic switches.
- Follow **real links, sitemaps, RSS/Atom feeds and site-provided search pages**
  discovered from pages actually fetched. Never invent URLs.
- Optional pluggable **site-native public APIs** (for example a documentation
  site's own API) as independent adapters, off by default, never required.
- A bounded **local source memory** that remembers which domains and paths
  produced useful results for the user, so discovery improves with use.

**Fetching.** Async, bounded concurrency, per-host politeness, deadlines,
robots.txt, early byte limits, SSRF protection, connection reuse, progressive
return. Cancel stragglers once enough strong evidence exists.

**Extraction.** Main-content extraction (strip navigation and ads), metadata,
publication dates, canonical URLs, PDF text, image metadata.

**Ranking.** Passage-level scoring (BM25 first), entity and phrase evidence,
freshness only when the query needs it, structural source-authority signals
(official ownership evidence), duplicate and mobile/AMP/print variant removal,
per-domain caps, namesake disambiguation. Optional small CPU embedding or
reranker model, only if it measurably helps and stays optional.

**Answers.** Return cited passages. Label each claim VERIFIED (primary source
or two independent sources), SOURCE EXCERPT, or INFERENCE. Show conflicts.
Abstain when evidence is weak or about a different entity.

**Speed (honest expectations).**
- Warm / cached searches: aim for milliseconds.
- Cold searches that must fetch live pages: seconds are realistic. Improve with
  parallel fetching, early return of first strong results, progressive output,
  and the local cache. Do not claim millisecond cold-web latency.
- Finance quotes and breaking news are fetched live and never served stale as
  current.

## 9. Repository and documentation expectations

Not the top priority (accuracy comes first), but required before release:

- `README.md`: what it is, install, quick start, filter reference, agent
  integration examples (function-calling, LangChain, MCP), limitations.
- `docs/`: architecture, filters reference, configuration, evaluation method,
  dependency justification, contributing guide, honest limitations.
- `tests/`: unit tests plus offline fixtures; public-network tests are separate
  and clearly marked.
- `pyproject.toml` with the package name `own_search` (verify the name is
  available on PyPI before publishing), minimal dependencies, Python version
  range stated.
- Open-source licence chosen by the owner.

## 10. Roadmap (priority order)

1. **Accuracy first.** Fix the evaluation set, grading and baseline. Improve
   query understanding, source planning, passage ranking, source authority and
   evidence verification. Measure every change.
2. **Faster pipeline.** Profile, then parallelise fetching, return progressive
   results, add the bounded persistent cache. Report cold and warm latency
   (p50/p95/p99) separately.
3. **Agent interface.** Stable `search_tool` API, filters, JSON schema, MCP
   server, LangChain/LlamaIndex wrappers.
4. **PDF and image support** and export formats.
5. **Packaging and docs.** `pip install`, README, examples, release.

## 11. Definition of done

- `pip install own_search` then three lines of Python returns cited results.
- All filters in Section 7 work and are tested.
- Sealed-test results meet or honestly report against Section 6 targets.
- No dependency on any search engine or paid API anywhere in the code.
- No hardcoded queries, URLs, answers or topic rules; no regex for meaning.
- Every limitation is documented honestly in the README.

## 12. Instructions for the LLM at the start of every session

1. Read this file completely.
2. Read `docs/PROGRESS.md` for current state and the last handoff.
3. State back, in two sentences, what the project is and what you will do now.
4. Follow Section 5 strictly. When unsure, ask instead of guessing.
5. Finish by updating `docs/PROGRESS.md` with what changed, measured results,
   failures and next steps.