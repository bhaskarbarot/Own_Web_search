# Dependent implementation checkpoint

The user requested preserving this implementation as `dependent`, then creating
`Independent` to replace external search-engine discovery with owned query-time
crawling and bounded caching, without a database or paid search API.

Checkpoint: Phase 1 runtime 5709c59, complete evaluation/report 50d5c2a.
303 release tests passed; 300 dev searches and 30 repeats were recorded.
Relevance judgments remain absent. These historical measurements describe the
dependent implementation and cannot be attributed to its replacement.

The saved implementation uses local SearXNG for broad URL discovery. Keeping a
local copy did not remove its upstream search-engine dependencies. The new
branch must remove that discovery path, preserve existing user data, retain
robots/SSRF/deadline safeguards, and describe seed/coverage limitations honestly.
