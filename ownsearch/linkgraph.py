"""Link graph analysis: PageRank over documents (with host-level smoothing) and anchor-text refresh."""
import math
import time
from array import array

from .util import now_ts


def compute_pagerank(store, damping=0.85, iterations=30, tol=1e-7, log=None):
    """Power-iteration PageRank over active documents. Writes a normalised score in [0, 1] to documents.pagerank.

    Links between pages of the same host count half (sites cannot pump their own pages much), nofollow links
    are ignored, and the final score blends page rank with the rank of the page's host.
    """
    t0 = time.time()
    db = store.db
    rows = db.query("SELECT id, url, host FROM documents WHERE active=1 AND duplicate_of IS NULL")
    if not rows:
        return {"documents": 0}
    idx = {}
    ids = array("q")
    hosts = []
    url_to = {}
    for i, r in enumerate(rows):
        idx[r["id"]] = i
        ids.append(r["id"])
        hosts.append(r["host"] or "")
        url_to[r["url"]] = i
    n = len(ids)
    src_list, dst_list, wt_list = array("i"), array("i"), array("f")
    for r in db.conn().execute("SELECT src_id, dst_key, nofollow FROM links"):
        if r[2]:
            continue
        s = idx.get(r[0])
        d = url_to.get(r[1])
        if s is None or d is None or s == d:
            continue
        src_list.append(s)
        dst_list.append(d)
        wt_list.append(0.5 if hosts[s] == hosts[d] else 1.0)
    out_w = [0.0] * n
    for s, w in zip(src_list, wt_list):
        out_w[s] += w
    pr = [1.0 / n] * n
    it = 0
    for it in range(1, iterations + 1):
        dangling = sum(pr[i] for i in range(n) if out_w[i] == 0.0)
        base = (1.0 - damping) / n + damping * dangling / n
        new = [base] * n
        for s, d, w in zip(src_list, dst_list, wt_list):
            new[d] += damping * pr[s] * w / out_w[s]
        delta = sum(abs(a - b) for a, b in zip(new, pr))
        pr = new
        if delta < tol:
            break
    # host-level rank: sum of page ranks per host, used to smooth sparse page graphs
    host_rank = {}
    for i in range(n):
        host_rank[hosts[i]] = host_rank.get(hosts[i], 0.0) + pr[i]
    max_pr = max(pr) or 1.0
    max_host = max(host_rank.values()) or 1.0
    scores = []
    for i in range(n):
        page = math.log1p(pr[i] * n) / math.log1p(max_pr * n)
        site = math.log1p(host_rank[hosts[i]] * n) / math.log1p(max_host * n)
        scores.append((round(0.7 * page + 0.3 * site, 6), ids[i]))
    with db.tx() as c:
        c.executemany("UPDATE documents SET pagerank=? WHERE id=?", scores)
    stats = {"documents": n, "edges": len(src_list), "iterations": it, "seconds": round(time.time() - t0, 2)}
    if log:
        log(f"[pagerank] {stats}")
    return stats


def refresh_anchors(store):
    """Re-index documents that received new inbound anchor text since the last refresh."""
    last = float(store.get_meta("anchors_refreshed_at", 0) or 0)
    now = now_ts()
    rows = store.db.query(
        "SELECT DISTINCT d.id FROM links l JOIN documents d ON d.url = l.dst_key "
        "WHERE l.added_at > ? AND l.anchor != '' AND d.active = 1", (last,))
    ids = [r[0] for r in rows]
    store.bump(ids)
    store.set_meta("anchors_refreshed_at", now)
    return len(ids)


def refresh(store, indexer=None, log=None):
    """PageRank + anchor refresh + (optional) re-index. Static scores live in index segments, so re-index all
    documents whose rank changed noticeably only on explicit request; ranking also reads pagerank live."""
    stats = compute_pagerank(store, log=log)
    stats["anchor_docs_reindexed"] = refresh_anchors(store)
    if indexer is not None:
        stats["indexed_changes"] = indexer.run()
    return stats
