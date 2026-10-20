"""HTTP API for agents (standard library ThreadingHTTPServer).

Roles
  full    search API + background indexer (+ optional crawler threads and periodic PageRank)
  node    read-only search node for the gateway (no background writers; reloads the index automatically)

Endpoints
  GET  /health                          liveness + index generation
  GET  /search?q=...&limit=&offset=&freshness=&site=&filetype=&lang=&evidence=1&explain=0
  POST /search    {"query", "limit", "offset", "fetch_evidence", "freshness", "site", "filetype", "lang"}
  GET  /document?id=N | ?url=...       full stored text of a result (for reading a page)
  POST /fetch     {"url", "index": true}  live-fetch one URL safely (robots.txt respected), extract and index it
  POST /crawl     {"urls": [...], "scope": "domain"|"host"|"open", "priority": 10}  enqueue seeds
  POST /ingest    {"title", "text", "url"}
  POST /feedback  {"query", "url" | "doc_id", "grade": 0-3, "note"}
  GET  /stats  GET /metrics (Prometheus)  GET /frontier
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .auth import KeyStore, RateLimiter
from .crawler import Crawler
from .engine import Busy, SearchEngine
from .fetcher import FetchError
from .frontier import Frontier
from .linkgraph import refresh as refresh_links
from .metrics import Metrics

MAX_BODY = 2_000_000
ENDPOINT_SCOPE = {"/search": "search", "/providers": "search", "/document": "search", "/feedback": "search", "/fetch": "fetch",
                  "/crawl": "crawl", "/ingest": "ingest", "/stats": "search", "/frontier": "search"}
ENDPOINT_COST = {"/fetch": 5.0, "/crawl": 2.0, "/ingest": 1.0}


class BackgroundWorker:
    """Indexer loop, optional crawler threads and periodic PageRank, shared by `serve` and `worker`."""

    def __init__(self, engine, crawl_threads=0, index_interval=5.0, pagerank_interval=3600.0, log=None):
        self.engine = engine
        self.frontier = Frontier(engine.settings)
        self.crawl_threads = crawl_threads
        self.index_interval = index_interval
        self.pagerank_interval = pagerank_interval
        self.stop = threading.Event()
        self.log = log or (lambda m: print(m, file=sys.stderr, flush=True))
        self.threads = []
        self.crawler = None

    def start(self):
        t = threading.Thread(target=self._index_loop, name="indexer", daemon=True)
        t.start()
        self.threads.append(t)
        if self.crawl_threads > 0:
            self.crawler = Crawler(self.engine.settings, self.engine.store, self.frontier, index=None, log=self.log)
            t = threading.Thread(target=self._crawl_loop, name="crawler", daemon=True)
            t.start()
            self.threads.append(t)
        return self

    def _index_loop(self):
        last_rank = time.monotonic()
        rank_seq = self.engine.store.current_seq()
        while not self.stop.wait(self.index_interval):
            try:
                if self.engine.store.current_seq() > self.engine.index.committed_seq:
                    n = self.engine.rebuild_index()
                    if n:
                        self.log(f"[index] committed {n} changes (generation {self.engine.index.generation})")
                if self.pagerank_interval and time.monotonic() - last_rank > self.pagerank_interval:
                    seq = self.engine.store.current_seq()
                    if seq != rank_seq:
                        stats = refresh_links(self.engine.store, self.engine.indexer, log=self.log)
                        self.engine.cache.clear()
                        rank_seq = self.engine.store.current_seq()
                        self.log(f"[pagerank] {stats}")
                    last_rank = time.monotonic()
            except Exception as e:
                self.log(f"[index] error: {e!r}")

    def _crawl_loop(self):
        while not self.stop.is_set():
            try:
                self.crawler.run(threads=self.crawl_threads, until_idle=False, stop_event=self.stop)
            except Exception as e:
                self.log(f"[crawl] loop error: {e!r}")
            self.stop.wait(5)

    def shutdown(self):
        self.stop.set()
        for t in self.threads:
            t.join(10)


def make_handler(engine, keys, limiter, metrics, frontier, require_auth, role):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"OwnSearch/{__version__}"
        protocol_version = "HTTP/1.1"
        timeout = 60

        # ------------------------------------------------------------ plumbing
        def _send(self, status, obj, content_type="application/json; charset=utf-8", extra_headers=None):
            data = obj if isinstance(obj, bytes) else (
                obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            self._status = status

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                raise ValueError("Bad Content-Length")
            if length < 0 or length > MAX_BODY:
                raise ValueError("Request body too large")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("JSON body must be an object")
            return obj

        def _auth(self, path):
            """-> (agent name, error response tuple or None)"""
            scope = ENDPOINT_SCOPE.get(path)
            if not require_auth or scope is None:
                return (self.headers.get("X-Agent") or "anonymous")[:64], None
            key = self.headers.get("X-API-Key") or ""
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
            rec = keys.authenticate(key)
            if rec is None:
                return None, (401, {"error": "Missing or invalid API key"}, {"WWW-Authenticate": "Bearer"})
            scopes = set(rec.get("scopes", ["search"]))
            if scope not in scopes and "admin" not in scopes:
                return None, (403, {"error": f"Key lacks the '{scope}' scope"}, None)
            ok, retry, reason = limiter.check(rec["agent"], rec.get("rps", 20.0), rec.get("burst", 40),
                                              rec.get("daily_quota", 0), ENDPOINT_COST.get(path, 1.0))
            if not ok:
                return None, (429, {"error": reason, "retry_after": round(retry, 2)},
                              {"Retry-After": str(max(1, int(retry + 0.999)))})
            return rec["agent"], None

        def _can_fetch(self):
            key = self.headers.get("X-API-Key") or ""
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
            rec = keys.authenticate(key)
            return bool(rec) and bool({"fetch", "admin"} & set(rec.get("scopes", [])))

        def _dispatch(self, method):
            t0 = time.perf_counter()
            self._status = 500
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            agent = None
            metrics.begin()
            try:
                try:
                    body = self._body() if method == "POST" else {}   # always drain before replying (keep-alive)
                except (ValueError, json.JSONDecodeError) as e:
                    self.close_connection = True
                    self._send(400, {"error": str(e)[:300]})
                    return
                agent, err = self._auth(path)
                if err:
                    self._send(err[0], err[1], extra_headers=err[2])
                    return
                qs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
                self._route(method, path, qs, body, agent)
            except Busy as e:
                self._send(503, {"error": str(e)}, extra_headers={"Retry-After": "1"})
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)[:500]})
            except Exception as e:
                print(f"[api] error on {method} {path}: {e!r}", file=sys.stderr)
                self._send(500, {"error": "Internal error", "detail": str(e)[:300]})
            finally:
                metrics.end(path if path in ENDPOINT_SCOPE or path in ("/", "/health", "/metrics") else "other",
                            self._status, (time.perf_counter() - t0) * 1000, agent)

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def log_message(self, fmt, *args):
            pass

        # ------------------------------------------------------------ routes
        def _route(self, method, path, qs, body, agent):
            live_engine = getattr(engine, 'live_web_first', False)
            if path == "/health":
                if not live_engine:
                    engine.index.maybe_reload()
                index_stats = engine.stats() if live_engine else {'documents': engine.index.doc_count, 'generation': engine.index.generation}
                return self._send(200, {"ok": True, "engine": f"OwnSearch {__version__}", "role": role,
                                        "documents": index_stats['documents'], "generation": index_stats['generation'],
                                        "search_mode": 'live' if live_engine else 'local'})
            if path == "/":
                return self._send(200, {"name": "OwnSearch", "version": __version__, "role": role,
                                        "auth_required": require_auth, "docs": __doc__})
            if path == "/metrics":
                index_stats = engine.stats() if live_engine else {'documents': engine.index.doc_count, 'generation': engine.index.generation}
                return self._send(200, metrics.prometheus({"index_documents": index_stats['documents'],
                                                           "index_generation": index_stats['generation']}),
                                  "text/plain; version=0.0.4")
            if path == '/providers':
                if not live_engine:
                    return self._send(200, {'mode': 'local', 'note': 'Use the providers CLI command to diagnose live sources.'})
                return self._send(200, engine.diagnostics())
            if path == "/search":
                src = body if method == "POST" else qs
                query = src.get("query", src.get("q", ""))
                ev = src.get("fetch_evidence", src.get("evidence", True))
                can_fetch = not require_auth or self._can_fetch()
                extra = ({'fetch_pages': can_fetch and str(src.get('fetch_pages', 'true')).lower() in ('true', '1', 'yes'),
                          'search_type': src.get('search_type', 'web'),
                          'answer_mode': str(src.get('answer_mode', 'false')).lower() in ('true', '1', 'yes')}
                         if live_engine else {})
                res = engine.search(query, src.get("limit", 10), ev, offset=src.get("offset", 0),
                                    freshness=src.get("freshness"), site=src.get("site"),
                                    filetype=src.get("filetype"), lang=src.get("lang"),
                                    preferred_language=src.get("preferred_language") or self.headers.get("Accept-Language"),
                                    timezone_name=src.get("timezone"),
                                    timeout_ms=src.get("timeout_ms"), agent=agent,
                                    live=str(src.get("live", "true")).lower() in ("1", "true", "yes")
                                    and (live_engine or can_fetch),
                                    explain=str(src.get("explain", "")).lower() in ("1", "true", "yes"), **extra)
                return self._send(200, res)
            if path == "/document":
                src = body if method == "POST" else qs
                max_chars = min(int(src.get("max_chars", 200_000)), 2_000_000)
                doc = engine.document(doc_id=src.get("id"), url=src.get("url"), max_chars=max_chars) \
                    if (src.get("id") or src.get("url")) else None
                return self._send(200, doc) if doc else self._send(404, {"error": "Document not found"})
            if path == "/stats":
                stats = engine.stats()
                stats["api"] = metrics.summary()
                stats["usage_today"] = limiter.usage()
                if frontier is not None:
                    stats["frontier"] = frontier.stats()
                return self._send(200, stats)
            if path == "/frontier":
                if frontier is None:
                    return self._send(404, {"error": "No frontier on this node"})
                return self._send(200, {"stats": frontier.stats(),
                                        "sample": frontier.list_urls(qs.get("status"), int(qs.get("limit", 50)))})
            if method != "POST":
                return self._send(405 if path in ENDPOINT_SCOPE else 404, {"error": "Not found"})
            if live_engine and path in ('/ingest', '/crawl', '/feedback'):
                return self._send(409, {'error': 'Persistent storage endpoints are disabled in live mode. Use OWNSEARCH_SEARCH_MODE=local for the optional crawler/index service.'})
            if role == "node" and path in ("/fetch", "/crawl", "/ingest", "/feedback"):
                return self._send(403, {"error": "Read-only search node"})
            if path == "/feedback":
                grade = int(body.get("grade", 1))
                if not 0 <= grade <= 3:
                    raise ValueError("grade must be 0..3")
                engine.store.add_feedback(agent or "", str(body.get("query", "")), str(body.get("url", "")),
                                          body.get("doc_id"), grade, str(body.get("note", "")))
                return self._send(201, {"ok": True})
            if path == "/ingest":
                if not body.get("text") and not body.get("title"):
                    return self._send(400, {"error": "Provide title and/or text"})
                doc = engine.add_document(str(body.get("title", "Untitled")), str(body.get("text", "")),
                                          str(body.get("url", "")) or "", "api", {"ingested_by": agent})
                return self._send(201, {"indexed": True, "id": doc.get("id"), "title": doc.get("title"),
                                        "status": doc.get("status")})
            if path == "/crawl":
                urls = body.get("urls") or ([body["url"]] if body.get("url") else [])
                if not urls or not isinstance(urls, list):
                    return self._send(400, {"error": "Provide url or urls"})
                scope = body.get("scope")
                n = frontier.add_seeds([str(u) for u in urls[:1000]], float(body.get("priority", 10.0)), scope)
                return self._send(202, {"queued_new": n, "frontier": frontier.stats(),
                                        "note": "Crawling runs in the background worker (serve --crawl-threads N "
                                                "or `ownsearch worker`)."})
            if path == "/fetch":
                if live_engine:
                    return self._send(*engine.fetch_url(str(body.get('url', ''))))
                return self._send(*live_fetch(engine, frontier, str(body.get("url", "")),
                                              index=body.get("index", True) is not False))
            return self._send(404, {"error": "Not found"})

    return Handler


def live_fetch(engine, frontier, url, index=True):
    """Fetch one URL now (robots.txt respected), run the pipeline, optionally index immediately."""
    crawler = Crawler(engine.settings, engine.store, frontier or Frontier(engine.settings))
    from .util import normalize_url
    key = normalize_url(url)
    if not key.startswith(("http://", "https://")):
        return 400, {"error": "Provide an absolute http(s) URL"}
    try:
        policy = crawler.robots_for(key)
        if not policy.allowed(key):
            return 403, {"error": "Disallowed by robots.txt", "url": key}
        res = crawler.fetcher.fetch(key, allow=lambda u: crawler.robots_for(u).allowed(u))
    except FetchError as e:
        return 502, {"error": f"{e.kind}: {e}", "url": key}
    if not 200 <= res.status < 300:
        return 502, {"error": f"HTTP {res.status}", "url": key}
    out = crawler.processor.process(key, res.final_url, res.status, res.headers, res.body, enqueue=False)
    if index and out.get("doc_id"):
        engine.rebuild_index()
    doc = engine.document(doc_id=out["doc_id"], max_chars=100_000) if out.get("doc_id") else None
    return 200, {"url": key, "final_url": res.final_url, "status": res.status, "result": out.get("result"),
                 "kind": out.get("kind"), "extraction_status": out.get("extraction_status"), "document": doc}


def serve(host="127.0.0.1", port=8765, engine=None, require_auth=None, role="full", crawl_threads=0,
          allow_insecure=False, pagerank_interval=3600.0):
    if engine is None:
        from .coordinator import search_engine
        engine = search_engine()
    keys = KeyStore(engine.settings.keys_path)
    if require_auth is None:
        require_auth = keys.enabled
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if not require_auth and not loopback and not allow_insecure:
        raise SystemExit("Refusing to listen on a non-loopback address without API keys. Create keys with "
                         "`ownsearch create-key --agent NAME` or pass --insecure if this network is trusted.")
    worker = None
    live_engine = getattr(engine, 'live_web_first', False)
    if live_engine and crawl_threads:
        raise ValueError('Background crawling requires OWNSEARCH_SEARCH_MODE=local; live mode does not persist pages.')
    frontier = Frontier(engine.settings) if role != "node" and not live_engine else None
    if role == "full" and not live_engine:
        worker = BackgroundWorker(engine, crawl_threads=crawl_threads, pagerank_interval=pagerank_interval).start()
    metrics = Metrics()
    handler = make_handler(engine, keys, RateLimiter(), metrics, frontier, require_auth, role)
    server = ThreadingHTTPServer((host, int(port)), handler)
    server.daemon_threads = True
    server.request_queue_size = 256
    print(f"OwnSearch {__version__} [{role}] listening on http://{host}:{port}  auth={'on' if require_auth else 'off'}"
          f"  mode={'live' if live_engine else 'local'}", file=sys.stderr, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping OwnSearch...", file=sys.stderr)
    finally:
        server.server_close()
        if worker:
            worker.shutdown()
