# Relevance refactor review — 14 October 2026

Implemented on `wip/data-driven-relevance`; changes remain local. Main remains
available as the previous working version. The six-query smoke check returns
sourced answers or relevant pages, but an **overall green flag is withheld**.
Not every broader relevance metric improved, and this run does not establish
reliable cold-start discovery or tick-by-tick market coverage.

## What changed

- Topic-free intent templates replace active topic-filled training examples.
  Query subjects retain their names; operators/exclusions do not train intent.
- Wikidata labels/aliases, contextual search and related organization names
  disambiguate entities. Inflections do not stop at an unrelated exact label.
  Facts match the entity's own property labels; preferred claims win.
- Discovery uses entity URL properties, balanced source budgets, focused anchor
  walks and bounded sitemaps. It reserves time to fetch selected pages. Publisher
  feed metadata is persisted; feed headlines survive article fetch failures.
- Ranking removes the Python/domain/path/pull-request and financial word-list
  rules. Linked names are required, weak scores are cut, and generic subject
  density/title phrasing help rank focused guides over incidental references.
- CLI/API responses expose sourced answers. Market history uses daily bars,
  identifies its price basis, and labels an incomplete session. Quote change
  uses the previous trading session, not the chart window's starting close.
- Tests disable external services and use an isolated, versioned corpus.

The cloned SearXNG source was reviewed locally. Its API/filter forwarding,
upstream-error reporting, time-budget and duplicate-merging patterns informed
our provider adapter. SearXNG itself remains optional; its external search
engines have not been enabled automatically.

## Frozen-corpus comparison

The comparison uses the same snapshot of the existing 811-document index and
50 original judgments. Main (`e55a705`) was exported to a separate directory.
The provided baseline was reproduced: NDCG@10 0.7499, MRR@10 0.7356, P@5 0.172.

| Judgment type / metric | Before | After |
|---|---:|---:|
| URL NDCG@10 | 0.7499 | 0.7560 |
| URL MRR@10 | 0.7356 | 0.7333 |
| URL P@5 | 0.1720 | 0.1840 |
| URL Recall@100 | 0.8900 | 0.8800 |
| Host NDCG@10 | 0.8614 | 0.8360 |
| Host MRR@10 | 0.8529 | 0.8200 |
| Host P@5 | 0.1840 | 0.1920 |

Host evaluation projects the old URL grades onto exact host names and counts
repeated pages from one host once. Its numbers assess source retrieval, not
answer correctness. Some old judgments are unsuitable for current-news/price
acceptance: they grade a static Modi biography as news and a company Wikipedia
page as a stock-price answer. They were retained so the comparison stays honest.
Requests-documentation ranking also regresses in the host projection; that
regression is not explained away by the stale news judgment.

Local evaluation does not call live linking/providers. It isolates the lexical
ranking changes. Recorded latency depends on this machine and its warm index;
this is not a sustained load or production-readiness benchmark.

Raw results: [URL before](evaluation/urls-before.json),
[URL after](evaluation/urls-after.json), [host before](evaluation/hosts-before.json),
[host after](evaluation/hosts-after.json).

## Six-query check against web search

The final run used the default 20-second live network budget, a warmed knowledge
cache and an acceptance index accumulated during debugging. Provider errors are
preserved in [the full run](evaluation/live-six-queries.json).

| Query | OwnSearch result | Comparison / qualification |
|---|---|---|
| Nvidia live price | NVDA regular-session quote, timestamp and corrected daily change | $228.52, +$2.20 (+0.97%), prior close $226.32 matches the [Google Finance snapshot](https://www.google.com/finance/quote/NVDA:NASDAQ) and [Yahoo history](https://finance.yahoo.com/quote/NVDA/history/). This is the regular-session quote, not an overnight-market quote. |
| Today's Trump headlines | Two dated Guardian reports; unrelated headlines rejected | The White House press-access story agrees with [AP's report](https://apnews.com/article/1a023a8890e8d25d5d293862f4cd47af). Publisher dates fall in the requested rolling day. Some feeds deny bot access. |
| Samrat Ashok birthplace | Ashoka linked by alias; Patna/Pataliputra fact | Matches the place-of-birth statement in [Wikidata Q8589](https://www.wikidata.org/wiki/Q8589). This verifies the knowledge-base statement, not independent historical certainty. |
| TCS 6-month analysis | TCS.NS, INR, 126 observations, adjusted-price statistics and monthly observations | [Yahoo's company/history pages](https://finance.yahoo.com/quote/TCS.NS/history/) confirm instrument/history identity. The latest session is provisional; cached web snapshots do not independently validate the identical intraday six-month return. Arithmetic has independent fixture tests. |
| Inheritance in OOPS | Programming inheritance summary, rather than legal inheritance | Consistent with [Oracle's inheritance explanation](https://docs.oracle.com/javase/tutorial/java/concepts/inheritance.html); the displayed summary cites Wikipedia/Wikidata. |
| Claude docs on MCP | Official remote/local MCP connection guides lead the results | [Local connection guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers) explicitly teaches Claude Desktop integration; [remote connection guide](https://modelcontextprotocol.io/docs/develop/connect-remote-servers) covers remote integration. Broader overview pages can still follow; some official endpoints return 403/timeouts. |

All six return useful sourced output in this snapshot. This is a functional
smoke pass, not proof of universal relevance or dependable fresh discovery on
an empty index. The original strict green flag remains withheld until cold-start
coverage, broader ranking regressions and independently matched market windows
are accepted.

## Reproducing checks

```bash
python3 -m unittest discover -v
python3 scripts/check_relevance.py --data-dir /tmp/ownsearch-acceptance --live --output /tmp/ownsearch-six.json
python3 scripts/evaluate_relevance.py --data-dir /path/to/frozen-corpus --qrels tests/fixtures/legacy_relevance_qrels.json --output /tmp/urls-after.json
python3 scripts/evaluate_relevance.py --engine-root /path/to/main-export --data-dir /path/to/frozen-corpus --qrels tests/fixtures/legacy_host_qrels.json --output /tmp/hosts-before.json
```

The full offline suite passes **95 tests** (`python3 -m unittest discover -v`).
The versioned offline fixtures include 12 deterministic operator cases and
host judgments for the six live acceptance queries. The operator cases pass;
the fixture benchmark is isolated from the production database. Live evaluation
requires public network access. No credentials, API keys or paid services are
needed for these six checks.
