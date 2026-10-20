> Historical integration smoke report. Current measurements and limits: [SEARCH_QUALITY_REPORT.md](SEARCH_QUALITY_REPORT.md).

# Bundled discovery source verification

The user requested reusing the cloned SearXNG implementation in `searxxxing/`.
That source copy is now wired to OwnSearch through the existing JSON adapter.
It does not require the original `repo/searxng` clone at runtime or a hosted
SearXNG instance. It still relies on external search indexes and its pinned
Python libraries. This is reuse of AGPL-licensed upstream code, not newly
authored search-engine logic.

## Changes

- `searxxxing/`: all 1,008 upstream tracked paths, including one relative symlink;
  source revision `22c64b8d394b680c7ea96be25f36dad14126420a`. No nested Git history.
  All 1,007 regular files match the clone byte for byte. License and attribution
  are preserved. `OWNSEARCH_UPSTREAM.json` records source hashes. Added archive
  version metadata and instructions; no upstream algorithms/adapters changed.
- `ownsearch/bundled.py`: isolated pinned-package setup, private random secret,
  localhost-only Granian launcher and instance status. This is integration glue.
- `ownsearch/cli.py`: `discovery setup|serve|status` commands.
- `main.py`: propagate CLI return codes so setup failures are nonzero.
- `ownsearch/coordinator.py`: diagnostics point to the bundled setup commands.
- `tests/test_bundled.py`: six offline checks, including source integrity,
  configuration preservation, secret permissions and the actual launcher path.
- README, live-web documentation and progress notes describe the bundled option.

Setup created small ignored `.runtime/searxxxing/` configuration/cache files and
merged three provider settings into ignored `data/ownsearch.json`. It does not
create a document database or load an internet corpus. Existing corpus files
were retained. Upstream has expiring engine/data metadata caches, not a new
OwnSearch page index. The copied backend is running at `http://127.0.0.1:8888`.
Stop the foreground `discovery serve` process with Ctrl+C when running it yourself.

## Actual verification

All **219 tests passed in 47.084 seconds** using the existing base-profile virtual
environment. An initial sandboxed run could not open localhost fixture sockets;
the complete rerun with those sockets permitted passed. See
[`tests.txt`](evaluation/bundled-source/tests.txt).

The bundled process identified its ten configured adapters through `/config`.
`providers --check` received 40 candidate rows and returned 10 results; its
provider coordination time was 875.01 ms, with upstream warnings retained.

Recorded real, uncached smoke queries:

| Query | Returned pages | Time | Page enrichment |
|---|---:|---:|---|
| give me ramayan serial by ramanand sagar character names | 9 | 1327.19 ms | disabled |
| give me doremon cartoon character names | 3 | 1489.93 ms | disabled |
| Python requests timeout parameter documentation | 9 | 5168.16 ms | 3 pages fetched |

The user's earlier Ramayan and Doraemon outputs had zero results. These new
probes demonstrate URL discovery beyond the old corpus. They do not establish
that every returned page is useful. No persistent pages were written in the
three probes. Source evidence and traces are saved in
[`live-smoke.json`](evaluation/bundled-source/live-smoke.json).

## Remaining limits

- A separate upstream probe reported Brave suspended for too many requests,
  DuckDuckGo CAPTCHA, and Google suspended for access denied. These were not
  bypassed or described as successful. Available sources still returned pages.
- Official Requests documentation ranked ninth in the no-fetch documentation
  probe; source bundling has not fixed that relevance problem.
- Cold responses are seconds for these samples, especially with page fetching.
  No general subsecond or cached-performance claim follows from these numbers.
- Three smoke queries were captured, not the full `query.md` benchmark. They
  have no independent relevance or answer-correctness judgments. P@5, MRR,
  NDCG@10 and broad accuracy are therefore not reported for this smoke run.
  The earlier full benchmark plan remains pending; **no 90% accuracy green flag**.

## Run

```sh
python3 main.py discovery setup
python3 main.py discovery serve
# In another terminal:
python3 main.py discovery status
python3 main.py providers --check
python3 main.py search "your unfamiliar query" --pretty
```

Setup is already complete on this machine. Keep the source checkout, including
`searxxxing/`; the OwnSearch-only wheel does not include this third-party tree.
