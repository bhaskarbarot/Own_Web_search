"""Retrieval and ranking.

Stage 1  candidate retrieval per segment: conjunctive (AND) over required terms, driven by the rarest term;
         very common terms use champion (top-k) lists so cost stays bounded; falls back to OR with a
         minimum-should-match when AND finds too little. Hidden meta terms implement site:/filetype:/lang:.
Stage 1b BM25F scoring over title / headings / url / anchor text / body with per-field length normalisation.
Stage 2  static and query-dependent features (pagerank, quality, freshness, title coverage, URL depth).
Stage 3  positional rerank: exact phrase, term proximity (minimal covering window), best passage score.
Stage 4  diversification (near-duplicate collapse, per-host cap) — done in the engine.

The final score is a linear model whose weights live in ``ranker.json`` and can be learned from
relevance judgments with ``ownsearch train-ranker`` (coordinate ascent on NDCG@10).
"""
import heapq
import json
import math
import time

from .indexer import META
from .segments import F_TITLE, F_URL, NF

FIELD_WEIGHTS = (3.0, 1.8, 1.4, 2.2, 1.0, 0.0)
FIELD_B = (0.40, 0.50, 0.30, 0.60, 0.75, 0.0)
K1 = 1.2
CAND_LIMIT = 30000          # max postings scanned for the lead term before switching to champion lists
PHRASE_CHECK_LIMIT = 20000

DEFAULT_WEIGHTS = {
    "bm25": 1.00,            # normalised BM25F (score / best score in the candidate set)
    "coverage": 0.45,        # fraction of query terms matched
    "title": 0.35,           # fraction of query terms in the title
    "url": 0.12,             # fraction of query terms in the URL
    "phrase": 0.30,          # whole query appears as a phrase
    "proximity": 0.30,       # 1 / (1 + extra words in the minimal window covering all terms)
    "passage": 0.25,         # best passage density
    "pagerank": 0.20,
    "quality": 0.18,
    "freshness": 0.05,       # multiplied up when the query wants fresh results
    "depth": 0.06,           # shallow URLs (home/section pages) for navigational queries
}
FEATURES = list(DEFAULT_WEIGHTS)


def load_weights(path):
    w = dict(DEFAULT_WEIGHTS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        w.update({k: float(v) for k, v in data.get("weights", {}).items() if k in w})
    except (OSError, ValueError):
        pass
    return w


def _has(p, local):
    return p.find(local) >= 0


class Candidate:
    __slots__ = ("score", "doc_id", "ri", "local", "matched", "features", "final", "passages", "mask")

    def __init__(self, score, doc_id, ri, local, matched):
        self.score, self.doc_id, self.ri, self.local, self.matched = score, doc_id, ri, local, matched
        self.features = {}
        self.final = 0.0
        self.passages = None
        self.mask = 0


def _phrase_ok(reader, local, plists, phrase):
    sets = []
    for t in phrase:
        p = plists.get(t)
        if p is None:
            return False
        i = p.find(local)
        if i < 0:
            return False
        sets.append(set(reader.positions(p, i)))
    first = sets[0]
    return any(all((pos + k) in sets[k] for k in range(1, len(sets))) for pos in first)


def retrieve(snap, q, want=400, deadline=None, need=10):
    """Returns (candidates sorted by score desc, info dict)."""
    req = list(dict.fromkeys(q.required + [t for p in q.phrases for t in p] + q.intitle + q.inurl))
    opt = [t for t in q.optional if t not in req]
    scoring = list(dict.fromkeys(req + opt))
    idf = {t: snap.idf(t) for t in scoring}
    missing = [t for t in req if snap.df(t) == 0]
    site_terms = [META + "site:" + s for s in q.sites]
    nosite_terms = [META + "site:" + s for s in q.not_sites]
    type_terms = [META + ("type:" if ft in ("web", "pdf", "text", "image", "docx", "xlsx", "pptx", "odt", "epub",
                                             "feed", "xml") else "ext:") + ft for ft in q.filetypes]
    lang_terms = [META + "lang:" + q.lang] if q.lang else []
    avg = snap.avg
    info = {"mode": "all_terms", "missing_terms": missing, "segments": len(snap.readers)}

    def run(mode, min_match):
        out = []
        for ri, r in enumerate(snap.readers):
            if r.live == 0:
                continue
            if deadline and time.monotonic() > deadline and out:
                info["timed_out"] = True
                break
            pl = {t: snap.postings(ri, t) for t in scoring}
            filt_site = [p for t in site_terms if (p := snap.postings(ri, t))]
            filt_type = [p for t in type_terms if (p := snap.postings(ri, t))]
            filt_lang = [p for t in lang_terms if (p := snap.postings(ri, t))]
            if (site_terms and not filt_site) or (type_terms and not filt_type) or (lang_terms and not filt_lang):
                continue
            neg = [p for t in q.excluded if (p := snap.postings(ri, t))]
            neg_site = [p for t in nosite_terms if (p := snap.postings(ri, t))]
            # ---- candidate generation
            if scoring:
                if mode == "and":
                    if any(pl[t] is None for t in req) or not req:
                        continue
                    order = sorted(req, key=lambda t: pl[t].n)
                    lead = pl[order[0]]
                    if lead.n <= CAND_LIMIT:
                        cand = lead.docs
                    else:
                        cs = set()
                        for t in order:
                            ch = snap.champions(ri, t)
                            cs.update(ch if ch is not None else pl[t].docs[:CAND_LIMIT])
                        cand = sorted(cs)
                        info["champions"] = True
                    for t in order[1:]:
                        p = pl[t]
                        if len(cand) * 16 < p.n:
                            cand = [d for d in cand if _has(p, d)]
                        else:
                            cand = sorted(set(cand).intersection(p.docs))
                        if not cand:
                            break
                else:
                    cs = set()
                    for t in scoring:
                        p = pl[t]
                        if p is None:
                            continue
                        if p.n <= CAND_LIMIT:
                            cs.update(p.docs)
                        else:
                            ch = snap.champions(ri, t)
                            cs.update(ch if ch is not None else p.docs[:CAND_LIMIT])
                    cand = sorted(cs)
            else:
                base = filt_site or filt_type or filt_lang
                if not base:
                    continue
                cs = set()
                for p in base:
                    cs.update(p.docs[:200000])
                cand = sorted(cs)
            # ---- filters
            if filt_site:
                cand = [d for d in cand if any(_has(p, d) for p in filt_site)]
            if filt_type:
                cand = [d for d in cand if any(_has(p, d) for p in filt_type)]
            if filt_lang:
                cand = [d for d in cand if any(_has(p, d) for p in filt_lang)]
            if neg:
                cand = [d for d in cand if not any(_has(p, d) for p in neg)]
            if neg_site:
                cand = [d for d in cand if not any(_has(p, d) for p in neg_site)]
            cand = [d for d in cand if not r.is_deleted(d)]
            if q.phrases or q.excluded_phrases:
                cand = cand[:PHRASE_CHECK_LIMIT]
                if q.phrases:
                    cand = [d for d in cand if all(_phrase_ok(r, d, pl, ph) for ph in q.phrases)]
                if q.excluded_phrases:
                    extra = {t: snap.postings(ri, t) for ph in q.excluded_phrases for t in ph}
                    cand = [d for d in cand if not any(_phrase_ok(r, d, extra, ph) for ph in q.excluded_phrases)]
            if q.intitle:
                cand = [d for d in cand if all((p := pl[t]) is not None and (i := p.find(d)) >= 0
                                               and p.tf(F_TITLE, i) > 0 for t in q.intitle)]
            if q.inurl:
                cand = [d for d in cand if all((p := pl[t]) is not None and (i := p.find(d)) >= 0
                                               and p.tf(F_URL, i) > 0 for t in q.inurl)]
            # ---- BM25F scoring
            L = r.lengths
            static = r.static
            infos = [(idf[t] * (1.0 if t in req else 0.5), pl[t], 1 << k) for k, t in enumerate(scoring)
                     if pl[t] is not None]
            for d in cand:
                base = d * NF
                s = 0.0
                matched = 0
                mask = 0
                for w_idf, p, bit in infos:
                    i = p.find(d)
                    if i < 0:
                        continue
                    matched += 1
                    mask |= bit
                    n = p.n
                    tfs = p.tfs
                    w = 0.0
                    for f in range(NF - 1):
                        tf = tfs[f * n + i]
                        if tf:
                            w += FIELD_WEIGHTS[f] * tf / (1.0 - FIELD_B[f] + FIELD_B[f] * L[base + f] / avg[f])
                    s += w_idf * w / (K1 + w)
                if scoring and matched < min_match:
                    continue
                if not scoring:
                    s = static[d] / 255.0
                c = Candidate(s, r.docids[d], ri, d, matched)
                c.mask = mask
                out.append(c)
        return out

    if req:
        cands = run("and", 0)
        info["and_matches"] = len(cands)
        if len(cands) < need and (len(req) > 1 or opt):
            n_terms = len(req) + len(opt)
            info["mode"] = "all_terms+partial" if cands else "partial_terms"
            seen = {c.doc_id for c in cands}
            min_match = max(1, math.ceil(0.5 * n_terms)) if n_terms > 2 else 1
            cands += [c for c in run("or", min_match) if c.doc_id not in seen]
    elif scoring:
        info["mode"] = "any_terms"
        cands = run("or", 1)
    else:
        info["mode"] = "filters_only"
        cands = run("filter", 0)
    # importance of each query term = IDF; a term never seen in the index gets the maximum IDF
    max_idf = math.log(1.0 + (snap.N + 0.5) / 0.5) if snap.N else 1.0
    term_w = [idf[t] if idf[t] > 0 else max_idf for t in scoring]
    total_w = sum(term_w) or 1.0
    req_bits = sum(1 << k for k, t in enumerate(scoring) if t in req)
    for c in cands:
        c.features["_wcov"] = sum(w for k, w in enumerate(term_w) if c.mask >> k & 1) / total_w
        c.features["_all"] = 1.0 if (c.mask & req_bits) == req_bits else 0.0
    if info["mode"] in ("partial_terms", "all_terms+partial"):
        # a partial match must contain the important (rare) words, not just the common ones
        key_bit = 1 << max(range(len(scoring)), key=lambda k: term_w[k]) if scoring else 0
        cands = [c for c in cands if c.features["_all"] or (c.features["_wcov"] >= 0.65 and c.mask & key_bit)]
    info["candidates"] = len(cands)
    top = heapq.nlargest(want, cands, key=lambda c: c.score)
    return top, info


def min_window(position_lists):
    """Smallest span (in tokens) containing at least one position from every list."""
    lists = [sorted(p) for p in position_lists if p]
    if len(lists) < 2:
        return 0 if lists else None
    heap = [(lst[0], k, 0) for k, lst in enumerate(lists)]
    heapq.heapify(heap)
    hi = max(lst[0] for lst in lists)
    best = hi - heap[0][0]
    while True:
        lo, k, idx = heapq.heappop(heap)
        best = min(best, hi - lo)
        if idx + 1 >= len(lists[k]):
            return best
        nxt = lists[k][idx + 1]
        hi = max(hi, nxt)
        heapq.heappush(heap, (nxt, k, idx + 1))


def positional_features(snap, cand, terms, full_phrase):
    """(proximity in [0,1], whole-query phrase match 0/1) from stored positions."""
    r = snap.readers[cand.ri]
    pos = {}
    for t in terms:
        p = snap.postings(cand.ri, t)
        if p is None:
            continue
        i = p.find(cand.local)
        if i >= 0:
            pos[t] = r.positions(p, i)[:2000]
    prox = 0.0
    if len(pos) >= 2:
        w = min_window(list(pos.values()))
        if w is not None:
            prox = 1.0 / (1.0 + max(0, w - (len(pos) - 1)) / 2.0)
    elif len(pos) == 1 and len(terms) == 1:
        prox = 1.0
    phrase = 0.0
    if len(full_phrase) >= 2 and all(t in pos for t in full_phrase):
        sets = [set(pos[t]) for t in full_phrase]
        if any(all((p0 + k) in sets[k] for k in range(1, len(sets))) for p0 in pos[full_phrase[0]]):
            phrase = 1.0
    return prox, phrase


def linear_score(features, weights):
    return sum(weights.get(k, 0.0) * v for k, v in features.items())
