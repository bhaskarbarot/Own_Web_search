"""Live discovery: find and index relevant pages at query time when the local index lacks coverage.

Supports a modular provider architecture:
  * SearXNGProvider: self-hosted metasearch instance (configurable, optional)
  * NewsFeedProvider: configured RSS/Atom/JSON news feeds
  * WikipediaProvider: encyclopedic reference pages (strictly disabled for news and financial queries)
  * OfficialSiteProvider: verified domains for official and tech documentation queries
  * FinancialProvider: optional live financial data endpoint

Candidate pages are fetched safely (robots.txt and politeness respected), indexed incrementally,
and queued to the frontier for background exploration.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import quote, urlparse

from .extract.feeds import parse_feed
from .query import FRESH_WORDS, ParsedQuery, parse_query
from .textproc import STOPWORDS, tokenize
from .util import normalize_url

_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|org|net|io|in|co|ai|dev|gov|edu|uk|de|info|app))\b", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&.-]*")
GENERIC = STOPWORDS | FRESH_WORDS | {"price", "stock", "share", "shares", "market", "best", "top", "how", "what",
                                     "review", "reviews", "news", "today", "vs", "versus", "guide", "tutorial"}


@dataclass
class CandidateItem:
    url: str
    provider: str
    title: str = ""
    snippet: str = ""
    published_at: Optional[str] = None


class BaseProvider:
    name: str = "base"

    def is_configured(self, settings) -> bool:
        return True

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        raise NotImplementedError


class SearXNGProvider(BaseProvider):
    name = "searxng"

    def is_configured(self, settings) -> bool:
        return bool(settings and getattr(settings, "searxng_url", None) and settings.searxng_url.strip())

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        if not self.is_configured(settings):
            return [], []
        endpoint = settings.searxng_url.rstrip("/") + "/search"
        categories = "news" if pq.intent == "news" else (settings.searxng_categories or "general")
        params = {
            "q": query,
            "format": "json",
            "categories": categories,
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/json",
            }
        )
        candidates, errors = [], []
        eff_timeout = min(timeout, getattr(settings, "searxng_timeout", timeout) or timeout)
        try:
            with urllib.request.urlopen(req, timeout=eff_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            for item in data.get("results", [])[:settings.discovery_max_urls]:
                u = item.get("url")
                if u and u.startswith(("http://", "https://")):
                    candidates.append(CandidateItem(
                        url=u,
                        provider=self.name,
                        title=item.get("title", ""),
                        snippet=item.get("content", ""),
                        published_at=item.get("publishedDate")
                    ))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
            err_msg = f"SearXNG ({settings.searxng_url}) request failed: {e}"
            errors.append(err_msg)
            if log:
                log(f"[discover] {err_msg}")
        return candidates, errors


class NewsFeedProvider(BaseProvider):
    name = "news_feeds"

    def is_configured(self, settings) -> bool:
        return bool(settings and getattr(settings, "news_feeds", None) and settings.news_feeds.strip())

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        if not self.is_configured(settings):
            return [], []
        # News feeds should be queried for news intent, fresh intent, or general queries
        if pq.intent not in ("news", "general") and not pq.fresh_intent:
            return [], []
        feeds = [f.strip() for f in re.split(r"[,\n]+", settings.news_feeds) if f.strip()]
        candidates, errors = [], []
        query_terms = {t.lower() for t in tokenize(query) if t.lower() not in STOPWORDS}

        for feed_url in feeds[:5]:
            req = urllib.request.Request(feed_url, headers={"User-Agent": settings.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                parsed = parse_feed(raw, base_url=feed_url)
                if not parsed or not parsed.get("entries"):
                    continue
                for entry in parsed["entries"][:30]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text_terms = {t.lower() for t in tokenize(title + " " + summary)}
                    if query_terms & text_terms:
                        u = entry.get("url")
                        if u and u.startswith(("http://", "https://")):
                            candidates.append(CandidateItem(
                                url=u,
                                provider=self.name,
                                title=title,
                                snippet=summary[:300],
                                published_at=entry.get("published_at")
                            ))
            except Exception as e:
                err_msg = f"NewsFeed ({feed_url}) failed: {e}"
                errors.append(err_msg)
                if log:
                    log(f"[discover] {err_msg}")
        return candidates, errors


class WikipediaProvider(BaseProvider):
    name = "wikipedia"

    def is_configured(self, settings) -> bool:
        return True

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        # Strictly restrict Wikipedia to reference queries or explicit wikipedia queries (never news, financial, tech docs)
        if pq.intent != "reference" and "wikipedia" not in query.lower():
            return [], []

        raw_words = _WORD.findall(query)
        content = [w for w in raw_words if w.lower() not in GENERIC and len(w) > 1]
        if not content:
            return [], []

        phrases = [" ".join(content[:4])]
        if len(content) > 1:
            phrases.append(" ".join(content[:2]))
        candidates = []
        seen = set()
        for ph in phrases:
            title = ph[:1].upper() + ph[1:]
            key = title.lower()
            if key not in seen:
                seen.add(key)
                u = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()'-")
                candidates.append(CandidateItem(url=u, provider=self.name, title=f"{title} - Wikipedia"))
        return candidates[:2], []


class OfficialSiteProvider(BaseProvider):
    name = "official"

    def is_configured(self, settings) -> bool:
        return True

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        # Do not guess official domains for news queries
        if pq.intent == "news":
            return [], []
        candidates = []
        # Explicit domains typed in query
        for m in _DOMAIN.finditer(query):
            candidates.append(CandidateItem(url=f"https://{m.group(1).lower()}/", provider=self.name))

        # Only guess official domain if query has company or tech docs intent
        if pq.intent in ("company", "tech_docs"):
            raw_words = _WORD.findall(query)
            for w in raw_words:
                if w[:1].isupper() and w.lower() not in GENERIC and w.isalnum() and 3 <= len(w) <= 20:
                    candidates.append(CandidateItem(url=f"https://www.{w.lower()}.com/", provider=self.name))
        return candidates[:2], []


class FinancialProvider(BaseProvider):
    name = "financial"

    def is_configured(self, settings) -> bool:
        return bool(settings and getattr(settings, "financial_provider_url", None) and settings.financial_provider_url.strip())

    def discover(self, query: str, pq: ParsedQuery, settings, timeout: float = 3.0,
                 log=None) -> Tuple[List[CandidateItem], List[str]]:
        if not self.is_configured(settings) or pq.intent != "financial":
            return [], []
        endpoint = settings.financial_provider_url.rstrip("/")
        params = {"q": query}
        url = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": settings.user_agent})
        candidates, errors = [], []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and data.get("url"):
                candidates.append(CandidateItem(
                    url=data["url"],
                    provider=self.name,
                    title=data.get("title", ""),
                    snippet=data.get("snippet", ""),
                    published_at=data.get("timestamp")
                ))
        except Exception as e:
            errors.append(f"Financial provider failed: {e}")
        return candidates, errors


def candidate_urls(query: str, max_urls: int = 6, intent: Optional[str] = None) -> List[str]:
    """Compatibility helper returning a deduplicated list of candidate URLs."""
    pq = parse_query(query)
    if intent:
        pq.intent = intent
    items, _ = gather_candidates(None, query, pq, max_urls=max_urls)
    return [item.url for item in items][:max_urls]


def gather_candidates(engine, query: str, pq: ParsedQuery, max_urls: int = 6,
                      log=None) -> Tuple[List[CandidateItem], List[str]]:
    """Query all configured providers based on query intent and return deduplicated candidates."""
    from .config import Settings
    settings = engine.settings if engine is not None else Settings()
    timeout = getattr(settings, "discovery_timeout", 3.0) if settings else 3.0

    providers: List[BaseProvider] = [
        SearXNGProvider(),
        NewsFeedProvider(),
        FinancialProvider(),
        WikipediaProvider(),
        OfficialSiteProvider(),
    ]

    all_candidates: List[CandidateItem] = []
    all_errors: List[str] = []

    for prov in providers:
        if not prov.is_configured(settings):
            continue
        try:
            cands, errs = prov.discover(query, pq, settings, timeout=min(timeout, 3.0), log=log)
            all_candidates.extend(cands)
            all_errors.extend(errs)
        except Exception as e:
            all_errors.append(f"{prov.name} error: {e}")

    # Deduplicate by normalized URL
    seen_urls = set()
    deduped: List[CandidateItem] = []
    for item in all_candidates:
        u = normalize_url(item.url) or item.url
        if u not in seen_urls:
            seen_urls.add(u)
            item.url = u
            deduped.append(item)
        if len(deduped) >= max_urls:
            break
    return deduped, all_errors


def discover(engine, query: str, frontier=None, max_urls: int = 6, log=None) -> List[dict]:
    """Fetch candidate pages for ``query`` now and index them.

    Returns a list of dicts: ``[{"url", "result", "title", "doc_status", "provider"}]``.
    """
    from .crawler import Crawler
    from .frontier import Frontier

    frontier = frontier or Frontier(engine.settings)
    crawler = Crawler(engine.settings, engine.store, frontier)
    pq = parse_query(query)

    items, errors = gather_candidates(engine, query, pq, max_urls=max_urls, log=log)
    if not items:
        # Record discovery run details
        engine._last_discovery = {
            "query": query,
            "intent": pq.intent,
            "candidates_found": 0,
            "errors": errors,
            "results": [],
            "took_ms": 0.0,
        }
        return []

    urls = [item.url for item in items]
    frontier.add_seeds(urls, priority=8.0)

    url_to_item = {item.url: item for item in items}
    now = time.time()
    results = []

    def one(url: str) -> dict:
        item = url_to_item.get(url)
        prov_name = item.provider if item else "unknown"
        try:
            # Check if recently fetched (cache/freshness guard to prevent redundant HTTP requests)
            existing = engine.store.get_by_url(url)
            if existing and existing.get("active") and existing.get("fetched_at"):
                # If fetched within the last 15 minutes, don't re-download
                from .util import iso_to_ts
                fetched_ts = iso_to_ts(existing["fetched_at"]) or 0
                if now - fetched_ts < 900:
                    return {
                        "url": url,
                        "result": "cached",
                        "title": existing.get("title"),
                        "doc_status": "unchanged",
                        "provider": prov_name,
                    }

            policy = crawler.robots_for(url)
            if not policy.allowed(url):
                return {"url": url, "result": "disallowed", "provider": prov_name}

            res = crawler.fetcher.fetch(url, allow=lambda u: crawler.robots_for(u).allowed(u), retries=0)
            if not 200 <= res.status < 300:
                frontier.complete(url, {"result": "gone" if res.status in (404, 410) else "failed",
                                        "status": res.status})
                return {"url": url, "result": f"http {res.status}", "provider": prov_name}

            out = crawler.processor.process(url, res.final_url, res.status, res.headers, res.body)
            # If the provider provided verified publication date and processor did not extract one, attach it
            if item and item.published_at and not out.get("published_at"):
                out["published_at"] = item.published_at

            frontier.complete(url, out)
            return {
                "url": res.final_url,
                "result": out.get("result"),
                "title": out.get("title"),
                "doc_status": out.get("doc_status"),
                "provider": prov_name,
            }
        except Exception as e:
            return {"url": url, "result": f"error: {e}"[:200], "provider": prov_name}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        for fut in as_completed([pool.submit(one, u) for u in urls]):
            r = fut.result()
            results.append(r)
            if log:
                log(f"[discover] {r.get('provider', '')} {r['result']:10} {r['url']}")

    if any(r["result"] == "ok" for r in results):
        engine.rebuild_index()

    discovery_took_ms = round((time.perf_counter() - t0) * 1000, 2)
    engine._last_discovery = {
        "query": query,
        "intent": pq.intent,
        "candidates_found": len(items),
        "errors": errors,
        "results": results,
        "took_ms": discovery_took_ms,
    }
    return results
