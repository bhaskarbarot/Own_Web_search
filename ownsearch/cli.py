"""Owned independent crawler commands; no service bootstrap or document index."""
import argparse
import json
from .config import Settings
from .coordinator import IndependentSearch


def main(argv=None):
    parser = argparse.ArgumentParser(description='OwnSearch Independent — bounded direct web crawling with memory caches')
    parser.add_argument('--data-dir', default=None, help='Configuration directory only; no document database')
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search')
    search.add_argument('query')
    search.add_argument('--seed', action='append', default=None, help='Starting page URL; repeat for several sites')
    search.add_argument('--limit', type=int, default=10)
    search.add_argument('--offset', type=int, default=0)
    for key in ('site', 'filetype', 'lang', 'freshness', 'timezone'):
        search.add_argument('--' + key)
    search.add_argument('--timeout-ms', type=int)
    search.add_argument('--type', choices=('web', 'images', 'video'), default='web')
    search.add_argument('--answer', action='store_true')
    search.add_argument('--explain', action='store_true')
    search.add_argument('--cache-only', action='store_true')
    search.add_argument('--json', action='store_true')
    search.add_argument('--markdown', action='store_true')
    search.add_argument('--format', '-f', choices=('text', 'code', 'markdown', 'json', 'firecrawl'), default=None,
                        help='Agent output format: text, code (only code snippet), markdown, json, firecrawl')
    search.add_argument('--refresh', '--force-refresh', dest='force_refresh', action='store_true',
                        help='Bypass query cache and force a live crawl')
    search.add_argument('--pdf', default=None, help='Export results to PDF file')
    serve_parser = sub.add_parser('serve')
    serve_parser.add_argument('--host', default='127.0.0.1')
    serve_parser.add_argument('--port', type=int, default=8765)
    serve_parser.add_argument('--require-auth', action='store_true')
    serve_parser.add_argument('--seed', action='append', default=None)
    sub.add_parser('status')
    sub.add_parser('mcp')
    crawl_parser = sub.add_parser('crawl', help='Background crawl sitemaps and seeds into persistent index')
    crawl_parser.add_argument('--site', default=None, help='Single site root URL to crawl')
    crawl_parser.add_argument('--sitemap', default=None, help='Sitemap URL to discover and crawl')
    crawl_parser.add_argument('--max-pages', type=int, default=100, help='Maximum pages to index')
    crawl_parser.add_argument('--depth', type=int, default=1, help='Maximum link follow depth')
    crawl_parser.add_argument('--workers', type=int, default=4, help='Concurrent crawl workers')
    crawl_parser.add_argument('--all-sources', action='store_true', help='Crawl all seeds from sources.txt')
    key = sub.add_parser('create-key')
    key.add_argument('agent')
    args = parser.parse_args(argv)
    settings = Settings.load(args.data_dir)
    if args.command == 'create-key':
        from .auth import KeyStore
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        print(KeyStore(settings.keys_path).create(args.agent))
        return 0
    if args.command == 'mcp':
        from .mcp import run_mcp_server
        run_mcp_server()
        return 0
    if args.command in ('serve', 'search', 'crawl'):
        settings.persistent_cache_enabled = True
        settings.source_planning_enabled = True
    engine = IndependentSearch(settings)
    if args.command == 'crawl':
        from .crawler import BackgroundCrawler
        from .sourceplan import load_registry
        crawler = BackgroundCrawler(settings=settings, cache=engine.cache, max_workers=args.workers)
        seeds = []
        if args.site:
            seeds.append(args.site)
        elif args.all_sources or not args.sitemap:
            sources = load_registry(settings.sources_file)
            seeds = [s.url for s in sources]
        sitemaps = [args.sitemap] if args.sitemap else []
        print(f"Starting crawl with {len(seeds)} seeds, {len(sitemaps)} sitemaps (max_pages={args.max_pages}, depth={args.depth})...")
        def progress(msg, stats):
            print(f"[{stats.elapsed_seconds():.1f}s] {msg} ({stats.pages_indexed}/{args.max_pages})")
        stats = crawler.crawl_seeds(
            seeds=seeds,
            max_pages=args.max_pages,
            max_depth=args.depth,
            sitemaps=sitemaps,
            on_progress=progress,
        )
        print(f"Crawl finished. {stats.summary()}")
        return 0
    if args.command == 'serve':
        if args.seed:
            engine.starting_urls = list(dict.fromkeys(args.seed + engine.starting_urls))
        from .server import serve
        serve(engine, args.host, args.port, args.require_auth)
    elif args.command == 'search':
        response = engine.search(args.query, seeds=args.seed, limit=args.limit, offset=args.offset,
                                 site=args.site, filetype=args.filetype, lang=args.lang, freshness=args.freshness,
                                 timezone_name=args.timezone, timeout_ms=args.timeout_ms, search_type=args.type,
                                 answer_mode=args.answer, explain=args.explain, fetch_pages=not args.cache_only,
                                 force_refresh=args.force_refresh)
        from .tool import SearchResults
        res_obj = SearchResults(response)
        if args.pdf:
            res_obj.to_pdf(args.pdf)
            print(f"Results exported to {args.pdf}")
        elif args.format == 'firecrawl':
            print(json.dumps(res_obj.to_firecrawl(), indent=2, ensure_ascii=False))
        elif args.format == 'code':
            print(res_obj.code)
        elif args.format == 'markdown' or args.markdown:
            print(res_obj.to_markdown())
        elif args.format == 'json' or args.json:
            print(res_obj.to_json())
        else:
            print(res_obj.text)
    else:
        print(json.dumps({'mode': 'independent', 'database': False, 'starting_urls': engine.starting_urls,
                          'cache': engine.cache.stats()}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
