# Runtime dependencies and outbound policy

The active core uses Python's standard library. No package was added for source
planning, native form discovery, evaluation or caching.

- `html.parser`, `urllib.parse`: parse actual HTML controls, origins and safe GET
  submissions; never guess a site's endpoint or forward to a search service.
- `collections`, `math`: TF-IDF similarity and the existing locally trained small
  statistical intent classifier. Registry descriptions are user-editable data.
- `sqlite3` (planned optional cache): Python standard library only; bounded TTL
  storage of pages already fetched for user queries, not a full-web index.
- Existing optional `regex`, `stopwordsiso`, `dateparser`, `holidays` and
  `charset-normalizer`: Unicode tokenization, multilingual stopwords, calendar
  parsing, explicit-country holiday parsing and text decoding. All have core
  fallbacks and make no search-service calls. No download is initiated by search.

Dedicated web search/metasearch services listed in goal.md are forbidden outbound
sources, including same-origin form targets and redirects. The host exclusion
policy is a dependency/safety rule, not a relevance or expected-domain mapping.
A permitted content site's own search form may be used only when discovered from
its actual fetched HTML, same-origin, GET, semantically marked as search, and
allowed by its robots policy. Missing/blocked forms are reported, not replaced by
invented endpoints, other identities, proxies, or external search providers.
