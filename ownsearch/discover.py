"""Discover pages from linked entities, focused official-site walks and configured feeds.

All page requests use the safe fetcher, robots policies, one shared deadline and a
request cap. No company domains, guessed encyclopedia titles or topic rules live here.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlencode, urlparse

from .dates import parse_date
from .extract import extract
from .extract.feeds import parse_feed
from .live import PageClient
from .intent import get_model
from .query import parse_query
from .textproc import analyze, tokenize
from .util import iso_to_ts, normalize_url, utc_now


@dataclass
class CandidateItem:
    url: str
    provider: str
    title: str = ""
    snippet: str = ""
    published_at: Optional[str] = None
    source_url: Optional[str] = None
    sources: list = field(default_factory=list)


class BaseProvider:
    name = "base"

    def is_configured(self, settings):
        return True

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        raise NotImplementedError


def feed_urls(settings):
    urls = settings.news_feeds.replace(",", "\n").splitlines()
    if settings.news_feeds_file:
        try:
            urls += Path(settings.news_feeds_file).read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
    return list(dict.fromkeys(u.strip() for u in urls if u.strip() and not u.lstrip().startswith("#")))


def _client(settings, timeout, client):
    return client or PageClient(settings, time.monotonic() + timeout)


def _json(client, url):
    r = client.raw(url, accept="application/json", max_bytes=2_000_000)
    if r.status != 200:
        raise ValueError(f"HTTP {r.status}")
    return json.loads(r.body.decode("utf-8", "replace"))


class SearXNGProvider(BaseProvider):
    name = "searxng"

    def is_configured(self, settings):
        return bool(settings.searxng_url.strip())

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        if not self.is_configured(settings):
            return [], []
        params = {"q": query, "format": "json", "categories": "news" if pq.intent == "news" else settings.searxng_categories}
        # These parameters are supported by the self-hosted SearXNG API. A week
        # uses a wider upstream window; OwnSearch still enforces its exact dates.
        if pq.lang:
            params["language"] = pq.lang
        if pq.freshness in ("day", "month", "year", "week"):
            params["time_range"] = "month" if pq.freshness == "week" else pq.freshness
        url = settings.searxng_url.rstrip("/") + "/search?" + urlencode(params)
        try:
            client = _client(settings, min(timeout, settings.searxng_timeout), client)
            data = _json(client, url)
            errors = [f"SearXNG upstream {e[0]}: {e[1]}" for e in data.get("unresponsive_engines", [])
                      if isinstance(e, (list, tuple)) and len(e) >= 2]
            return [CandidateItem(i["url"], self.name, i.get("title", ""), i.get("content", ""),
                                  parse_date(i.get("publishedDate")))
                    for i in data.get("results", [])[:settings.discovery_max_urls] if i.get("url")], errors
        except (OSError, ValueError) as e:
            return [], [f"SearXNG request failed: {e}"]
        except Exception as e:
            return [], [f"SearXNG request failed: {e}"]


class NewsFeedProvider(BaseProvider):
    name = "news_feeds"

    def is_configured(self, settings):
        return bool(feed_urls(settings))

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        if pq.intent != "news" or not self.is_configured(settings):
            return [], []
        client = _client(settings, timeout, client)
        subjects = [set(analyze(n)) for e in pq.entities for n in e.names] or [set(pq.entity_terms)]
        subjects = [s for s in subjects if s]
        if not subjects:
            return [], []
        candidates, errors = [], []
        now = time.time()
        for url in feed_urls(settings)[:8]:
            if time.monotonic() >= client.deadline:
                break
            try:
                r = client.fetch(url, max_bytes=2_000_000)
                if r.status != 200:
                    raise ValueError(f"HTTP {r.status}")
                parsed = parse_feed(r.body, base_url=url) or {}
                for entry in parsed.get("entries", [])[:200]:
                    text = set(analyze(entry.get("title", "") + " " + entry.get("summary", "")))
                    ts = iso_to_ts(entry.get("published_at"))
                    # A shared generic word must never admit an unrelated feed entry.
                    if not any(s <= text for s in subjects) or ts is None or ts > now + 300:
                        continue
                    if pq.after is not None and ts < pq.after or pq.before is not None and ts > pq.before:
                        continue
                    if entry.get("url"):
                        candidates.append(CandidateItem(entry["url"], self.name, entry.get("title", ""),
                                                        entry.get("summary", ""), entry.get("published_at"), url))
            except Exception as e:
                errors.append(f"NewsFeed ({url}) failed: {e}")
        candidates.sort(key=lambda c: iso_to_ts(c.published_at) or 0, reverse=True)
        return candidates, errors


class WikipediaProvider(BaseProvider):
    name = "wikipedia"

    def is_configured(self, settings):
        return settings.knowledge_enabled

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        if pq.intent in ("news", "financial", "company"):
            return [], []
        return [CandidateItem(e.wiki_url, self.name, e.label) for e in pq.entities if e.wiki_url], []


def _explicit_urls(query, pq):
    urls = ["https://" + host + "/" for host in pq.sites]
    for word in query.split():
        value = word.strip('"\'(),')
        parsed = urlparse(value if "://" in value else "https://" + value)
        if parsed.hostname and "." in parsed.hostname and parsed.scheme in ("http", "https"):
            urls.append(parsed.geturl())
    return urls


def _http_url(url):
    normalized = normalize_url(url)
    return normalized if normalized and urlparse(normalized).scheme in ("http", "https") else None


class OfficialSiteProvider(BaseProvider):
    name = "official"

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        if pq.intent in ("news", "financial"):
            return [], []
        roots = _explicit_urls(query, pq)
        roots.extend(pq.reference_roots)
        # Round-robin preserves sources for each linked entity, rather than
        # letting one entity's many URL claims exhaust the entire crawl budget.
        for i in range(max((len(e.urls) for e in pq.entities), default=0)):
            roots.extend(e.urls[i] for e in pq.entities if i < len(e.urls))
        # A reference page can publish the official/docs link even when its
        # Wikidata URL record is unavailable. Read that link rather than guess
        # a host from the query name.
        roots.extend(e.wiki_url for e in pq.entities if not e.urls and e.wiki_url)
        roots = list(dict.fromkeys(_http_url(u) for u in roots if _http_url(u)))
        if pq.intent == "tech_docs":
            # A narrowly scoped entity source should get a turn before a
            # related product's many general/legal URL properties consume time.
            roots.sort(key=lambda u: min((len(e.urls) for e in pq.entities
                                         if any(_http_url(v) == u for v in e.urls)), default=100))
        roots = roots[:4]
        client = _client(settings, timeout, client)
        linked_terms = {t for e in pq.entities for t in analyze(e.span)}
        terms = set(pq.entity_terms + pq.required + pq.intitle + pq.inurl)
        candidates, errors = {}, []
        model = get_model(settings.data_dir)

        def offer(url, anchor=""):
            normalized = _http_url(url)
            if normalized:
                score = len(terms & set(analyze(unquote(normalized) + " " + anchor)))
                words = " " + " ".join(tokenize(unquote(normalized) + " " + anchor)) + " "
                host = "".join(tokenize(urlparse(normalized).hostname or ""))
                score += sum(any(" " + " ".join(tokenize(name)) + " " in words or
                                 (len("".join(tokenize(name))) >= 3 and "".join(tokenize(name)) in host)
                                 for name in e.names) for e in pq.entities)
                # Anchor phrasing supplies a generic intent signal. This ranks
                # guides above incidental references without inspecting host names.
                if anchor:
                    affinity = model.classify(anchor)[1].get(pq.intent, 0)
                    score += affinity if score or affinity >= 0.45 else 0
                previous = candidates.get(normalized)
                if previous is None or score > previous[0]:
                    candidates[normalized] = (score, CandidateItem(normalized, self.name, anchor))

        for root in roots:
            offer(root)
        for root in roots:
            if time.monotonic() >= client.deadline:
                break
            offer(root)
            try:
                r = client.fetch(root, max_bytes=2_000_000)
                if r.status != 200:
                    raise ValueError(f"HTTP {r.status}")
                ext = extract(r.body, r.final_url, r.content_type, settings)
                offer(root, ext.title)
                host = urlparse(r.final_url).hostname
                # Only follow links on the verified site. An unrelated outbound link is not official.
                for url, anchor, nofollow in ext.links[:settings.discovery_sitemap_limit]:
                    if not nofollow and urlparse(url).hostname == host:
                        offer(url, anchor)
                    elif not nofollow and pq.intent == "tech_docs" and model.classify(anchor)[1].get("tech_docs", 0) >= 0.45 and (any(
                            "".join(tokenize(name)) in "".join(tokenize(urlparse(url).hostname or ""))
                            for e in pq.entities for name in e.names if len("".join(tokenize(name))) >= 3) or
                            (not pq.entities and any(w.lower() in (urlparse(url).hostname or '').lower()
                                                    for w in pq.entity if len(w) >= 3))):
                        # A docs link published by a verified site can establish
                        # its external documentation host. Keep this walk bounded.
                        normalized = _http_url(url)
                        if normalized and normalized not in roots and len(roots) < 6:
                            roots.insert(roots.index(root) + 1, normalized)
                            offer(normalized, anchor)
                            if normalized not in [u for e in pq.entities for u in e.urls]:
                                for entity in pq.entities:
                                    if any("".join(tokenize(name)) in "".join(tokenize(urlparse(normalized).hostname or ""))
                                           for name in entity.names if len("".join(tokenize(name))) >= 3):
                                        entity.urls.append(normalized)
                origin = urlparse(r.final_url)._replace(path="", query="", fragment="").geturl()
                maps = [(u, 0) for u in client.policy(r.final_url).sitemaps[:3]] or [(origin + "/sitemap.xml", 0)]
                seen, examined = set(), 0
                while maps and len(seen) < 2 and examined < settings.discovery_sitemap_limit and time.monotonic() < client.deadline:
                    url, depth = maps.pop(0)
                    if url in seen or depth > 2 or urlparse(url).hostname != host:
                        continue
                    seen.add(url)
                    sr = client.fetch(url, max_bytes=2_000_000)
                    if sr.status != 200:
                        continue
                    sm = extract(sr.body, sr.final_url, sr.content_type, settings)
                    for loc, *_ in sm.sitemap_urls[:settings.discovery_sitemap_limit - examined]:
                        examined += 1
                        if urlparse(loc).hostname == host:
                            offer(loc)
                    maps.extend((u, depth + 1) for u, _ in sm.sitemaps[:3])
            except Exception as e:
                errors.append(f"Official site ({root}) failed: {e}")
        ordered = sorted(candidates.values(), key=lambda x: (-x[0], len(x[1].url), x[1].url))
        return [item for score, item in ordered if score or item.url in roots][:settings.discovery_max_urls], errors


class FinancialProvider(BaseProvider):
    name = "financial"

    def is_configured(self, settings):
        return bool(settings.financial_provider_url.strip())

    def discover(self, query, pq, settings, timeout=3.0, log=None, client=None):
        if not self.is_configured(settings) or pq.intent != "financial":
            return [], []
        try:
            client = _client(settings, min(timeout, settings.financial_timeout), client)
            data = _json(client, settings.financial_provider_url + "?" + urlencode({"q": query}))
            return ([CandidateItem(data["url"], self.name, data.get("title", ""), data.get("snippet", ""),
                                   parse_date(data.get("timestamp")))] if data.get("url") else []), []
        except Exception as e:
            return [], [f"Financial provider failed: {e}"]


def candidate_urls(query, max_urls=6, intent=None):
    pq = parse_query(query)
    if intent:
        pq.intent = intent
    items, _ = gather_candidates(None, query, pq, max_urls=max_urls)
    return [item.url for item in items]


def gather_candidates(engine, query, pq, max_urls=6, log=None, client=None):
    from .config import Settings
    settings = engine.settings if engine else Settings()
    client = _client(settings, settings.discovery_timeout, client)
    items, errors = [], []
    for provider in [SearXNGProvider(), NewsFeedProvider(), FinancialProvider(), OfficialSiteProvider(), WikipediaProvider()]:
        if not provider.is_configured(settings) or time.monotonic() >= client.deadline:
            continue
        global_deadline = client.deadline
        provider_timeout = getattr(settings, provider.name + "_timeout", settings.discovery_provider_timeout)
        client.deadline = min(global_deadline, time.monotonic() + provider_timeout)
        try:
            cands, errs = provider.discover(query, pq, settings, timeout=max(0.01, client.deadline - time.monotonic()),
                                           log=log, client=client)
        finally:
            client.deadline = global_deadline
        items.extend(cands)
        errors.extend(errs)
        if len(cands) >= settings.discovery_min_results and provider.name == "news_feeds":
            break
    unique = {}
    for item in items:
        url = normalize_url(item.url)
        if url and url.startswith(("http://", "https://")):
            item.url = url
            item.sources = [item.provider]
            if url not in unique:
                unique[url] = item
            else:
                prior = unique[url]
                prior.sources = list(dict.fromkeys(prior.sources + item.sources))
                if item.provider == "news_feeds" and item.published_at:
                    prior.published_at = item.published_at
                    prior.source_url = item.source_url
                    prior.provider = item.provider
                    prior.title = item.title or prior.title
                    prior.snippet = item.snippet or prior.snippet
                prior.title = prior.title or item.title
                prior.snippet = prior.snippet or item.snippet
    return list(unique.values())[:max_urls], errors


def discover(engine, query, frontier=None, max_urls=None, log=None, pq=None, deadline=None, details=None):
    from .frontier import Frontier
    from .pipeline import Processor
    t0 = time.monotonic()
    deadline = deadline or t0 + engine.settings.discovery_timeout
    pq = pq or parse_query(query, data_dir=engine.root)
    client = PageClient(engine.settings, deadline)
    # Reserve time to fetch/index the selected pages. Finding URLs alone must
    # not consume the entire query budget, leaving every candidate unfetched.
    client.deadline = t0 + max(0, deadline - t0) * 0.6
    items, errors = gather_candidates(engine, query, pq, max_urls=max_urls or engine.settings.discovery_max_urls,
                                      log=log, client=client)
    client.deadline = deadline
    frontier = frontier or Frontier(engine.settings)
    processor = Processor(engine.settings, engine.store)
    results = []
    # The publisher's feed is itself evidence for a headline. Store it even if
    # the article cannot be fetched, and identify this shorter source explicitly.
    for item in items:
        existing = engine.store.get_by_url(item.url, with_text=False)
        if item.provider == "news_feeds" and item.published_at and item.title and (
                not existing or existing.get("source_type") == "news_feed"):
            engine.store.upsert(item.url, item.title, item.snippet, source_type="news_feed",
                                published_at=item.published_at,
                                metadata={"publication_source": "news_feeds", "feed_url": item.source_url})
    for item in items:
        if time.monotonic() >= deadline:
            errors.append("Discovery deadline reached; remaining pages were not fetched.")
            break
        try:
            existing = engine.store.get_by_url(item.url)
            if existing and existing.get("active") and existing.get("source_type") != "news_feed" and time.time() - (iso_to_ts(existing.get("fetched_at")) or 0) < 900:
                out = {"result": "cached", "doc_status": "unchanged", "title": existing["title"]}
            else:
                r = client.fetch(item.url)
                if not 200 <= r.status < 300:
                    raise ValueError(f"HTTP {r.status}")
                out = processor.process(item.url, r.final_url, r.status, r.headers, r.body, enqueue=False,
                                        published_at=item.published_at, publication_source=item.provider,
                                        source_type="reference" if item.provider == "wikipedia" else None)
                if out.get("result") == "ok":
                    frontier.enqueue_many([{"url": r.final_url, "priority": 8.0, "source": "discovery", "depth": 0}])
            results.append({"url": item.url, "provider": item.provider, "sources": item.sources or [item.provider],
                            **{k: out[k] for k in ("result", "doc_status", "title") if k in out}})
            if sum(r.get("result") in ("ok", "cached") for r in results) >= engine.settings.discovery_min_results:
                engine.rebuild_index()
                check = engine._search(query, 5, 0, False, None, None, None, None,
                                       200, False, time.perf_counter(), q=pq, request_deadline=deadline)
                if len(check["results"]) >= engine.settings.discovery_min_results and not check["coverage"]["low_confidence"]:
                    break
        except Exception as e:
            errors.append(f"{item.provider} ({item.url}): {e}")
            results.append({"url": item.url, "provider": item.provider, "result": f"error: {e}"[:200]})
    engine.rebuild_index()
    report = {"query": query, "intent": pq.intent, "candidates_found": len(items),
                              "errors": errors, "results": results, "requests": client.requests,
                              "took_ms": round((time.monotonic() - t0) * 1000, 2)}
    engine._last_discovery = report
    if details is not None:
        details.update(report)
    return results
