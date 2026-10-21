"""Independent crawler HTTP API and same-origin HTML UI. No database or providers."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .auth import KeyStore, RateLimiter
from .coordinator import Busy

MAX_BODY = 64_000


def _boolean(value):
    if isinstance(value, bool):
        return value
    if value in ('1', 'true', 'yes'):
        return True
    if value in ('0', 'false', 'no'):
        return False
    raise ValueError('Expected a boolean value')


def make_handler(engine, require_auth=False):
    keys = KeyStore(engine.settings.keys_path)
    limiter = RateLimiter()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'OwnSearch/' + __version__
        timeout = 10
        def log_message(self, *_):
            pass

        def send(self, status, obj, content_type='application/json; charset=utf-8'):
            data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src https: http:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def route(self):
            try:
                if self.server.server_address[0] in ('127.0.0.1', '::1'):
                    host = urlsplit('http://' + self.headers.get('Host', '')).hostname
                    if host not in ('127.0.0.1', '::1', 'localhost'):
                        self.send(403, {'error': 'Invalid Host header for loopback server'})
                        return
                target = urlsplit(self.path)
                path = target.path.rstrip('/') or '/'
                if path == '/health':
                    self.send(200, {'ok': True, 'engine': 'OwnSearch ' + __version__, 'mode': 'independent', 'database': False})
                    return
                if path in ('/', '/ui') and self.command in ('GET', 'HEAD'):
                    self.send(200, Path(__file__).with_name('resources').joinpath('search.html').read_bytes(), 'text/html; charset=utf-8')
                    return
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.send(403, {'error': 'Cross-site requests are disabled'})
                    return
                if self.command == 'POST':
                    # Cross-site browser requests may not trigger crawling or read protected results.
                    origin = self.headers.get('Origin')
                    if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                        self.send(403, {'error': 'Cross-origin requests are disabled'})
                        return
                if require_auth:
                    authorization = self.headers.get('Authorization', '')
                    key = authorization[7:].strip() if authorization.lower().startswith('bearer ') else self.headers.get('X-API-Key', '')
                    record = keys.authenticate(key)
                    if not record:
                        self.send(401, {'error': 'Missing or invalid API key'})
                        return
                    if not {'search', 'admin'} & set(record.get('scopes', [])):
                        self.send(403, {'error': 'Key lacks search scope'})
                        return
                    ok, retry, reason = limiter.check(record['agent'], record.get('rps', 20), record.get('burst', 40), record.get('daily_quota', 0))
                    if not ok:
                        self.send(429, {'error': reason, 'retry_after': retry})
                        return
                if path == '/stats' and self.command == 'GET':
                    self.send(200, {'mode': 'independent', 'database': False, 'cache': engine.cache.stats(), 'starting_urls': engine.starting_urls})
                    return
                if path != '/search':
                    self.send(404, {'error': 'Unknown endpoint'})
                    return
                body = {k: v[-1] for k, v in parse_qs(target.query).items()}
                if self.command == 'POST':
                    if self.headers.get('Transfer-Encoding'):
                        raise ValueError('Transfer-Encoding is unsupported')
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 0 or length > MAX_BODY:
                        raise ValueError('Request body exceeds limit')
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError('Incomplete request body')
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError('JSON body must be an object')
                elif self.command != 'GET':
                    self.send(405, {'error': 'Use GET or POST'})
                    return
                query = body.pop('query', body.pop('q', ''))
                if 'timezone' in body:
                    body['timezone_name'] = body.pop('timezone')
                allowed = {'limit', 'offset', 'freshness', 'site', 'filetype', 'lang', 'timeout_ms', 'explain',
                           'use_cache', 'fetch_pages', 'search_type', 'answer_mode', 'preferred_language', 'timezone_name', 'seeds'}
                unknown = set(body)-allowed
                if unknown:
                    raise ValueError('Unknown search options: ' + ', '.join(sorted(unknown)))
                for key in ('explain', 'use_cache', 'fetch_pages', 'answer_mode'):
                    if key in body:
                        body[key] = _boolean(body[key])
                self.send(200, engine.search(query, **body))
            except Busy as error:
                self.send(503, {'error': str(error)})
            except (ValueError, TypeError) as error:
                self.send(400, {'error': str(error)[:300]})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {'error': 'Internal search error'})

        do_GET = route
        do_POST = route
        do_HEAD = route

    return Handler


class SearchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, engine, require_auth=False):
        self.capacity = threading.BoundedSemaphore(max(16, engine.settings.max_concurrent_searches*4))
        super().__init__(address, make_handler(engine, require_auth))
    def process_request(self, request, client_address):
        if not self.capacity.acquire(False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.capacity.release()
            raise
    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


def serve(engine, host='127.0.0.1', port=8765, require_auth=False):
    if host not in ('127.0.0.1', '::1', 'localhost') and not require_auth:
        raise ValueError('Use authentication when exposing the crawler beyond localhost')
    with SearchServer((host, port), engine, require_auth) as server:
        print('OwnSearch Independent: http://' + host + ':' + str(server.server_port) + '/ui', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
