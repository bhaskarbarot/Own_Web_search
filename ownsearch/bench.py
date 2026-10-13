"""Benchmarks: concurrent query load tests (in-process or over HTTP) and index scaling with a synthetic corpus."""
import http.client
import json
import random
import tempfile
import threading
import time
from urllib.parse import quote, urlparse

from .metrics import percentile


def sample_queries(engine, n=200, seed=1):
    rng = random.Random(seed)
    rows = engine.store.db.query("SELECT title FROM documents WHERE active=1 AND title != '' ORDER BY RANDOM() LIMIT ?",
                                 (n * 2,))
    out = []
    for (title,) in rows:
        words = [w for w in title.split() if len(w) > 3 and w.isalpha()]
        if words:
            out.append(" ".join(rng.sample(words, min(len(words), rng.choice((1, 2, 2, 3))))))
    return out[:n] or ["search engine", "python", "news", "pdf report"]


def _report(latencies, errors, seconds, concurrency):
    lat = sorted(latencies)
    return {"requests": len(lat) + errors, "ok": len(lat), "errors": errors, "concurrency": concurrency,
            "seconds": round(seconds, 2), "qps": round(len(lat) / seconds, 1) if seconds else None,
            "p50_ms": round(percentile(lat, 50), 1) if lat else None,
            "p95_ms": round(percentile(lat, 95), 1) if lat else None,
            "p99_ms": round(percentile(lat, 99), 1) if lat else None,
            "max_ms": round(lat[-1], 1) if lat else None,
            "error_rate": round(errors / max(1, len(lat) + errors), 4)}


def run_load(call, queries, concurrency=7, duration=20.0):
    latencies, errors = [], [0]
    lock = threading.Lock()
    stop = time.monotonic() + duration
    t0 = time.monotonic()

    def worker(i):
        rng = random.Random(i)
        while time.monotonic() < stop:
            q = rng.choice(queries)
            s = time.perf_counter()
            try:
                ok = call(q)
            except Exception:
                ok = False
            ms = (time.perf_counter() - s) * 1000
            with lock:
                if ok:
                    latencies.append(ms)
                else:
                    errors[0] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return _report(latencies, errors[0], time.monotonic() - t0, concurrency)


def inprocess_load(engine, queries, concurrency=7, duration=20.0, cache=False):
    def call(q):
        engine.search(q, 10, True, use_cache=cache)
        return True
    return run_load(call, queries, concurrency, duration)


def http_load(base_url, queries, concurrency=7, duration=20.0, key=None):
    p = urlparse(base_url)
    local = threading.local()

    def call(q):
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = local.conn = http.client.HTTPConnection(p.hostname, p.port or 80, timeout=30)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            conn.request("GET", f"/search?q={quote(q)}&limit=10", headers=headers)
            r = conn.getresponse()
            r.read()
            return r.status == 200
        except Exception:
            local.conn = None
            raise
    return run_load(call, queries, concurrency, duration)


# ------------------------------------------------------------------ synthetic index scaling

def _zipf_vocab(size, rng):
    letters = "abcdefghijklmnopqrstuvwxyz"
    vocab = set()
    while len(vocab) < size:
        vocab.add("".join(rng.choice(letters) for _ in range(rng.randint(3, 9))))
    vocab = sorted(vocab)
    weights = [1.0 / (i + 1) ** 1.05 for i in range(size)]
    return vocab, weights


def index_scaling(sizes=(10_000, 50_000, 100_000), vocab_size=50_000, words_per_doc=300, queries=200, log=print):
    """Index synthetic documents in growing batches and measure throughput, latency and index size."""
    from .config import Settings
    from .engine import SearchEngine
    rng = random.Random(42)
    vocab, weights = _zipf_vocab(vocab_size, rng)
    out = []
    with tempfile.TemporaryDirectory(prefix="ownsearch-bench-") as tmp:
        settings = Settings.load(tmp, log_queries=False, index_flush_docs=5000)
        engine = SearchEngine(settings=settings)
        done = 0
        for size in sizes:
            t0 = time.time()
            batch = size - done
            for start in range(0, batch, 2000):
                n = min(2000, batch - start)
                with engine.store.db.tx():
                    for i in range(n):
                        words = rng.choices(vocab, weights, k=words_per_doc)
                        doc_no = done + start + i
                        engine.store.upsert(f"https://bench{doc_no % 997}.example/{doc_no}",
                                            " ".join(words[:6]), " ".join(words), fetched_at="2025-01-01T00:00:00+00:00")
            t_store = time.time() - t0
            t1 = time.time()
            engine.rebuild_index()
            t_index = time.time() - t1
            done = size
            qs = [" ".join(rng.choices(vocab[:5000], k=rng.choice((1, 2, 3)))) for _ in range(queries)]
            lat = []
            for q in qs:
                s = time.perf_counter()
                engine.search(q, 10, True, use_cache=False)
                lat.append((time.perf_counter() - s) * 1000)
            lat.sort()
            disk = sum(f.stat().st_size for f in settings.index_dir.iterdir())
            row = {"documents": size, "store_docs_per_s": round(batch / t_store, 1),
                   "index_docs_per_s": round(batch / max(t_index, 1e-6), 1),
                   "segments": len(engine.index.snapshot().readers), "index_mb": round(disk / 1e6, 1),
                   "query_p50_ms": round(percentile(lat, 50), 1), "query_p95_ms": round(percentile(lat, 95), 1),
                   "query_p99_ms": round(percentile(lat, 99), 1)}
            out.append(row)
            if log:
                log(json.dumps(row))
    return out
