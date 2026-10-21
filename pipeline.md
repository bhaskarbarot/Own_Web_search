# Independent search pipeline

Starting URLs / site filter / memory cache → query parsing → robots policy →
query-prioritized bounded link and sitemap traversal → safe direct fetch →
HTML/text/PDF/Office extraction → lexical ranking and filters → duplicate
collapse → cited source excerpt or abstention → ranked links in the HTML UI.

All runtime implementation is owned code under `ownsearch/`. The default core
requires no external search service or document database. See README.md for scope,
configuration, safety limits and reproduction.
