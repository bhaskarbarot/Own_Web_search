"""Polite multi-threaded crawler driven by the persistent frontier.

Per fetch: robots.txt check (cached, RFC 9309 semantics) -> conditional GET with safe redirects ->
status handling (304, 404/410, 401/403, 429/503 backoff, 5xx retry) -> shared pipeline -> frontier update.
New hosts get their sitemaps (from robots.txt or /sitemap.xml) queued automatically. A background thread
commits new documents to the index while crawling.
"""
import sys
import threading
import time
from collections import Counter, defaultdict

from .fetcher import FetchError, Fetcher
from .indexer import Indexer
from .pipeline import Processor
from .robots import RobotsPolicy
from .util import host_of, normalize_url, origin_of


class Crawler:
    def __init__(self, settings, store, frontier, index=None, log=None):
        self.settings, self.store, self.frontier, self.index = settings, store, frontier, index
        self.fetcher = Fetcher(settings)
        self.processor = Processor(settings, store, frontier)
        self.indexer = Indexer(store, index, settings) if index is not None else None
        self.log = log
        self._robots = {}
        self._robots_lock = threading.Lock()
        self._host_locks = defaultdict(threading.Lock)
        self.stats = Counter()
        self._deadline = None
        self._reserved_bytes = 0
        self._bytes_at_start = 0
        self._stats_lock = threading.Lock()

    def _say(self, msg):
        if self.log:
            self.log(msg)

    def _count(self, key, n=1):
        with self._stats_lock:
            self.stats[key] += n

    def _fetch_budgeted(self,url,**kwargs):
        requested=kwargs.get('max_bytes',self.settings.max_page_bytes)
        with self._stats_lock:
            remaining=self.settings.max_crawl_bytes-(self.stats['decoded_bytes']-self._bytes_at_start)-self._reserved_bytes
            reservation=min(self.settings.max_decompressed_bytes,requested*4,remaining)
            if reservation<=0:raise FetchError('Crawl byte budget exhausted','budget')
            self._reserved_bytes+=reservation
        try:
            kwargs['max_bytes']=min(requested,reservation)
            response=self.fetcher.fetch(url,max_decompressed_bytes=reservation,**kwargs)
            if len(response.body)>reservation:raise FetchError('Decoded crawl response exceeds byte reservation','too_large')
            with self._stats_lock:self.stats['decoded_bytes']+=len(response.body)
            return response
        finally:
            with self._stats_lock:self._reserved_bytes-=reservation

    # ------------------------------------------------------------ robots
    def robots_for(self, url):
        host = host_of(url)
        now = time.time()
        cached = self._robots.get(host)
        if cached and cached[1] > now:
            return cached[0]
        with self._host_locks[host]:
            cached = self._robots.get(host)
            if cached and cached[1] > now:
                return cached[0]
            row = self.frontier.host(host)
            token = self.settings.robots_token
            if row and row.get("robots_fetched_at") and now - row["robots_fetched_at"] < self.settings.robots_ttl \
                    and row.get("robots_status") is not None:
                st = row["robots_status"]
                if 200 <= st < 300:
                    policy = RobotsPolicy.parse(row.get("robots_txt") or "", token, st)
                elif 400 <= st < 500 and st != 429:
                    policy = RobotsPolicy.allow_all(st)
                else:
                    policy = None
                if policy is not None:
                    self._robots[host] = (policy, now + 3600)
                    return policy
            policy, ttl = self._fetch_robots(url)
            first_time = not (row and row.get("sitemaps_checked_at"))
            self._robots[host] = (policy, now + ttl)
            if first_time and policy.mode != "disallow_all":
                self._discover_sitemaps(url, policy)
            return policy

    def _fetch_robots(self, url):
        robots_url = origin_of(normalize_url(url)) + "/robots.txt"
        host = host_of(url)
        try:
            res = self._fetch_budgeted(robots_url, max_bytes=512_000, accept="text/plain,*/*;q=0.5", retries=1, deadline=self._deadline)
        except FetchError as e:
            if e.kind in ("blocked", "invalid"):
                return RobotsPolicy.disallow_all(None), 3600
            self.frontier.save_robots(host, None, 599, None)
            return RobotsPolicy.disallow_all(599), 600                 # unreachable: assume disallowed, retry soon
        st = res.status
        if 200 <= st < 300:
            text = res.body.decode("utf-8", "replace")
            if "<html" in text[:1000].lower():                       # soft-404 HTML page instead of robots.txt
                policy = RobotsPolicy.allow_all(st)
                self.frontier.save_robots(host, "", 404, None)
                return policy, self.settings.robots_ttl
            policy = RobotsPolicy.parse(text, self.settings.robots_token, st)
            delay = min(self.settings.max_crawl_delay, policy.crawl_delay) if policy.crawl_delay else None
            self.frontier.save_robots(host, text, st, delay)
            return policy, self.settings.robots_ttl
        if 400 <= st < 500 and st != 429:
            self.frontier.save_robots(host, "", st, None)
            return RobotsPolicy.allow_all(st), self.settings.robots_ttl
        self.frontier.save_robots(host, None, st, None)
        return RobotsPolicy.disallow_all(st), 900

    def _discover_sitemaps(self, url, policy):
        origin = origin_of(normalize_url(url))
        maps = [normalize_url(s, origin) for s in policy.sitemaps[:20]] or [origin + "/sitemap.xml"]
        items = [{"url": m, "priority": 7.0, "source": "robots", "kind": "sitemap", "depth": 0} for m in maps if m]
        if self.frontier.get_meta("scope", "domain") == "open":
            items.append({"url": origin + "/", "priority": 4.0, "source": "host", "depth": 0})
        self.frontier.enqueue_many(items)
        self.frontier.mark_sitemaps_checked(host_of(url))

    # ------------------------------------------------------------ one URL
    def crawl_one(self, item):
        url = item["url"]
        try:
            policy = self.robots_for(url)
        except Exception as e:                                       # never crash a worker on robots problems
            self.frontier.complete(url, {"result": "retry", "error": f"robots: {e}"[:300]})
            return "retry"
        if not policy.allowed(url):
            self.frontier.complete(url, {"result": "disallowed", "error": "robots.txt"})
            self._count("disallowed")
            return "disallowed"
        doc_exists = bool(item.get("doc_id"))
        try:
            res = self._fetch_budgeted(url, etag=item.get("etag") if doc_exists else None,
                                     last_modified=item.get("last_modified") if doc_exists else None,
                                     allow=lambda u: self.robots_for(u).allowed(u), deadline=self._deadline)
        except FetchError as e:
            result = {"robots": "disallowed", "blocked": "blocked", "invalid": "failed", "redirect": "failed",
                      "too_large": "failed", "encoding": "failed", "tls": "failed"}.get(e.kind, "retry")
            self.frontier.complete(url, {"result": result, "error": f"{e.kind}: {e}"[:300]})
            self._count("fetch_error_" + e.kind)
            self._say(f"[crawl] ERR {e.kind:9} {url} {str(e)[:80]}")
            return result
        st = res.status
        self._count(f"http_{st}")
        final = res.final_url
        if final != url and res.redirects:
            self.frontier.complete(url, {"result": "redirected", "status": st, "error": "-> " + final})
            # queued in the future so no other worker grabs it before we record this fetch below
            self.frontier.enqueue_many([{"url": final, "priority": item.get("priority", 3.0), "source": "redirect",
                                         "depth": item.get("depth", 0), "force": True,
                                         "next_fetch_at": time.time() + 3600}], respect_scope=False)
            url = final
        if st == 304:
            self.store.touch(url)
            self.frontier.complete(url, {"result": "not_modified", "status": st})
            self._say(f"[crawl] 304 unchanged {url}")
            return "not_modified"
        if st in (404, 410):
            self.store.deactivate(url=url, reason=f"http {st}")
            self.frontier.complete(url, {"result": "gone", "status": st})
            return "gone"
        if st in (401, 403, 451):
            self.store.deactivate(url=url, reason=f"http {st}")
            self.frontier.complete(url, {"result": "blocked", "status": st})
            return "blocked"
        if st in (429, 503):
            ra = res.headers.get("x-retry-after")
            self.frontier.complete(url, {"result": "retry", "status": st, "host_backoff": True,
                                         "retry_after": float(ra) if ra not in (None, "") else None,
                                         "error": f"http {st}"})
            return "retry"
        if st >= 500:
            self.frontier.complete(url, {"result": "retry", "status": st, "error": f"http {st}"})
            return "retry"
        if not 200 <= st < 300:
            self.frontier.complete(url, {"result": "failed", "status": st, "error": f"http {st}"})
            return "failed"
        try:
            out = self.processor.process(url, final, st, res.headers, res.body, depth=item.get("depth", 0),
                                         previous_hash=item.get("content_hash"))
        except Exception as e:
            self.frontier.complete(url, {"result": "failed", "status": st,
                                         "error": f"process: {e.__class__.__name__}: {e}"[:300]})
            self._count("process_error")
            return "failed"
        if res.truncated:
            out["extraction_status"] = (out.get("extraction_status") or "") + " (truncated)"
        self.frontier.complete(url, out)
        self._count("pages_ok")
        if out.get("doc_status") in ("new", "updated"):
            self._count("docs_" + out["doc_status"])
        self._say(f"[crawl] {st} {out.get('kind', ''):7} +{out.get('new_links', 0):<4} {url}"
                  + (f"  [{out.get('extraction_status')}]" if out.get("extraction_status") not in ("ok", None) else ""))
        return out["result"]

    # ------------------------------------------------------------ loop
    def run(self, max_pages=None, duration=None, threads=None, until_idle=True, stop_event=None, index_every=20.0,
            idle_wait=30.0):
        threads = max(1, int(threads or self.settings.crawl_threads))
        stop = stop_event or threading.Event()
        self.frontier.recover_leases()
        deadline = time.monotonic() + duration if duration else None
        self._deadline = deadline
        initial_bytes = self.stats.get("decoded_bytes",0)
        self._bytes_at_start = initial_bytes
        started = [0]
        lock = threading.Lock()
        start_time = time.monotonic()

        def worker():
            while not stop.is_set():
                if deadline and time.monotonic() > deadline:
                    return
                with lock:
                    if self.stats.get("decoded_bytes",0)-initial_bytes >= self.settings.max_crawl_bytes: return
                    if max_pages and started[0] >= max_pages:
                        return
                item = self.frontier.claim()
                if item is None:
                    wait = self.frontier.next_due_in()
                    if until_idle and (wait is None or wait > idle_wait) and self.frontier.leased_count() == 0:
                        return
                    stop.wait(min(2.0, wait if wait is not None else 1.0) or 0.05)
                    continue
                with lock:
                    if self.stats.get("decoded_bytes",0)-initial_bytes >= self.settings.max_crawl_bytes: return
                    if max_pages and started[0] >= max_pages:
                        self.frontier.release(item["url"])
                        return
                    started[0] += 1
                try:
                    self.crawl_one(item)
                except Exception as e:                      # last-resort safety net
                    print(f"[crawl] worker error on {item['url']}: {e!r}", file=sys.stderr)
                    try:
                        self.frontier.complete(item["url"], {"result": "retry", "error": repr(e)[:300]})
                    except Exception:
                        pass

        def index_loop():
            while not stop.wait(index_every):
                self._index()

        pool = [threading.Thread(target=worker, name=f"crawl-{i}", daemon=True) for i in range(threads)]
        indexer_thread = threading.Thread(target=index_loop, daemon=True) if self.indexer else None
        for t in pool:
            t.start()
        if indexer_thread:
            indexer_thread.start()
        try:
            for t in pool:
                while t.is_alive():
                    t.join(0.5)
        except KeyboardInterrupt:
            self._say("[crawl] stopping (Ctrl+C) ...")
            stop.set()
            for t in pool:
                t.join(30)
        stop.set()
        indexed = self._index()
        result = dict(self.stats)
        result.update(fetched=started[0], seconds=round(time.monotonic() - start_time, 1), indexed_changes=indexed,
                      frontier=self.frontier.stats())
        return result

    def _index(self):
        if not self.indexer:
            return 0
        try:
            n = self.indexer.run()
            if n:
                self._say(f"[index] committed {n} document changes")
            return n
        except Exception as e:
            print(f"[index] error: {e!r}", file=sys.stderr)
            return 0
