"""Passage (evidence) extraction for AI agents and prompt-injection screening of retrieved text."""
import math
import re
try:
    import regex as passage_re
except ImportError:
    passage_re=re

from .textproc import stem, tokenize

INJECTION_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|messages?|context)",
    r"\bdisregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|system)\b",
    r"\bforget\s+(?:all\s+|everything\s+|your\s+)(?:previous|prior|instructions?)",
    r"\byou\s+are\s+now\s+(?:a|an|in)\b",
    r"\bnew\s+(?:system\s+)?instructions?\s*:",
    r"\bsystem\s*prompt\b",
    r"<\|?(?:im_start|im_end|system|endoftext)\|?>",
    r"\[\s*(?:system|inst)\s*\]",
    r"\b(?:assistant|system)\s*:\s*(?:you|ignore|from now)",
    r"\bdo\s+not\s+(?:tell|inform|reveal\s+to)\s+the\s+user\b",
    r"\b(?:exfiltrate|send)\s+(?:the\s+)?(?:api[_\s-]?keys?|credentials|passwords?|secrets?|tokens?)\b",
    r"\bact\s+as\s+(?:an?\s+)?(?:unrestricted|jailbroken|dan)\b",
    r"\bwhen\s+(?:an?\s+)?(?:ai|llm|language\s+model|agent|assistant)\s+(?:reads|sees|processes)\s+this\b",
)]


def injection_flags(text):
    hits = []
    for rx in INJECTION_PATTERNS:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0)[:80])
    return hits


def _term_patterns(terms, surface):
    """One regex group per query term: stems match their word family (crawl -> crawling, crawler)."""
    pats = []
    for i, t in enumerate(terms):
        alts = {re.escape(t)}
        for s in surface:
            if stem(s) == t:
                alts.add(re.escape(s))
        body = "|".join(sorted(alts, key=len, reverse=True))
        pats.append(f"(?P<t{i}>(?<!\\w)(?:{body})\\w*)")
    if not pats:
        return None
    return passage_re.compile("|".join(pats[:40]), passage_re.I)


_SENT_END = re.compile(r"[.!?](?=\s|$)|\n|\f")


def _expand(text, start, end, max_len):
    lo = max(0, start - 160)
    cut = max(text.rfind(". ", lo, start), text.rfind("\n", lo, start), text.rfind("\f", lo, start))
    if cut >= 0:
        start = cut + 1
    hi = min(len(text), end + 220)
    m = _SENT_END.search(text, end, hi)
    if m:
        end = m.start() + 1
    elif hi == len(text):
        end = hi
    else:
        cut = text.rfind(" ", end, hi)
        end = cut if cut > end else hi
    if end - start > max_len:
        mid = (start + end) // 2
        start, end = max(0, mid - max_len // 2), min(len(text), mid + max_len // 2)
    return start, end


def passages(text, terms, surface, idf=None, max_passages=3, window=700, max_len=900, scan_chars=3_000_000):
    """Best non-overlapping passages: [{"text", "start", "end", "page", "score", "matched_terms"}]."""
    if not text:
        return []
    terms = [t for t in dict.fromkeys(terms) if t]
    idf = idf or {}
    rx = _term_patterns(terms, surface)
    hits = []
    if rx:
        for m in rx.finditer(text, 0, min(len(text), scan_chars)):
            hits.append((m.start(), int(m.lastgroup[1:])))
            if len(hits) >= 20000:
                break
    out = []
    if not hits:
        start, end = _expand(text, 0, min(len(text), 400), max_len)
        return [{"text": text[start:end].strip(), "start": start, "end": end, "page": _page(text, start),
                 "score": 0.0, "matched_terms": 0}]
    weights = [max(0.1, idf.get(t, 1.0)) for t in terms]
    total_w = sum(weights) or 1.0
    used = []
    for _ in range(max_passages):
        best, best_span = -1.0, None
        j = 0
        counts = {}
        for i in range(len(hits)):          # sliding window over hit positions
            while hits[i][0] - hits[j][0] > window:
                k = hits[j][1]
                counts[k] -= 1
                if not counts[k]:
                    del counts[k]
                j += 1
            k = hits[i][1]
            counts[k] = counts.get(k, 0) + 1
            a, b = hits[j][0], hits[i][0]
            if any(not (b < u0 or a > u1) for u0, u1 in used):
                continue
            distinct = sum(weights[x] for x in counts) / total_w
            density = math.log1p(sum(counts.values()))
            score = 2.0 * distinct + 0.25 * density
            if score > best:
                best, best_span = score, (a, b, len(counts))
        if best_span is None:
            break
        a, b, nmatched = best_span
        start, end = _expand(text, a, b + 40, max_len)
        if any(not (end <= u0 or start >= u1) for u0, u1 in used):
            used.append((a, b))
            continue
        used.append((start, end))
        out.append({"text": text[start:end].replace("\f", " ").strip(), "start": start, "end": end,
                    "page": _page(text, start), "score": round(best, 4), "matched_terms": nmatched})
        if best < 1.0 and out:
            break
    return out


def _page(text, offset):
    return text.count("\f", 0, offset) + 1 if "\f" in text else None


def snippet_from(passage_text, surface, max_len=320):
    t = " ".join(passage_text.split())
    if len(t) <= max_len:
        return t
    low = t.lower()
    pos = [low.find(w.lower()) for w in surface if w and low.find(w.lower()) >= 0]
    start = max(0, min(pos) - max_len // 4) if pos else 0
    start = t.rfind(" ", 0, start) + 1 if start else 0
    end = min(len(t), start + max_len)
    cut = t.rfind(" ", start, end)
    end = cut if cut > start + max_len * 0.6 else end
    return ("…" if start else "") + t[start:end] + ("…" if end < len(t) else "")


def surface_words(raw):
    return [w for w in tokenize(raw) if len(w) > 1]
