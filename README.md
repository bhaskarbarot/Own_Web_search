# OwnSearch Independent

OwnSearch crawls pages directly, extracts their text, ranks matching pages and
returns cited source excerpts. The running search uses Python's standard library
and bounded memory caches. It has no search-provider integration, account quota,
paid API, SQLite database, or persistent document index.

The previous metasearch implementation is preserved on branch `dependent` at
`489d8dc`. This implementation is on branch `Independent`.

## Run

```bash
./run.sh
# Open http://127.0.0.1:8765/ui
```

Python 3.10+ is required. No package installation or other service is required.
Optional Unicode/date helpers are available with `pip install -e '.[text]'`.
The launcher never installs or starts another search engine.

Starting sites are editable in [sources.txt](sources.txt). The owner's initial
selection covers Wikipedia, news publishers, Python documentation and Stack
Overflow. To use a different list, set `OWNSEARCH_SOURCES_FILE` to its absolute
path. Set it to an empty string to use only explicit starting URLs and site filters.
A source list is configuration, not a collection of indexed documents.

```bash
python3 main.py search 'python tutorial' --seed https://docs.python.org/3/ --answer
python3 main.py serve --port 8765
python3 main.py status
```

The UI supports starting URLs, site, language, publication freshness/date operators,
file types, exact phrases, exclusions, images, video pages, ranked links and cited
excerpts. Images and video metadata come from fetched pages. PDF and Office parsing
runs in an isolated process with time/resource limits and OCR disabled. Turning
off “Crawl new pages” searches only unexpired memory cache entries.

## How discovery works

A query starts with configured sites, explicit page URLs or a `site:` root.
OwnSearch reads robots rules, extracts actual links, follows declared sitemaps and
feeds, prioritizes links using the query, fetches pages and ranks their text with
BM25 and owned relevance checks. Crawl scope stays within configured origins;
add both a publisher's feed origin and article origin when they differ. It never
guesses article addresses or substitutes another search engine behind the scenes.

Unknown URLs cannot be discovered from query words alone. A cold request can take
seconds; a bounded query-time crawler cannot search the whole web in milliseconds.
Coverage depends on the starting sites, links and query budget. Some sites deny
crawling. Those denials remain visible and are respected. Memory caches expire and
are lost on restart. There is no subscription quota; concurrency, bytes, deadlines
and website politeness remain bounded.

A cited answer is an extract from a fetched page, not a guarantee that the source
is correct. Instruction-like source text cannot supply answers. Missing evidence
produces an explicit abstention. Publication filters require actual publication
metadata; a fetch time or sitemap modification date is not a publication date.

## API

`GET /health`, `GET /stats`, `GET /ui` and `POST /search` are available.

```json
{"query":"orbital guidance","seeds":["https://your-site.example/"],"limit":10,"answer_mode":true,"fetch_pages":true}
```

Use `site`, `lang`, `freshness`, `filetype`, `timezone`, `search_type` (`web`,
`images`, `video`), `offset`, `explain` and `timeout_ms` as optional search fields.
`GET /search?q=...&fetch_pages=false` searches the cache without network access.

The server binds to localhost by default. For remote access, create a local API
key with `python3 main.py create-key NAME`, then start `serve --require-auth`.
API keys are local configuration files, not third-party service credentials.
There are no ingestion, database maintenance or external-provider endpoints.
Existing ignored `data/` contents are left intact but document databases are not
read by the new runtime. Legacy provider settings are ignored.

## Verification

```bash
python3 -m unittest discover -s tests -q
python3 benchmark.py --output /tmp/independent-benchmark.json
```

The benchmark uses a controlled website and the 300 unsealed development queries
for query parsing. Its fixture metrics are not live web accuracy. Human-review
CSVs and sealed queries remain preserved. See [docs/PROGRESS.md](docs/PROGRESS.md)
and [the rebuild plan](docs/plan/phase-independent-1.md).
