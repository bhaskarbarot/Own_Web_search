"""Relevance evaluation (NDCG@10, Recall@100, MRR@10, P@10) and learning-to-rank by coordinate ascent.

Judgments file (JSON):
    {"queries": [{"query": "python web crawler",
                  "judgments": {"https://example.org/crawler": 3, "https://example.org/other": 1}}]}
or TSV lines:  query<TAB>url<TAB>grade      (grade 0 = not relevant ... 3 = perfect)
Feedback that agents send to POST /feedback can be exported to this format with `ownsearch qrels-from-feedback`.
"""
import json
import math
import random
import time
from collections import defaultdict

from .ranking import DEFAULT_WEIGHTS, FEATURES, linear_score
from .util import normalize_url


def load_qrels(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
        items = data["queries"] if isinstance(data, dict) else data
        return [{"query": it["query"], "judgments": {_key(k): int(v) for k, v in it["judgments"].items()},
                 "params": it.get("params", {})} for it in items]
    except (ValueError, KeyError, TypeError):
        pass
    grouped = defaultdict(dict)
    for line in raw.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3 and not line.startswith("#"):
            try:
                grouped[parts[0]][_key(parts[1])] = int(parts[2])
            except ValueError:
                continue
    return [{"query": q, "judgments": j, "params": {}} for q, j in grouped.items()]


def _key(k):
    k = str(k).strip()
    if k.startswith("doc:"):
        return k
    return normalize_url(k) or k


def _result_key(r):
    return normalize_url(r["url"]) or r["url"]


def dcg(gains):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg(ranked_keys, judgments, k=10):
    gains = [judgments.get(key, 0) for key in ranked_keys[:k]]
    ideal = dcg(sorted(judgments.values(), reverse=True)[:k])
    return dcg(gains) / ideal if ideal > 0 else 0.0


def recall(ranked_keys, judgments, k=100):
    rel = {key for key, g in judgments.items() if g > 0}
    return len(rel & set(ranked_keys[:k])) / len(rel) if rel else 0.0


def mrr(ranked_keys, judgments, k=10):
    for i, key in enumerate(ranked_keys[:k]):
        if judgments.get(key, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def precision(ranked_keys, judgments, k=10):
    return sum(1 for key in ranked_keys[:k] if judgments.get(key, 0) > 0) / k


def _keys_for(results):
    out = []
    for r in results:
        out.append((_result_key(r), f"doc:{r['id']}"))
    return out


def _match(keys, judgments):
    return [k1 if k1 in judgments else k2 for k1, k2 in keys]


def run_queries(engine, qrels, depth=100, explain=False):
    runs = []
    for item in qrels:
        results = []
        for off in range(0, depth, 50):
            res = engine.search(item["query"], limit=50, fetch_evidence=False, offset=off, explain=explain,
                                use_cache=False, **item.get("params", {}))
            results.extend(res["results"])
            if not res.get("has_more"):
                break
        runs.append(results[:depth])
    return runs


def evaluate(engine, qrels, depth=100):
    t0 = time.time()
    runs = run_queries(engine, qrels, depth)
    per = []
    for item, results in zip(qrels, runs):
        keys = _match(_keys_for(results), item["judgments"])
        per.append({"query": item["query"], "ndcg@10": round(ndcg(keys, item["judgments"]), 4),
                    "recall@100": round(recall(keys, item["judgments"]), 4),
                    "mrr@10": round(mrr(keys, item["judgments"]), 4), "p@10": round(precision(keys, item["judgments"]), 4),
                    "results": len(results)})
    n = max(1, len(per))
    summary = {m: round(sum(p[m] for p in per) / n, 4) for m in ("ndcg@10", "recall@100", "mrr@10", "p@10")}
    return {"queries": len(per), "summary": summary, "per_query": per, "seconds": round(time.time() - t0, 2)}


def train(engine, qrels, rounds=6, seed=7, log=None):
    """Coordinate ascent on the linear ranker weights, maximising mean NDCG@10 over the judged queries."""
    runs = run_queries(engine, qrels, depth=100, explain=True)
    data = []
    for item, results in zip(qrels, runs):
        keys = _match(_keys_for(results), item["judgments"])
        feats = [r.get("features", {}) for r in results]
        data.append((keys, feats, item["judgments"]))

    def objective(w):
        total = 0.0
        for keys, feats, judg in data:
            order = sorted(range(len(keys)), key=lambda i: linear_score(feats[i], w), reverse=True)
            total += ndcg([keys[i] for i in order], judg)
        return total / max(1, len(data))

    rng = random.Random(seed)
    w = dict(engine.weights)
    best = objective(w)
    start = best
    steps = (-0.6, -0.3, -0.1, 0.1, 0.3, 0.6)
    for rnd in range(rounds):
        improved = False
        order = list(FEATURES)
        rng.shuffle(order)
        for f in order:
            base = w[f]
            for s in steps:
                cand = dict(w)
                cand[f] = max(0.0, base + s * max(0.1, abs(base)))
                val = objective(cand)
                if val > best + 1e-6:
                    best, w, improved = val, cand, True
        if log:
            log(f"[train] round {rnd + 1}: ndcg@10={best:.4f}")
        if not improved:
            break
    return {"weights": {k: round(v, 4) for k, v in w.items()}, "ndcg@10_before": round(start, 4),
            "ndcg@10_after": round(best, 4), "queries": len(data), "defaults": DEFAULT_WEIGHTS}


def save_ranker(path, result):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"weights": result["weights"], "trained": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "ndcg@10_before": result["ndcg@10_before"], "ndcg@10_after": result["ndcg@10_after"],
                   "queries": result["queries"]}, f, indent=2)


def qrels_from_feedback(store):
    rows = store.db.query("SELECT query, url, doc_id, MAX(grade) FROM feedback WHERE query != '' GROUP BY query, url, doc_id")
    grouped = defaultdict(dict)
    for q, url, doc_id, grade in rows:
        key = _key(url) if url else f"doc:{doc_id}"
        grouped[q][key] = max(grouped[q].get(key, 0), int(grade))
    return {"queries": [{"query": q, "judgments": j} for q, j in grouped.items()]}
