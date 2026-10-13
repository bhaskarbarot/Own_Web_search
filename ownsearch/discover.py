"""Live discovery: when the index does not cover a query, find likely pages at query time.

No search API is used. Candidate URLs are derived from the query itself:
  * Wikipedia articles whose titles match the query's key phrases (https://en.wikipedia.org/wiki/<Title>)
  * official sites of capitalised names in the query (Nvidia -> https://www.nvidia.com/)
  * any domain typed in the query (example.org)
They are fetched politely (robots.txt respected), indexed immediately, and added to the frontier as seeds so
the background crawler keeps exploring those sites.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from .query import FRESH_WORDS
from .textproc import STOPWORDS

_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|org|net|io|in|co|ai|dev|gov|edu|uk|de|info|app))\b", re.I)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&.-]*")
GENERIC = STOPWORDS | FRESH_WORDS | {"price", "stock", "share", "shares", "market", "best", "top", "how", "what",
                                     "review", "reviews", "news", "today", "vs", "versus", "guide", "tutorial"}


def candidate_urls(query, max_urls=6):
    urls = []
    raw_words = _WORD.findall(query)
    for m in _DOMAIN.finditer(query):
        urls.append(f"https://{m.group(1).lower()}/")
    content = [w for w in raw_words if w.lower() not in GENERIC and len(w) > 1]
    # Wikipedia: whole key phrase first, then pairs, then single key words
    phrases = []
    if content:
        phrases.append(" ".join(content[:4]))
        phrases += [" ".join(content[i:i + 2]) for i in range(len(content) - 1)]
        phrases += content
    seen = set()
    for ph in phrases:
        title = ph[:1].upper() + ph[1:]
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append("https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()'-,"))
    # official site guess for capitalised names (Nvidia, OpenAI, Tata) — not for ordinary words
    for w in raw_words:
        if w[:1].isupper() and w.lower() not in GENERIC and w.isalnum() and 3 <= len(w) <= 20:
            urls.append(f"https://www.{w.lower()}.com/")
    out, seen_urls = [], set()
    for u in urls:
        if u not in seen_urls:
            seen_urls.add(u)
            out.append(u)
    return out[:max_urls]


def discover(engine, query, frontier=None, max_urls=6, log=None):
    """Fetch candidate pages for ``query`` now and index them. Returns a list of {url, result}."""
    from .crawler import Crawler
    from .frontier import Frontier
    frontier = frontier or Frontier(engine.settings)
    crawler = Crawler(engine.settings, engine.store, frontier)
    urls = candidate_urls(query, max_urls)
    if not urls:
        return []
    frontier.add_seeds(urls, priority=8.0)           # also lets the background crawler go deeper later

    def one(url):
        try:
            policy = crawler.robots_for(url)
            if not policy.allowed(url):
                return {"url": url, "result": "disallowed"}
            res = crawler.fetcher.fetch(url, allow=lambda u: crawler.robots_for(u).allowed(u), retries=0)
            if not 200 <= res.status < 300:
                frontier.complete(url, {"result": "gone" if res.status in (404, 410) else "failed",
                                        "status": res.status})
                return {"url": url, "result": f"http {res.status}"}
            out = crawler.processor.process(url, res.final_url, res.status, res.headers, res.body)
            frontier.complete(url, out)
            return {"url": res.final_url, "result": out.get("result"), "title": out.get("title")}
        except Exception as e:
            return {"url": url, "result": f"error: {e}"[:200]}

    results = []
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        for fut in as_completed([pool.submit(one, u) for u in urls]):
            r = fut.result()
            results.append(r)
            if log:
                log(f"[discover] {r['result']:10} {r['url']}")
    if any(r["result"] == "ok" for r in results):
        engine.rebuild_index()
    return results
