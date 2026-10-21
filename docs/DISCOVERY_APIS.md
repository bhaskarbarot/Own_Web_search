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
