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
    search.add_argument('--pdf', default=None, help='Export results to PDF file')
    serve_parser = sub.add_parser('serve')
    serve_parser.add_argument('--host', default='127.0.0.1')
    serve_parser.add_argument('--port', type=int, default=8765)
    serve_parser.add_argument('--require-auth', action='store_true')
    serve_parser.add_argument('--seed', action='append', default=None)
    sub.add_parser('status')
    sub.add_parser('mcp')
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
    engine = IndependentSearch(settings)
    if args.command == 'serve':
        if args.seed:
            engine.starting_urls = list(dict.fromkeys(args.seed + engine.starting_urls))
        from .server import serve
        serve(engine, args.host, args.port, args.require_auth)
    elif args.command == 'search':
        response = engine.search(args.query, seeds=args.seed, limit=args.limit, offset=args.offset,
                                 site=args.site, filetype=args.filetype, lang=args.lang, freshness=args.freshness,
                                 timezone_name=args.timezone, timeout_ms=args.timeout_ms, search_type=args.type,
                                 answer_mode=args.answer, explain=args.explain, fetch_pages=not args.cache_only)
        from .tool import SearchResults
        res_obj = SearchResults(response)
        if args.pdf:
            res_obj.to_pdf(args.pdf)
            print(f"Results exported to {args.pdf}")
        elif args.markdown:
            print(res_obj.to_markdown())
        elif args.json:
            print(res_obj.to_json())
        else:
            print(res_obj.text)
    else:
        print(json.dumps({'mode': 'independent', 'database': False, 'starting_urls': engine.starting_urls,
                          'cache': engine.cache.stats()}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
