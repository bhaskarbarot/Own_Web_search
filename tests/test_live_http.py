"""Local HTTP end-to-end checks: API -> provider -> response, with no corpus."""
import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ownsearch.auth import KeyStore, RateLimiter
from ownsearch.coordinator import LiveSearch
from ownsearch.metrics import Metrics
from ownsearch.server import make_handler
from ownsearch.webfetch import WebFetchSession
from tests.test_live_web import settings
from tests.test_server import call


class LiveHTTPTests(unittest.TestCase):
    def test_real_http_provider_and_page_enrichment_without_persistence(self):
        class Fixture(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith('/search?'):
                    body = json.dumps({'results': [{'url': 'http://content.example:'+str(self.server.server_port)+'/guide',
                        'title': 'Nebula installation manual', 'content': 'Nebula installation steps.'}]}).encode()
                    content_type = 'application/json'
                elif self.path == '/robots.txt':
                    body, content_type = b'User-agent: *\nAllow: /', 'text/plain'
                else:
                    body = b'<html><title>Nebula installation manual</title><main><h1>Nebula installation</h1><p>Install Nebula using the installer. Configure Nebula and restart the service.</p></main></html>'
                    content_type = 'text/html'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # Test-only intranet permission and deterministic DNS map; production defaults reject private addresses.
        cfg = settings(searxng_url='http://127.0.0.1:'+str(server.server_port), searxng_allow_private=True,
                       allow_private_hosts=True, discovery_provider_timeout=1, live_fetch_timeout=1)
        original = socket.getaddrinfo
        def resolve(host, port, *args, **kwargs):
            return original('127.0.0.1' if host == 'content.example' else host, port, *args, **kwargs)
        try:
            with patch('socket.getaddrinfo', side_effect=resolve):
                result = LiveSearch(cfg).search('Nebula installation', answer_mode=True)
            self.assertEqual(result['results'][0]['fetch_status'], 'fetched')
            self.assertEqual(result['trace']['page_requests'], 2)
            self.assertIn('installer', result['answer']['text'])
            self.assertFalse(cfg.data_dir.exists())
        finally:
            server.shutdown()
            server.server_close()

    def test_search_only_key_can_discover_but_cannot_fetch_and_no_storage_is_created(self):
        class Provider(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({'results': [{'url': 'https://docs.example/installation',
                    'title': 'Nebula installation manual', 'content': 'Nebula installation steps and configuration.'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        cfg = settings(searxng_url='http://127.0.0.1:'+str(provider.server_port), searxng_allow_private=True,
                       discovery_provider_timeout=1, discovery_timeout=2)
        engine = LiveSearch(cfg)
        key_path = Path(tempfile.mkdtemp())/'api_keys.json'
        keys = KeyStore(key_path)
        token = keys.create('search-only', scopes=['search'])
        api = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(engine, keys, RateLimiter(), Metrics(), None, True, 'full'))
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            with patch.object(WebFetchSession, 'enrich', side_effect=AssertionError('search-only key must not fetch arbitrary pages')):
                status, result = call(api.server_port, 'GET', '/search?q=Nebula+installation', key=token)
                self.assertEqual(status, 200)
                self.assertEqual(result['results'][0]['source_provider'], 'searxng')
                self.assertEqual(result['results'][0]['fetch_status'], 'not_fetched')
                status, result = call(api.server_port, 'POST', '/search', {'query': 'Nebula installation', 'fetch_pages': False}, key=token)
                self.assertEqual(status, 200)
                self.assertTrue(result['results'])
            for path in ('/health', '/stats', '/providers', '/metrics'):
                status, _ = call(api.server_port, 'GET', path, key=token)
                self.assertEqual(status, 200)
            self.assertFalse(cfg.data_dir.exists())
        finally:
            api.shutdown()
            provider.shutdown()
            api.server_close()
            provider.server_close()

    def test_ui_is_available_without_exposing_authenticated_search(self):
        engine = LiveSearch(settings(), [])
        with tempfile.TemporaryDirectory() as temp:
            keys = KeyStore(Path(temp)/'keys.json')
            api = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(engine, keys, RateLimiter(), Metrics(), None, True, 'full'))
            threading.Thread(target=api.serve_forever, daemon=True).start()
            try:
                import http.client
                connection = http.client.HTTPConnection('127.0.0.1', api.server_port, timeout=3)
                connection.request('GET', '/ui')
                response = connection.getresponse()
                page = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn('text/html', response.getheader('Content-Type'))
                self.assertIn("connect-src 'self'", response.getheader('Content-Security-Policy'))
                self.assertIn('id="search-form"', page)
                connection.request('HEAD', '/ui')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'')
                connection.close()
                self.assertEqual(call(api.server_port, 'GET', '/')[1]['name'], 'OwnSearch')
                self.assertEqual(call(api.server_port, 'POST', '/search', {'query': 'Nebula'})[0], 401)
                self.assertFalse(engine.settings.data_dir.exists())
            finally:
                api.shutdown()
                api.server_close()

    def test_live_api_rejects_persistent_ingestion_explicitly(self):
        engine = LiveSearch(settings(), [])
        key_path = Path(tempfile.mkdtemp())/'api_keys.json'
        keys = KeyStore(key_path)
        token = keys.create('admin', scopes=['admin'])
        api = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(engine, keys, RateLimiter(), Metrics(), None, True, 'full'))
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            status, result = call(api.server_port, 'POST', '/ingest', {'title': 'Nebula', 'text': 'No persistence'}, key=token)
            self.assertEqual(status, 409)
            self.assertIn('disabled in live mode', result['error'])
            from dataclasses import replace
            def enrich(session, item, deadline):
                return replace(item, title='Nebula installation', content='Transient Nebula installation text.', fetch_status='fetched')
            with patch.object(WebFetchSession, 'enrich', enrich):
                status, result = call(api.server_port, 'POST', '/fetch', {'url': 'https://docs.example/', 'index': True}, key=token)
            self.assertEqual(status, 200)
            self.assertIsNone(result['document']['id'])
            self.assertFalse(result['persistent_storage'])
            self.assertFalse(engine.settings.data_dir.exists())
        finally:
            api.shutdown()
            api.server_close()


if __name__ == '__main__':
    unittest.main()
