# OwnSearch — pending work

Status as of 2026-10-13: v1.0 committed locally (56 tests passing). Push to GitHub is blocked
(see item 0).

## 0. Setup (first thing tomorrow)
- [ ] Push to GitHub: `gh auth login` as `bhaskarbarot` (or add `wp113department-cell` as a collaborator),
      then `git push -u origin main`.

## 1. Coverage (most important for real agent use)
- [ ] Seed list: a curated file of good starting sites, sitemaps and RSS feeds (news, docs, Wikipedia,
      gov, Indian sources), plus a `seed-file` command.
- [ ] Bulk import from Common Crawl: test `cc-import` against the real index and import a few hundred
      thousand pages for the domains we care about.
- [ ] Run the `worker` continuously (systemd service) so the index keeps growing and stays fresh.
- [ ] Wikipedia dump import (free XML dump), so encyclopedic queries are covered.

## 2. Speed and scale
- [ ] Parallel indexing and bulk import using multiprocessing (currently about 450–600 docs/s on one core).
- [ ] Sharding across machines: index shards plus a gateway that searches all shards and merges results,
      with global term statistics.
- [ ] Segment replication to other machines (copy immutable segment files).
- [ ] Load test at 1M+ documents and set latency targets.

## 3. Ranking quality
- [ ] Build a judged query set (50–100 real agent queries) and measure NDCG@10 and Recall@100.
- [ ] Train ranker weights with `train-ranker`; collect agent feedback via `/feedback`.
- [ ] Spelling correction ("did you mean"), synonyms and query expansion.
- [ ] Semantic retrieval written from scratch (e.g. term-embedding or LSA-style vectors), as a reranking signal.
- [ ] Stronger spam and low-quality site detection; host trust scores.

## 4. Freshness
- [ ] Faster feed polling for news sources; measure time from publishing to being indexed.
- [ ] Better publication-date extraction for pages without metadata.

## 5. Content
- [ ] JavaScript-rendered pages (currently we only see server HTML).
- [ ] PDF: Type0 fonts without ToUnicode (embedded font cmap parsing), JBIG2 scanned images.
- [ ] Hindi/Indic stemming and language detection.

## 6. Operations
- [ ] systemd units for `cluster` and `worker`, log rotation, backups of `data/`.
- [ ] Agent integration guide plus a sample tool definition for the 7 agents.
- [ ] HTTPS / reverse proxy if the API is exposed outside localhost.
