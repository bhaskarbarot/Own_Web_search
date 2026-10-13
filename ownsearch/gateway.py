"""API gateway / load balancer for horizontal scaling.

Clients (your agents) talk only to the gateway. It authenticates keys, enforces per-agent rate limits and
quotas, caches search responses, and spreads requests over N search-node processes (least-in-flight with
health checks and failover). Nodes share the same data directory (or replicated segment files), so adding
CPU cores or machines is just starting more nodes.
"""
import hashlib
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__
from .auth import KeyStore, RateLimiter
from .engine import QueryCache
from .metrics import Metrics
from .server import ENDPOINT_COST, ENDPOINT_SCOPE

PASS_HEADERS = ("content-type",)


class Backend:
    def __init__(self, url):
        p = urlparse(url)
        self.url, self.host, self.port = url, p.hostname, p.port or 80
        self.inflight = 0
        self.healthy = False
        self.fails = 0
        self.generation = None
        self.lock = threading.Lock()

    def request(self, method, path, body, headers, timeout=30):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            conn.close()


class Gateway:
    def __init__(self, backends, keys_path, require_auth=True, cache_ttl=60.0, cache_entries=4096, primary=None):
        self.backends = [Backend(u) for u in backends]
        self.primary = Backend(primary) if primary else None     # receives write endpoints (crawl/ingest/fetch)
        self.keys = KeyStore(keys_path)
        self.require_auth = require_auth
        self.limiter = RateLimiter()
        self.metrics = Metrics()
        self.cache = QueryCache(cache_entries, cache_ttl)
        self.stop = threading.Event()
        threading.Thread(target=self._health_loop, daemon=True).start()

    def _health_loop(self):
        while not self.stop.is_set():
            for b in self.backends + ([self.primary] if self.primary else []):
                try:
                    st, _, body = b.request("GET", "/health", None, {}, timeout=3)
                    ok = st == 200
                    gen = json.loads(body).get("generation") if ok else None
                    if ok and gen != b.generation:
                        b.generation = gen
                        self.cache.clear()                  # index changed somewhere: drop cached answers
                    b.healthy, b.fails = ok, 0 if ok else b.fails + 1
                except Exception:
                    b.fails += 1
                    b.healthy = False
            self.stop.wait(2.0)

    def pick(self, exclude=()):
        live = [b for b in self.backends if b.healthy and b not in exclude]
        if not live:
            live = [b for b in self.backends if b not in exclude]
        if not live:
            return None
        return min(live, key=lambda b: (b.inflight, b.fails))

    def forward(self, method, path, body, headers, write=False):
        tried = []
        targets = [self.primary] if write and self.primary else None
        for _ in range(3 if not write else 1):
            b = targets[0] if targets else self.pick(tried)
            if b is None:
                break
            tried.append(b)
            with b.lock:
                b.inflight += 1
            try:
                return b.request(method, path, body, headers, timeout=120 if write else 30)
            except Exception:
                b.healthy = False
                b.fails += 1
            finally:
                with b.lock:
                    b.inflight -= 1
        return 503, {"content-type": "application/json"}, json.dumps({"error": "No healthy search node"}).encode()

    def handler(self):
        gw = self

        class H(BaseHTTPRequestHandler):
            server_version = f"OwnSearch-Gateway/{__version__}"
            protocol_version = "HTTP/1.1"
            timeout = 60

            def log_message(self, *a):
                pass

            def _send(self, status, data, headers=None):
                if not isinstance(data, bytes):
                    data = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", (headers or {}).get("content-type", "application/json; charset=utf-8"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("X-Content-Type-Options", "nosniff")
                for k, v in (headers or {}).items():
                    if k.lower() in ("retry-after", "x-cache"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
                self._status = status

            def _go(self, method):
                t0 = time.perf_counter()
                self._status = 500
                path = urlparse(self.path).path.rstrip("/") or "/"
                agent = None
                gw.metrics.begin()
                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    if length > 2_000_000:
                        self.close_connection = True
                        return self._send(413, {"error": "Body too large"})
                    body = self.rfile.read(length) if length else None
                    if path == "/gateway":
                        return self._send(200, {"backends": [{"url": b.url, "healthy": b.healthy, "inflight": b.inflight,
                                                              "generation": b.generation} for b in gw.backends],
                                                "metrics": gw.metrics.summary(), "usage_today": gw.limiter.usage(),
                                                "cache": {"entries": len(gw.cache.data), "hits": gw.cache.hits}})
                    if path == "/metrics":
                        return self._send(200, gw.metrics.prometheus().encode(), {"content-type": "text/plain"})
                    scope = ENDPOINT_SCOPE.get(path)
                    if gw.require_auth and scope:
                        key = self.headers.get("X-API-Key") or ""
                        a = self.headers.get("Authorization", "")
                        if a.lower().startswith("bearer "):
                            key = a[7:].strip()
                        rec = gw.keys.authenticate(key)
                        if rec is None:
                            return self._send(401, {"error": "Missing or invalid API key"})
                        scopes = set(rec.get("scopes", ["search"]))
                        if scope not in scopes and "admin" not in scopes:
                            return self._send(403, {"error": f"Key lacks the '{scope}' scope"})
                        ok, retry, reason = gw.limiter.check(rec["agent"], rec.get("rps", 20.0), rec.get("burst", 40),
                                                             rec.get("daily_quota", 0), ENDPOINT_COST.get(path, 1.0))
                        if not ok:
                            return self._send(429, {"error": reason, "retry_after": round(retry, 2)},
                                              {"Retry-After": str(max(1, int(retry + 0.999)))})
                        agent = rec["agent"]
                    headers = {k: v for k, v in self.headers.items() if k.lower() in PASS_HEADERS}
                    if agent:
                        headers["X-Agent"] = agent
                    cache_key = None
                    if path == "/search":
                        cache_key = hashlib.sha256((self.path + "|" + (body or b"").decode("utf-8", "replace"))
                                                   .encode()).hexdigest()
                        hit = gw.cache.get(cache_key)
                        if hit:
                            return self._send(hit[0], hit[2], dict(hit[1], **{"x-cache": "HIT"}))
                    write = path in ("/crawl", "/ingest", "/fetch", "/feedback")
                    st, rh, data = gw.forward(method, self.path, body, headers, write=write)
                    if cache_key and st == 200:
                        gw.cache.put(cache_key, (st, {"content-type": rh.get("content-type", "application/json")}, data))
                    return self._send(st, data, rh)
                except Exception as e:
                    return self._send(502, {"error": f"Gateway error: {e}"[:300]})
                finally:
                    gw.metrics.end(path, self._status, (time.perf_counter() - t0) * 1000, agent)

            def do_GET(self):
                self._go("GET")

            def do_POST(self):
                self._go("POST")

        return H

    def serve(self, host, port):
        server = ThreadingHTTPServer((host, int(port)), self.handler())
        server.daemon_threads = True
        server.request_queue_size = 512
        print(f"OwnSearch gateway on http://{host}:{port} -> {[b.url for b in self.backends]} "
              f"auth={'on' if self.require_auth else 'off'}", file=sys.stderr, flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            server.server_close()


def run_cluster(data_dir, nodes, host, port, crawl_threads, require_auth, allow_insecure=False):
    """Start N read-only search nodes + 1 primary (indexer/crawler) + the gateway, as separate processes."""
    procs = []
    base = int(port) + 1
    env = dict(os.environ, OWNSEARCH_DATA_DIR=str(data_dir))
    main = [sys.executable, "-m", "ownsearch.cli"]
    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # project root, so -m works anywhere
    try:
        primary_port = base
        procs.append(subprocess.Popen(main + ["serve", "--host", "127.0.0.1", "--port", str(primary_port), "--no-auth",
                                              "--role", "full", "--crawl-threads", str(crawl_threads)], env=env, cwd=cwd))
        node_urls = []
        for i in range(nodes):
            p = base + 1 + i
            procs.append(subprocess.Popen(main + ["serve", "--host", "127.0.0.1", "--port", str(p), "--no-auth",
                                                  "--role", "node"], env=env, cwd=cwd))
            node_urls.append(f"http://127.0.0.1:{p}")
        time.sleep(1.5)
        from .config import Settings
        settings = Settings.load(data_dir)
        keys = KeyStore(settings.keys_path)
        auth = keys.enabled if require_auth is None else require_auth
        if not auth and host not in ("127.0.0.1", "localhost", "::1") and not allow_insecure:
            raise SystemExit("Refusing to expose the gateway without API keys (create-key) or --insecure.")
        gw = Gateway(node_urls, settings.keys_path, require_auth=auth, cache_ttl=settings.cache_ttl,
                     primary=f"http://127.0.0.1:{primary_port}")
        gw.serve(host, port)
    finally:
        for p in procs:
            try:
                p.send_signal(signal.SIGTERM)
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
