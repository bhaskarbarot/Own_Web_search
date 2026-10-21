# Official discovery APIs

Adapters are independent, disabled unless named in vertical_providers, and use
bounded public HTTPS requests through the pinned safe fetcher. Result URLs must
be present in actual API responses. No result-page URLs are guessed from IDs.
Revision/activity timestamps are not asserted to be publication dates.

## Wikipedia and Wikidata

Wikipedia uses MediaWiki generator search with info/fullurl and plaintext
extracts. Wikidata uses wbsearchentities and returned concepturi metadata.
Neither converts an API match into a verified factual answer.

Official contracts: [MediaWiki search](https://www.mediawiki.org/wiki/API:Search),
[page information](https://www.mediawiki.org/wiki/API:Info), and
[Wikibase API](https://www.mediawiki.org/wiki/Wikibase/API).

Configure OWNSEARCH_VERTICAL_PROVIDERS=wikipedia,wikidata, or select either
individually. Routing can skip a vertical; configured general search remains
available. vertical_max_providers limits simultaneous independent verticals.
The integration is opt-in until the dev ablation qualifies default activation.

## GitHub

Public repository and issue search uses returned html_url, title/description or
issue body. Explicit open-issue requests preserve the API is:open qualifier.
Unauthenticated spacing is at least 6.1 seconds, with a 60/hour budget; returned
quota/reset headers can suspend further requests without discarding valid data.
An optional token is passed only as an HTTPS authorization header.

Contracts: [GitHub search](https://docs.github.com/en/rest/search/search) and
[rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

## PyPI

An explicit Python/PyPI package name or pip-install target enables an exact
metadata lookup. Owner-published project links and package URLs are read from
info, never generated. Unknown projects yield an empty batch without declaring
the API unhealthy. General requests to find Python libraries are not falsely
treated as a full-text PyPI search. Large metadata responses remain subject to
the ordinary two-megabyte response budget.

Contracts: [PyPI JSON API](https://docs.pypi.org/api/json/) and
[project URLs](https://docs.pypi.org/project_metadata/).

## npm

Full-text registry search uses the documented objects/package/links response.
Only returned npm, homepage and repository links become candidates; absent links
are not generated. Version modification metadata is not used as a page's
publication timestamp. [Official registry API](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md).

## crates.io

Search returns crate metadata. Documentation, homepage and repository links are
used only if returned; no docs.rs or crate-page URL is generated from a name.
[Official response types](https://github.com/rust-lang/crates.io/blob/main/crates/crates_io_api_types/src/lib.rs)
and [data-access policy](https://crates.io/data-access). Existing identifying
User-Agent, request spacing, response budgets and access-denial handling apply.

## arXiv

Uses Atom metadata only, with actual alternate page links and original published
timestamps. DTD/entity declarations are rejected. A process-wide connection lock
and at least three-second pacing cover adapter instances; a bounded 24-hour
metadata cache retains source retrieval timestamps. Operators running multiple
processes/machines must coordinate their aggregate traffic as required by the
service. The adapter never follows an error into an access-denial bypass.

[Official manual](https://info.arxiv.org/help/api/user-manual.html) and
[API terms](https://info.arxiv.org/help/api/tou.html).
# OpenAlex

Uses the official works search endpoint, returned landing/DOI/work URLs and
publication dates. Abstracts contain only words supplied in the inverted index.
Basic requests currently work without a key; an optional key is sent in an HTTPS
Bearer header. Decimal remaining-quota values and relative reset seconds are
honored. Contract: https://help.openalex.org/api/authentication/ and
https://developers.openalex.org/api-reference/works/get-a-list-of-works.


## StackExchange

Uses [advanced search](https://api.stackexchange.com/docs/advanced-search), actual
question links/body and creation dates. The site is explicit configuration,
not inferred from topic domains. Honors [body backoff and quota](https://api.stackexchange.com/docs/throttle),
with a bounded 60-second cache to avoid repeating identical requests. Cache hits
preserve source retrieval timestamps. No account or key is needed for basic calls.


## Free/self-hosted scope (user clarification, 2026-10-21)

The newly added Marginalia and Mojeek account integrations were removed. Their
historical commits/probe-free fixture artifacts remain auditable, but the runtime
does not configure or call them. Existing Brave compatibility remains opt-in and
disabled here. No paid service, new key or account is required. SearXNG runs locally;
the local index/crawler are owned code. External sites and free official APIs still
apply their own limits. They are supplements, not an unlimited independent index.


## Origin, sitemap and feed discovery

A single explicit site: operand can seed its public HTTPS origin when general
discovery returned no candidate for that site. This is only a fetch target; an
unfetched origin cannot become a result. Fetch robots and page normally; follow
actual same-origin page links or a robots-declared sitemap with at most one
actual child index. Never guess an internal search route or undocumented API.

For news/freshness requests, one same-origin RSS/Atom/JSON Feed link from fetched
HTML can supply at most two candidate URLs. Preserve the declaration and feed
entry provenance. Follow nofollow, robots, pinned DNS, shared bytes/requests and
the search deadline. Feed updated/modified dates are not publication evidence.
