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
