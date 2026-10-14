"""Entity linking and facts from free knowledge bases (Wikidata + Wikipedia). No rules about specific topics.

link():   query words -> Wikidata entities. Candidates come from (a) Wikidata label/alias lookup of word spans and
          (b) Wikipedia full-text lookup of the whole query (context). A candidate is accepted when its name or
          alias matches a span and it is supported by context (other query words in its description/aliases)
          or by agreement between the two lookups. Aliases ("Samrat Ashok" -> Ashoka, "OOP") come from the data.
answer(): one-fact questions. The query's remaining words are matched against the *labels and aliases of the
          entity's own Wikidata properties* (P19 is called "place of birth", alias "born in", "birthplace"...),
          so no question patterns are written in code.
Entities also expose their URL-valued properties (official website, documentation, repository) from the data.
"""
import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode

from .fetcher import FetchError, Fetcher
from .textproc import STOPWORDS, stem, tokenize

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/wiki/"

_lock = threading.Lock()
_net_lock = threading.Lock()                # Wikimedia asks API clients to send requests one at a time
_state = {"last": 0.0, "blocked_until": 0.0}
MIN_INTERVAL = 0.25
CACHE_TTL = 7 * 86400


class _DiskCache:
    """JSON responses cached in SQLite so repeated lookups never hit the network."""

    def __init__(self, path):
        from .db import Database
        self.db = Database(path, """CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, ts REAL, value TEXT);
            CREATE TABLE IF NOT EXISTS records(qid TEXT, full INTEGER, ts REAL, value TEXT, PRIMARY KEY(qid,full));""")
        if not self.db.one("SELECT 1 FROM records LIMIT 1"):
            with self.db.tx() as c:
                c.execute("""INSERT OR REPLACE INTO records SELECT e.key,
                    json_type(e.value,'$.claims') IS NOT NULL, k.ts, e.value
                    FROM kv k, json_each(k.value,'$.entities') e
                    WHERE e.type='object' AND json_type(e.value,'$.labels')='object'
                    ORDER BY k.ts""")

    def get(self, key):
        row = self.db.one("SELECT ts, value FROM kv WHERE key=?", (key,))
        if row and time.time() - row[0] < CACHE_TTL:
            return json.loads(row[1])
        return None

    def put(self, key, value):
        with self.db.tx() as c:
            now = time.time()
            c.execute("INSERT OR REPLACE INTO kv(key, ts, value) VALUES(?,?,?)",
                      (key, now, json.dumps(value)))
            for qid, record in value.get('entities', {}).items() if isinstance(value, dict) else []:
                if isinstance(record, dict) and record.get('labels'):
                    c.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?)",
                              (qid, int('claims' in record), now, json.dumps(record)))


_caches = {}


def _disk(settings):
    key = str(settings.data_dir)
    with _lock:
        if key not in _caches:
            _caches[key] = _DiskCache(Path(settings.data_dir) / "knowledge_cache.db")
        return _caches[key]


def _get_json(fetcher, url, max_bytes=20_000_000, cache=None, deadline=None):
    if cache is not None:
        hit = cache.get(url)
        if hit is not None:
            return hit
    remaining = None if deadline is None else max(0, deadline - time.monotonic())
    acquired = _net_lock.acquire() if remaining is None else _net_lock.acquire(timeout=remaining)
    if not acquired:
        return None
    try:
        now = time.time()
        if now < _state["blocked_until"]:
            return None                           # rate limited: degrade gracefully instead of hammering
        wait = MIN_INTERVAL - (now - _state["last"])
        if wait > 0:
            if deadline is not None and time.monotonic() + wait >= deadline:
                return None
            time.sleep(wait)
        try:
            res = fetcher.fetch(url, accept="application/json", max_bytes=max_bytes, retries=0, deadline=deadline)
        except FetchError:
            return None
        finally:
            _state["last"] = time.time()
        if res.status == 429:
            try:
                _state["blocked_until"] = time.time() + float(res.headers.get("x-retry-after") or res.headers.get("retry-after") or 30)
            except ValueError:
                _state["blocked_until"] = time.time() + 30
            return None
    finally:
        _net_lock.release()
    if res.status != 200:
        return None
    try:
        data = json.loads(res.body.decode("utf-8", "replace"))
    except ValueError:
        return None
    if cache is not None:
        cache.put(url, data)
    return data


def _stems(text):
    return {stem(t) for t in tokenize(text) if t not in STOPWORDS}


def _one_edit(a, b):
    """Conservative spelling grammar; candidate text must come from the source."""
    if a == b or min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    shorter, longer = sorted((a, b), key=len)
    i = next((i for i, (x, y) in enumerate(zip(shorter, longer)) if x != y), len(shorter))
    return shorter[i:] == longer[i + 1:]


@dataclass
class Entity:
    qid: str
    label: str
    description: str = ""
    aliases: list = field(default_factory=list)
    span: str = ""
    score: float = 0.0
    wiki_title: str = None
    urls: list = field(default_factory=list)       # values of URL-typed properties (official site, docs, repo)
    claims: dict = field(default_factory=dict)

    @property
    def wiki_url(self):
        return WIKIPEDIA + quote(self.wiki_title.replace(" ", "_")) if self.wiki_title else None

    @property
    def names(self):
        """Label + aliases, longest first (used to recognise the entity in documents)."""
        seen, out = set(), []
        names = [self.label] + list(self.aliases)
        if self.span and _stems(self.span) and any(_stems(self.span) <= _stems(n) for n in names):
            names.append(self.span)
        for n in names:
            k = n.lower().strip()
            if k and k not in seen and len(k) > 1:
                seen.add(k)
                out.append(n)
        return out

    def to_dict(self):
        return {"id": self.qid, "label": self.label, "description": self.description, "aliases": self.aliases[:8],
                "span": self.span, "score": round(self.score, 3), "wikipedia": self.wiki_url, "urls": self.urls[:8]}


class Knowledge:
    def __init__(self, settings, deadline=None):
        self.settings = settings
        self.deadline = deadline
        self.fetcher = Fetcher(settings)
        self._props_path = Path(settings.data_dir) / "wikidata_properties.json"
        self._props = None
        self.cache = _disk(settings)
        self.cached_only = False
        self.spelling_corrections = {}
        self.search_records = {}

    def _json(self, url, max_bytes=20_000_000):
        if self.cached_only or (self.deadline is not None and time.monotonic() >= self.deadline):
            return self.cache.get(url)
        return _get_json(self.fetcher, url, max_bytes, self.cache, self.deadline)

    # ------------------------------------------------------------ lookups
    def _local_search(self, text, limit=20):
        local = []
        for row in self.cache.db.query("SELECT qid,value FROM records WHERE ts>?", (time.time() - CACHE_TTL,)):
            if not row['qid'].startswith('Q') or not row['qid'][1:].isdigit():
                continue
            record = json.loads(row['value'])
            label = (record.get('labels', {}).get('en') or {}).get('value', '')
            names = [(label, 'label')] + [(a['value'], 'alias') for a in record.get('aliases', {}).get('en', [])]
            for name, kind in names:
                if name.lower() == text.lower():
                    local.append({'id': row['qid'], 'match': {'text': name, 'type': kind}})
                    break
        return list({r['id']: r for r in local}.values())[:limit]

    def _wd_search(self, text, limit=20):
        local = self._local_search(text, limit)
        if local:
            return local
        url = WIKIDATA_API + "?" + urlencode({"action": "wbsearchentities", "format": "json", "language": "en",
                                              "uselang": "en", "type": "item", "limit": limit, "search": text})
        return (self._json(url) or {}).get("search", [])

    def _wp_search(self, text, limit=5):
        """Wikipedia full-text lookup + Wikidata ids in one request (generator=search)."""
        url = WIKIPEDIA_API + "?" + urlencode({"action": "query", "format": "json", "generator": "search",
                                               "gsrsearch": text, "gsrlimit": limit, "prop": "pageprops|pageterms",
                                               "wbptterms": "label|description|alias",
                                               "ppprop": "wikibase_item", "list": "search", "srsearch": text,
                                               "srlimit": 1, "srinfo": "suggestion|rewrittenquery"})
        query = (self._json(url) or {}).get("query") or {}
        info = query.get("searchinfo") or {}
        # The generator omits searchinfo; the accompanying one-result list
        # supplies the search engine's correction without another HTTP request.
        original = tokenize(text)
        suggested = tokenize(info.get("suggestion") or info.get("rewrittenquery") or "")
        if len(original) == len(suggested):
            changes = [(a, b) for a, b in zip(original, suggested) if a != b]
            if changes and all(_one_edit(a, b) for a, b in changes):
                self.spelling_corrections.update(changes)
        pages = query.get("pages") or {}
        ranked = sorted(pages.values(), key=lambda p: p.get("index", 99))
        for page in ranked:
            qid = (page.get("pageprops") or {}).get("wikibase_item")
            terms = page.get("terms") or {}
            if not qid or not terms.get("label"):
                continue
            self.search_records[qid] = {
                "labels": {"en": {"value": terms["label"][0]}},
                "descriptions": {"en": {"value": (terms.get("description") or [""])[0]}},
                "aliases": {"en": [{"value": alias} for alias in terms.get("alias", [])]},
                "sitelinks": {"enwiki": {"title": page["title"]}}}
        if self.search_records:
            self.cache.put("search-records:" + url, {"entities": self.search_records})
        return [(p["title"], (p.get("pageprops") or {}).get("wikibase_item")) for p in ranked
                if (p.get("pageprops") or {}).get("wikibase_item")]

    def _wp_titles(self, titles):
        url = WIKIPEDIA_API + '?' + urlencode({'action':'query','format':'json','redirects':1,
            'titles':'|'.join(titles[:3]),'prop':'pageprops','ppprop':'wikibase_item'})
        pages = ((self._json(url) or {}).get('query') or {}).get('pages') or {}
        return [(p['title'],p['pageprops']['wikibase_item']) for p in pages.values()
                if p.get('pageprops', {}).get('wikibase_item')]

    def entities(self, qids, claims=False):
        """Wikidata records. Without claims the records are small (names, descriptions, sitelinks)."""
        qids = [q for q in dict.fromkeys(qids) if q]
        out = {}
        # Reuse records independently of the order/batch in which they were
        # fetched. URL-only caching previously missed the same entity whenever
        # another query changed the batch of candidate ids.
        for qid in qids:
            rows = self.cache.db.query("SELECT value AS record FROM records WHERE qid=? AND ts>? AND full>=? ORDER BY full DESC,ts DESC LIMIT 1",
                                       (qid, time.time() - CACHE_TTL, int(claims)))
            for row in rows:
                record = json.loads(row['record'])
                if record.get('labels') and (not claims or 'claims' in record):
                    out[qid] = record
                    break
        qids = [qid for qid in qids if qid not in out]
        if claims:
            for qid in list(qids):
                # EntityData is a small, cacheable public record endpoint and
                # remains useful when the query API is unavailable.
                data = self._json("https://www.wikidata.org/wiki/Special:EntityData/" + quote(qid) + ".json") or {}
                record = data.get('entities', {}).get(qid)
                if record and 'claims' in record:
                    out[qid] = record
            qids = [qid for qid in qids if qid not in out]
        props = "labels|descriptions|aliases|sitelinks" + ("|claims" if claims else "")
        step = 4 if claims else 40                 # full records can be several MB each
        for i in range(0, len(qids), step):
            chunk = qids[i:i + step]
            url = WIKIDATA_API + "?" + urlencode({"action": "wbgetentities", "format": "json", "languages": "en",
                                                  "props": props, "sitefilter": "enwiki", "ids": "|".join(chunk)})
            data = self._json(url, 60_000_000) or {}
            out.update((data.get("entities") or {}))
        return out

    # ------------------------------------------------------------ properties (labels/aliases are data)
    def _properties(self, pids):
        if self._props is None:
            try:
                self._props = json.loads(self._props_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._props = {}
        missing = [p for p in pids if p not in self._props]
        for i in range(0, len(missing), 45):
            chunk = missing[i:i + 45]
            url = WIKIDATA_API + "?" + urlencode({"action": "wbgetentities", "format": "json", "languages": "en",
                                                  "props": "labels|aliases|datatype", "ids": "|".join(chunk)})
            data = self._json(url) or {}
            for pid, e in (data.get("entities") or {}).items():
                self._props[pid] = {
                    "label": ((e.get("labels") or {}).get("en") or {}).get("value", ""),
                    "aliases": [a["value"] for a in (e.get("aliases") or {}).get("en", [])],
                    "datatype": e.get("datatype", "")}
        if missing:
            try:
                self._props_path.write_text(json.dumps(self._props), encoding="utf-8")
            except OSError:
                pass
        return {p: self._props.get(p, {}) for p in pids}

    # ------------------------------------------------------------ entity linking
    def link(self, words, context_words=(), max_entities=3, load_claims=True, load_urls=True, candidate_titles=(), candidate_ids=()):
        """words: subject words of the query (original case, in order); context_words: all other content words."""
        words = [w for w in words if w and w.lower() not in STOPWORDS]
        if not words:
            return []
        spans = []
        for n in (3, 2, 1):
            for i in range(0, len(words) - n + 1):
                spans.append(" ".join(words[i:i + n]))
        spans = list(dict.fromkeys(spans))[:12]
        variants = {}
        for s in spans:
            variants[s] = [s]
            if " " not in s:
                st = stem(s.lower())
                if st != s.lower() and len(st) > 1:      # plural / inflected form ("oops" -> "oop")
                    variants[s].append(st)
        wd, covered = [], set()
        known_spans = any(self._local_search(span) for span in spans)
        # Full-query context first: do not spend the entire network budget on
        # unlikely word spans before obtaining any usable entity records.
        self.cached_only = known_spans
        try:
            wp = list(candidate_ids) if candidate_ids else self._wp_titles(list(candidate_titles)) if candidate_titles else self._wp_search(" ".join(words + list(context_words)))
        finally:
            self.cached_only = False
        context_qids = {qid for _, qid in wp}
        # Search pageterms already contain source-provided labels, aliases and
        # descriptions. Missing a second API call must not cause a cached,
        # unrelated candidate to displace the source's primary subject.
        context_records = {qid: self.search_records[qid] for qid in context_qids if qid in self.search_records}
        missing_context = [qid for _, qid in wp if qid not in context_records]
        if missing_context:
            context_records.update(self.entities(missing_context, claims=bool(candidate_ids)))
        for span in spans:
            corrected = " ".join(self.spelling_corrections.get(w.lower(), w) for w in span.split())
            if corrected != span:
                variants[span].append(corrected)
        for span, vs in variants.items():
            # Cached spans remain usable after the network budget expires.
            toks = set(span.lower().split())
            if toks <= covered:
                continue                               # a longer span already matched these words exactly
            for v in vs:
                self.cached_only = bool(context_records) or known_spans
                try:
                    res = self._wd_search(v)
                finally:
                    self.cached_only = False
                wd.append((span, res))
                if any((r.get("match") or {}).get("text", "").lower() in (span.lower(), v.lower()) for r in res):
                    covered |= toks
        # Inflection variants must still be checked when a surface form is itself
        # an ambiguous name. Context, rather than the first label hit, decides.
        if context_words and not context_records:
            wp += self._wp_search(" ".join(words))
        # A stem is not generally a valid search word. Try inflection variants
        # for plural surface forms while preserving the other subject words.
        alternate = [stem(w.lower()) if w.lower().endswith("s") else w for w in words]
        if alternate != words:
            wp += self._wp_search(" ".join(alternate))
        wp = list(dict.fromkeys(wp))
        wp_rank = {qid: i for i, (_title, qid) in enumerate(wp)}
        cand_spans = {}
        for span, results in wd:
            for r in results:
                matched = (r.get("match") or {}).get("text", "")
                kind = (r.get("match") or {}).get("type", "")
                exact = matched.lower() in (span.lower(), stem(span.lower()))
                corrected_span = " ".join(self.spelling_corrections.get(w.lower(), w.lower()) for w in span.split())
                corrected = corrected_span != span.lower() and matched.lower() == corrected_span
                q = r["id"]
                quality = (1.0 if kind == "label" else 0.85) if exact else (0.9 if corrected else 0.25)
                prev = cand_spans.get(q)
                if not prev or quality * len(span) > prev[1] * len(prev[0]):
                    cand_spans[q] = (span, quality)
        for _title, qid in wp:
            cand_spans.setdefault(qid, ("", 0.0))
        ents = dict(context_records)
        remaining = [qid for qid in cand_spans if qid not in ents]
        if remaining:
            ents.update(self.entities(remaining))
        corrected_stem = lambda w: stem(self.spelling_corrections.get(w.lower(), w.lower()))
        subj = {corrected_stem(w) for w in words}
        all_ctx = subj | {stem(w.lower()) for w in context_words if w.lower() not in STOPWORDS}
        # Context search can name a related organization rather than the queried
        # product. Use those data-provided names as additional disambiguation
        # evidence when they occur in a candidate's own description or aliases.
        context_names = []
        for qid in context_qids:
            record = ents.get(qid) or {}
            names = [((record.get("labels") or {}).get("en") or {}).get("value", "")]
            names += [a["value"] for a in (record.get("aliases") or {}).get("en", [])]
            context_names.extend(_stems(n) for n in names if _stems(n))
        scored = []
        for qid, (span, quality) in cand_spans.items():
            e = ents.get(qid)
            if not e or "missing" in e:
                continue
            label = ((e.get("labels") or {}).get("en") or {}).get("value", "")
            if not label or label.split(":", 1)[0] in ("Category", "Template", "Wikipedia", "Portal", "Help"):
                continue
            desc = ((e.get("descriptions") or {}).get("en") or {}).get("value", "")
            aliases = [a["value"] for a in (e.get("aliases") or {}).get("en", [])]
            agree = qid in wp_rank
            if not span:
                # found only by the full-text lookup: its own name must be made of query words
                matched_name = max([label] + aliases, key=lambda n: len(_stems(n) & subj) / max(1, len(_stems(n))))
                label_stems = _stems(matched_name)
                hit = label_stems & subj
                if not hit:
                    continue
                span = " ".join(w for w in words if corrected_stem(w) in hit)
                quality = (0.9 if matched_name == label else 0.85) * len(hit) / len(label_stems)
                if context_words and qid in context_qids:
                    quality = (0.9 if matched_name == label else 0.85) * (0.5 + 0.5 * len(hit) / len(label_stems))
            span_stems = {corrected_stem(w) for w in tokenize(span) if w not in STOPWORDS}
            ctx = (all_ctx - span_stems) & _stems(desc + " " + " ".join(aliases) + " " + label)
            related = any(name <= _stems(desc + " " + " ".join(aliases))
                          for name in context_names if not name <= span_stems)
            specific = len(span.split()) >= 2 and quality >= 0.85    # exact multi-word name or alias
            if not (ctx or agree or specific or related):
                continue                                             # a lone word needs support from the query
            sitelinks = len(e.get("sitelinks") or {})
            agreement = 1.0 if qid in context_qids else 0.25 if agree else 0.0
            score = quality * (1 + 0.8 * (len(ctx) + int(related)) + agreement) + 0.25 * max(0, len(span.split()) - 1)
            score += 0.1 * math.log1p(sitelinks)
            ent = Entity(qid=qid, label=label, description=desc, aliases=aliases, span=span, score=score,
                         wiki_title=((e.get("sitelinks") or {}).get("enwiki") or {}).get("title"))
            scored.append(ent)
        scored.sort(key=lambda x: x.score, reverse=True)
        chosen, used = [], set()
        for ent in scored:
            toks = set(ent.span.lower().split()) if ent.span else set()
            if toks and toks & used:
                continue                       # one entity per query span (best first)
            if ent.score < 0.85:
                continue
            chosen.append(ent)
            used |= toks
            if len(chosen) >= max_entities:
                break
        full = self.entities([c.qid for c in chosen], claims=True) if load_claims else {}
        from .intent import get_model
        model = get_model(self.settings.data_dir)
        for ent in chosen:
            ent.claims = (full.get(ent.qid) or {}).get("claims") or {}
            urls = []
            url_pids = [pid for pid, claims in ent.claims.items()
                        if any((c.get("mainsnak") or {}).get("datatype") == "url" for c in claims)]
            metadata = self._properties(url_pids) if load_urls else {}
            ordered_pids = sorted(url_pids, key=lambda pid: max(
                (2 * model.classify(name)[1].get("company", 0) + model.classify(name)[1].get("tech_docs", 0)
                 for name in [metadata.get(pid, {}).get("label", "")] + metadata.get(pid, {}).get("aliases", [])),
                default=0), reverse=True)
            for pid in ordered_pids:
                names = [metadata.get(pid, {}).get('label', '')] + metadata.get(pid, {}).get('aliases', [])
                if max((max(model.classify(name)[1].get('company', 0), model.classify(name)[1].get('tech_docs', 0))
                        for name in names), default=0) < 0.45:
                    continue
                meta = metadata.get(pid, {})
                property_names = [meta.get("label", "")] + meta.get("aliases", [])
                affinity = max((model.classify(n)[1].get("company", 0) + model.classify(n)[1].get("tech_docs", 0)
                                for n in property_names), default=0)
                if load_urls and affinity < 0.45:
                    continue
                claims = ent.claims[pid]
                for c in claims[:3]:
                    snak = c.get("mainsnak") or {}
                    if snak.get("datatype") == "url" and (snak.get("datavalue") or {}).get("value"):
                        urls.append(snak["datavalue"]["value"])
            ent.urls = list(dict.fromkeys(urls))
        return chosen

    # ------------------------------------------------------------ facts
    def answer(self, entity, question_words):
        """Match question words to the entity's property names/aliases and return the best-matching fact(s)."""
        if not entity or not entity.claims:
            return None
        q = {stem(w.lower()) for w in question_words if w.lower() not in STOPWORDS} - _stems(" ".join(entity.names))
        if not q:
            return None
        props = self._properties(list(entity.claims))
        scored = []
        for pid, meta in props.items():
            if not meta or meta.get("datatype") in ("external-id", "commonsMedia", "geo-shape", "tabular-data"):
                continue
            names = [meta.get("label", "")] + meta.get("aliases", [])
            best = max((len(q & _stems(n)) / (len(_stems(n)) or 1) + len(q & _stems(n)) for n in names), default=0)
            if best >= 1.0:
                scored.append((best, pid, meta))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[0][0]
        facts = []
        for s, pid, meta in scored:
            if s < top - 1e-9 or len(facts) >= 2:
                break
            values = self._values(entity.claims.get(pid, []))
            if values:
                references = []
                for claim in entity.claims.get(pid, []):
                    if claim.get("rank") == "deprecated":
                        continue
                    for reference in claim.get("references", []):
                        for snaks in reference.get("snaks", {}).values():
                            for snak in snaks:
                                value = (snak.get("datavalue") or {}).get("value")
                                if snak.get("datatype") == "url" and isinstance(value, str):
                                    references.append(value)
                facts.append({"property": pid, "label": meta.get("label"), "values": values,
                              "references": list(dict.fromkeys(references))})
        if not facts:
            return None
        lines = []
        for f in facts:
            vals = []
            for v in f["values"][:4]:
                txt = v["text"]
                if v.get("aliases"):
                    txt += f" (also known as {', '.join(v['aliases'][:3])})"
                if v.get("description"):
                    txt += f" — {v['description']}"
                vals.append(txt)
            lines.append(f"{f['label'][:1].upper() + f['label'][1:]}: " + "; ".join(vals))
        return {"type": "fact", "entity": entity.label, "entity_description": entity.description,
                "text": "Wikidata reports (not independently verified):\n" + "\n".join(lines), "facts": facts,
                "verification": "unverified",
                "verification_note": "This claim has not been corroborated against an independent reliable source; it is not a confirmed answer.",
                "source": {"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{entity.qid}",
                           "page": entity.wiki_url}}

    def _values(self, claims):
        claims = sorted((c for c in claims if c.get("rank") != "deprecated"),
                        key=lambda c: 0 if c.get("rank") == "preferred" else 1)
        if any(c.get("rank") == "preferred" for c in claims):
            claims = [c for c in claims if c.get("rank") == "preferred"]
        out, item_ids = [], []
        for c in claims[:4]:
            dv = (c.get("mainsnak") or {}).get("datavalue") or {}
            v = dv.get("value")
            if isinstance(v, dict) and v.get("id"):
                item_ids.append(v["id"])
                out.append({"item": v["id"]})
            elif isinstance(v, dict) and "time" in v:
                out.append({"text": _format_time(v)})
            elif isinstance(v, dict) and "amount" in v:
                out.append({"text": f"{float(v['amount']):,.0f}"})
            elif isinstance(v, dict) and "text" in v:
                out.append({"text": v["text"]})
            elif isinstance(v, str):
                out.append({"text": v})
        if item_ids:
            ents = self.entities(item_ids)
            for o in out:
                if "item" in o:
                    e = ents.get(o["item"]) or {}
                    o["text"] = ((e.get("labels") or {}).get("en") or {}).get("value", o["item"])
                    o["description"] = ((e.get("descriptions") or {}).get("en") or {}).get("value")
                    o["aliases"] = [a["value"] for a in (e.get("aliases") or {}).get("en", [])][:3]
        return out

    def card(self, entity):
        """Short description card for 'what is X' style queries (from Wikidata + Wikipedia summary)."""
        if not entity:
            return None
        extract = None
        if entity.wiki_title:
            url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(entity.wiki_title.replace(" ", "_"),
                                                                               safe="")
            s = self._json(url) or {}
            extract = s.get("extract")
        text = entity.label + (f" — {entity.description}" if entity.description else "")
        if extract:
            text += "\n" + extract
        return {"type": "entity", "entity": entity.label, "text": text, "verified_summary": bool(extract), "urls": entity.urls[:4],
                "source": {"name": "Wikipedia / Wikidata", "url": entity.wiki_url or
                           f"https://www.wikidata.org/wiki/{entity.qid}"}}


def _format_time(value):
    t = value.get("time", "")
    precision = value.get("precision", 11)
    sign = "-" if t.startswith("-") else ""
    parts = t.lstrip("+-").split("T")[0].split("-")
    if len(parts) != 3:
        return t
    try:
        y, mo, d = (int(x) for x in parts)
    except ValueError:
        return t
    era = " BCE" if sign else ""
    if precision >= 11 and mo and d:
        from datetime import date
        try:
            return date(y, mo, d).strftime("%-d %B %Y") + era
        except ValueError:
            pass
    if precision == 10 and mo:
        from datetime import date
        return date(2000, mo, 1).strftime("%B ") + str(y) + era
    return ("c. " if precision < 9 else "") + str(y) + era
