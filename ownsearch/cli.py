"""OwnSearch command line. Run `python3 main.py -h` (or `python3 -m ownsearch.cli -h`)."""
import argparse
import json
import sys
import time


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _engine(args):
    from .config import Settings
    from .engine import SearchEngine
    return SearchEngine(settings=Settings.load(args.data_dir))


def _pretty(res):
    cov = res.get("coverage", {})
    print(f"\n{len(res['results'])} results for {res['query']!r}  ({res['took_ms']} ms, "
          f"{cov.get('matched_documents', 0)} matches in {cov.get('index_documents', 0)} docs, mode={cov.get('mode')})")
    if cov.get("message"):
        print(f"  note: {cov['message']}")
    found = [d for d in res.get("live_discovery", []) if d["result"] == "ok"]
    new = [d for d in found if d.get("doc_status") in ("new", "updated")]
    if found:
        print(f"  live discovery: checked {len(found)} page(s) live, {len(new)} new/updated in the index")
    for r in res["results"]:
        date = (r.get("published_at") or "")[:10]
        print(f"\n{r['rank']:>2}. {r['title']}")
        print(f"    {r['url']}" + (f"  [{date}]" if date else "") + (f"  page {r['page']}" if r.get("page") else "")
              + ("  ⚠ injection-like text" if r.get("injection_risk") else ""))
        print(f"    {r['snippet']}")
    print()


def build_parser():
    p = argparse.ArgumentParser(prog="ownsearch", description="OwnSearch — your own web search engine (no paid APIs)")
    p.add_argument("--data-dir", default=None, help="data directory (default: ./data or $OWNSEARCH_DATA_DIR)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the data directory")
    sub.add_parser("stats", help="index, store and frontier statistics")

    s = sub.add_parser("search", help="search the index")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--freshness", choices=["recent", "day", "week", "month", "year"])
    s.add_argument("--site")
    s.add_argument("--filetype")
    s.add_argument("--lang")
    s.add_argument("--no-evidence", action="store_true")
    s.add_argument("--explain", action="store_true", help="include ranking features per result")
    s.add_argument("--pretty", action="store_true", help="human readable output instead of JSON")
    s.add_argument("--no-live", action="store_true",
                   help="do not fetch new pages when the index does not cover the query")

    s = sub.add_parser("ingest-text", help="index a text string")
    s.add_argument("--title", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--url", default="")

    s = sub.add_parser("ingest", help="index files or a directory (HTML, PDF, DOCX/XLSX/PPTX/ODT, EPUB, text, images)")
    s.add_argument("path")

    s = sub.add_parser("crawl", help="add seed URLs and crawl until done / limits reached")
    s.add_argument("urls", nargs="+")
    s.add_argument("--max-pages", type=int, default=100)
    s.add_argument("--scope", choices=["host", "domain", "open"], default=None,
                   help="host: seed hosts only, domain: same registrable domain (default), open: follow links anywhere")
    s.add_argument("--threads", type=int, default=None)
    s.add_argument("--delay", type=float, default=None, help="minimum seconds between requests to one host")
    s.add_argument("--duration", type=float, default=None, help="stop after N seconds")
    s.add_argument("--quiet", action="store_true")

    s = sub.add_parser("seed", help="add URLs (sites, sitemaps, RSS/Atom feeds) to the frontier without crawling")
    s.add_argument("urls", nargs="+")
    s.add_argument("--scope", choices=["host", "domain", "open"], default=None)
    s.add_argument("--priority", type=float, default=10.0)

    s = sub.add_parser("worker", help="long-running crawler + indexer + PageRank (no HTTP)")
    s.add_argument("--threads", type=int, default=None)
    s.add_argument("--pagerank-interval", type=float, default=3600.0)

    s = sub.add_parser("frontier", help="inspect / manage the crawl frontier")
    s.add_argument("action", choices=["stats", "list", "retry-failed", "recrawl-now"])
    s.add_argument("--status")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--like", help="SQL LIKE pattern for recrawl-now, e.g. 'https://example.org/%%'")

    sub.add_parser("index", help="apply pending document changes to the index (incremental)")
    sub.add_parser("optimize", help="merge all index segments into one")
    sub.add_parser("pagerank", help="recompute PageRank and refresh anchor text")

    s = sub.add_parser("fetch", help="live-fetch one URL now (robots.txt respected) and index it")
    s.add_argument("url")

    s = sub.add_parser("doc", help="show a stored document")
    s.add_argument("ref", help="document id or URL")
    s.add_argument("--max-chars", type=int, default=5000)

    s = sub.add_parser("serve", help="start the HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--role", choices=["full", "node"], default="full")
    s.add_argument("--crawl-threads", type=int, default=0, help="crawl in the background with N threads")
    s.add_argument("--no-auth", action="store_true", help="disable API keys (only for localhost / internal nodes)")
    s.add_argument("--insecure", action="store_true", help="allow non-loopback binding without API keys")
    s.add_argument("--pagerank-interval", type=float, default=3600.0)

    s = sub.add_parser("cluster", help="gateway + N search nodes + 1 primary (indexer/crawler), multi-process")
    s.add_argument("--nodes", type=int, default=3)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--crawl-threads", type=int, default=0)
    s.add_argument("--no-auth", action="store_true")
    s.add_argument("--insecure", action="store_true")

    s = sub.add_parser("gateway", help="run only the gateway in front of existing nodes")
    s.add_argument("--backends", required=True, help="comma separated node URLs")
    s.add_argument("--primary", help="node URL that receives crawl/ingest/fetch")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-auth", action="store_true")

    s = sub.add_parser("create-key", help="create an API key for an agent")
    s.add_argument("--agent", required=True)
    s.add_argument("--rps", type=float, default=20.0)
    s.add_argument("--burst", type=int, default=40)
    s.add_argument("--daily-quota", type=int, default=0, help="0 = unlimited")
    s.add_argument("--scopes", default="search,fetch", help="search,fetch,crawl,ingest,admin")
    sub.add_parser("list-keys", help="list agents with API keys")
    s = sub.add_parser("revoke-key", help="revoke an agent's key")
    s.add_argument("--agent", required=True)

    s = sub.add_parser("import-warc", help="index WARC/WET archive files (e.g. downloaded from Common Crawl)")
    s.add_argument("paths", nargs="+")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--discover", action="store_true", help="also add discovered links to the frontier")

    sub.add_parser("cc-crawls", help="list available Common Crawl collections")
    s = sub.add_parser("cc-import", help="import pages for a URL pattern from the free Common Crawl index")
    s.add_argument("pattern", help="e.g. 'example.org/*' or '*.example.org'")
    s.add_argument("--crawl", help="collection id, e.g. CC-MAIN-2025-30 (default: latest)")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--discover", action="store_true")

    s = sub.add_parser("eval", help="evaluate ranking quality against relevance judgments")
    s.add_argument("qrels")
    s = sub.add_parser("train-ranker", help="learn ranker weights from relevance judgments (writes ranker.json)")
    s.add_argument("qrels")
    s.add_argument("--rounds", type=int, default=6)
    s = sub.add_parser("qrels-from-feedback", help="export agent feedback as a judgments file")
    s.add_argument("out")

    s = sub.add_parser("bench", help="concurrent query load test")
    s.add_argument("--url", help="benchmark a running server instead of in-process")
    s.add_argument("--key")
    s.add_argument("--concurrency", type=int, default=7)
    s.add_argument("--duration", type=float, default=20.0)
    s.add_argument("--queries", help="file with one query per line")
    s.add_argument("--cache", action="store_true", help="allow the query cache (in-process mode)")
    s = sub.add_parser("bench-index", help="index scaling benchmark on a synthetic corpus (temporary directory)")
    s.add_argument("--sizes", default="10000,50000,100000")
    return p


def _install_signal_handlers():
    """Ctrl+C and SIGTERM both stop servers/crawlers cleanly, even when started from a background shell
    (which would otherwise inherit an ignored SIGINT)."""
    import signal

    def stop(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.signal(signal.SIGTERM, stop)
    except ValueError:              # not in the main thread (e.g. embedded use)
        pass


def main(argv=None):
    _install_signal_handlers()
    args = build_parser().parse_args(argv)
    cmd = args.command

    if cmd in ("create-key", "list-keys", "revoke-key"):
        from .auth import KeyStore
        from .config import Settings
        settings = Settings.load(args.data_dir)
        settings.ensure_dirs()
        keys = KeyStore(settings.keys_path)
        if cmd == "create-key":
            key = keys.create(args.agent, args.rps, args.burst, args.daily_quota,
                              [s.strip() for s in args.scopes.split(",") if s.strip()])
            _print({"agent": args.agent, "api_key": key,
                    "note": "Store this key now; only its hash is saved. Send it as 'Authorization: Bearer <key>'."})
        elif cmd == "list-keys":
            _print(keys.list())
        else:
            _print({"revoked": keys.revoke(args.agent)})
        return

    if cmd == "bench-index":
        from .bench import index_scaling
        index_scaling(tuple(int(x) for x in args.sizes.split(",")), log=lambda m: print(m, flush=True))
        return

    if cmd == "gateway":
        from .config import Settings
        from .gateway import Gateway
        settings = Settings.load(args.data_dir)
        Gateway([u.strip() for u in args.backends.split(",") if u.strip()], settings.keys_path,
                require_auth=not args.no_auth, cache_ttl=settings.cache_ttl, primary=args.primary).serve(args.host, args.port)
        return

    if cmd == "cluster":
        from .config import Settings
        from .gateway import run_cluster
        settings = Settings.load(args.data_dir)
        settings.ensure_dirs()
        run_cluster(settings.data_dir, args.nodes, args.host, args.port, args.crawl_threads,
                    False if args.no_auth else None, args.insecure)
        return

    if cmd == "bench" and args.url:
        from .bench import http_load
        queries = [q.strip() for q in open(args.queries, encoding="utf-8") if q.strip()] if args.queries else \
            ["search engine", "python", "web crawler", "news today", "pdf", "machine learning", "api documentation"]
        _print(http_load(args.url, queries, args.concurrency, args.duration, args.key))
        return

    engine = _engine(args)
    s = engine.settings

    if cmd == "init":
        print(f"Initialized OwnSearch at {s.data_dir}")
    elif cmd == "stats":
        from .frontier import Frontier
        st = engine.stats()
        st["frontier"] = Frontier(s).stats()
        _print(st)
    elif cmd == "search":
        res = engine.search(args.query, args.limit, not args.no_evidence, offset=args.offset, freshness=args.freshness,
                            site=args.site, filetype=args.filetype, lang=args.lang, explain=args.explain, agent="cli",
                            live=not args.no_live)
        _pretty(res) if args.pretty else print(json.dumps(res, ensure_ascii=False, indent=2))
    elif cmd == "ingest-text":
        d = engine.add_document(args.title, args.text, args.url or "")
        _print({"indexed": True, "document_id": d["id"], "title": d.get("title"), "status": d.get("status")})
    elif cmd == "ingest":
        from .ingest import ingest_path
        _print({"results": ingest_path(args.path, engine, log=_log)})
    elif cmd in ("crawl", "seed"):
        from .crawler import Crawler
        from .frontier import Frontier
        if getattr(args, "delay", None) is not None:
            s.default_delay = max(0.0, args.delay)
        frontier = Frontier(s)
        n = frontier.add_seeds(args.urls, getattr(args, "priority", 10.0), args.scope)
        if cmd == "seed":
            _print({"queued_new": n, "frontier": frontier.stats()})
            return
        crawler = Crawler(s, engine.store, frontier, index=engine.index, log=None if args.quiet else _log)
        stats = crawler.run(max_pages=args.max_pages, duration=args.duration, threads=args.threads)
        from .linkgraph import refresh
        stats["pagerank"] = refresh(engine.store, engine.indexer)
        _print(stats)
    elif cmd == "worker":
        from .server import BackgroundWorker
        w = BackgroundWorker(engine, crawl_threads=args.threads or s.crawl_threads,
                             pagerank_interval=args.pagerank_interval).start()
        _log(f"[worker] crawling with {w.crawl_threads} threads; Ctrl+C to stop")
        try:
            while True:
                time.sleep(60)
                _log(f"[worker] {json.dumps(w.frontier.stats())}")
        except KeyboardInterrupt:
            w.shutdown()
    elif cmd == "frontier":
        from .frontier import Frontier
        f = Frontier(s)
        if args.action == "stats":
            _print(f.stats())
        elif args.action == "list":
            _print(f.list_urls(args.status, args.limit))
        elif args.action == "retry-failed":
            _print({"requeued": f.retry_failed()})
        else:
            _print({"rescheduled": f.recrawl_now(args.like)})
    elif cmd == "index":
        _print({"applied_changes": engine.rebuild_index(), "index": engine.index.stats()})
    elif cmd == "optimize":
        _print({"merges": engine.optimize(), "index": engine.index.stats()})
    elif cmd == "pagerank":
        from .linkgraph import refresh
        _print(refresh(engine.store, engine.indexer, log=_log))
    elif cmd == "fetch":
        from .frontier import Frontier
        from .server import live_fetch
        status, body = live_fetch(engine, Frontier(s), args.url)
        if body.get("document"):
            body["document"]["text"] = body["document"]["text"][:2000]
        _print({"http": status, **body})
    elif cmd == "doc":
        ref = args.ref
        doc = engine.document(doc_id=int(ref), max_chars=args.max_chars) if ref.isdigit() else \
            engine.document(url=ref, max_chars=args.max_chars)
        _print(doc or {"error": "not found"})
    elif cmd == "serve":
        from .server import serve
        serve(args.host, args.port, engine=engine, require_auth=False if args.no_auth else None, role=args.role,
              crawl_threads=args.crawl_threads, allow_insecure=args.insecure, pagerank_interval=args.pagerank_interval)
    elif cmd == "import-warc":
        from .frontier import Frontier
        from .warc import import_warc
        frontier = Frontier(s) if args.discover else None
        _print([dict(path=p, **import_warc(p, engine, frontier, args.limit, log=_log)) for p in args.paths])
    elif cmd == "cc-crawls":
        from .warc import CommonCrawl
        _print([{"id": c["id"], "name": c.get("name")} for c in CommonCrawl(s).crawls()[:24]])
    elif cmd == "cc-import":
        from .frontier import Frontier
        from .warc import CommonCrawl
        frontier = Frontier(s) if args.discover else None
        _print(CommonCrawl(s).import_pattern(engine, args.pattern, args.crawl, args.limit, frontier, log=_log))
    elif cmd == "eval":
        from .evaluation import evaluate, load_qrels
        _print(evaluate(engine, load_qrels(args.qrels)))
    elif cmd == "train-ranker":
        from .evaluation import load_qrels, save_ranker, train
        result = train(engine, load_qrels(args.qrels), rounds=args.rounds, log=_log)
        save_ranker(s.ranker_path, result)
        _print(result)
    elif cmd == "qrels-from-feedback":
        from .evaluation import qrels_from_feedback
        data = qrels_from_feedback(engine.store)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _print({"queries": len(data["queries"]), "written": args.out})
    elif cmd == "bench":
        from .bench import inprocess_load, sample_queries
        queries = [q.strip() for q in open(args.queries, encoding="utf-8") if q.strip()] if args.queries else \
            sample_queries(engine)
        _print(inprocess_load(engine, queries, args.concurrency, args.duration, cache=args.cache))


if __name__ == "__main__":
    main()
