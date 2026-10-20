# Bundled SearXNG source for OwnSearch

This directory is a source copy of SearXNG, not newly authored OwnSearch search logic.
All 1,008 tracked upstream paths were copied from local `repo/searxng` at commit
`22c64b8d394b680c7ea96be25f36dad14126420a`, including upstream documentation, tests,
static assets, attribution and the AGPL-3.0-or-later license. Git history, caches,
virtual environments and untracked files were excluded. No submodule or original
clone is required at runtime.

`OWNSEARCH_UPSTREAM.json` records SHA-256 hashes of 1,007 regular source files;
the remaining tracked path is the upstream `utils/templates/etc/apache2` symlink.
`searx/version_frozen.py` is added archive metadata so the embedded application
does not misreport the enclosing OwnSearch repository's version.
The added `searx/.gitignore` keeps that metadata in the enclosing repository.
No upstream search algorithms or engine adapters were changed.

From the OwnSearch repository root:

```sh
python3 main.py discovery setup
python3 main.py discovery serve
```

Keep the second command running. In another terminal:

```sh
python3 main.py discovery status
python3 main.py providers --check
python3 main.py search "your query" --pretty
```

Setup installs the pinned upstream requirements into `.runtime/searxxxing/venv`,
creates a random private instance secret and enables JSON on localhost:8888.
Use `discovery setup --port 8890` to choose another unprivileged port.
It merges the localhost endpoint into the selected data directory's
`ownsearch.json`; existing other settings are retained. `--data-dir` is a global
OwnSearch option and belongs before `discovery`. Existing environment overrides
still take precedence. Setup requires package download access on a new machine.
Serve uses the bundled source and Granian WSGI, with Ctrl+C to stop; no Docker,
Valkey server, separate SearXNG install or public SearXNG instance is required.
The launcher is source-checkout tooling; the OwnSearch-only wheel does not bundle
this third-party tree. Keep this folder when distributing the source checkout.

Eleven configured adapters cover general, news and images. All other copied
adapters remain available in source but are not enabled. Per-engine timeout is
2 seconds (1 second for Mwmbl) and maximum request timeout is 2.5 seconds. Search provider errors,
rate limits and challenges remain real limitations; do not bypass them.

This is a bundled metasearch backend: it still contacts external search engines.
It is not an independent internet index. OwnSearch still handles query parsing,
request budgets, page fetching, extraction and final relevance filtering. There
are no query-specific answer or URL overrides in this integration.

Full fetched pages are not added to OwnSearch's corpus by normal live searches.
The upstream backend can store small expiring engine/data metadata caches under
`.runtime/searxxxing/cache`; this is distinct from a searchable page corpus.
Runtime credentials, environments and cache files are ignored by Git. Secrets
are not included in the source copy. The bundled UI identifies SearXNG; preserve
its copyright notices and license when redistributing. No upstream contribution
or claim of original authorship is made by this copy.
