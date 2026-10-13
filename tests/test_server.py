"""Phase 7/8: API auth, scopes, per-agent rate limits, endpoints, concurrency, gateway failover."""
import http.client
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from ownsearch.auth import KeyStore, RateLimiter
from ownsearch.gateway import Gateway
from ownsearch.metrics import Metrics
from ownsearch.server import make_handler

from tests.helpers import make_engine


def start(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def call(port, method, path, body=None, key=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data.decode()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e, tmp = make_engine()
        e.add_document("Mango cultivation", "Mangoes grow in tropical climates. Mango trees need sun.", "https://f.example/mango")
        cls.e = e
        keys = KeyStore(e.settings.keys_path)
        cls.key = keys.create("agent-1", rps=5, burst=5, scopes=["search"])
        cls.admin = keys.create("admin", rps=100, burst=100, scopes=["admin"])
        from ownsearch.frontier import Frontier
        handler = make_handler(e, keys, RateLimiter(), Metrics(), Frontier(e.settings), True, "full")
        cls.srv, cls.port = start(handler)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_requires_key(self):
        st, body = call(self.port, "GET", "/search?q=mango")
        self.assertEqual(st, 401)
        st, body = call(self.port, "GET", "/search?q=mango", key="wrong")
        self.assertEqual(st, 401)
        st, _ = call(self.port, "GET", "/health")
        self.assertEqual(st, 200)

    def test_search_get_and_post(self):
        st, body = call(self.port, "GET", "/search?q=mango&limit=3", key=self.admin)
        self.assertEqual(st, 200)
        self.assertEqual(body["results"][0]["title"], "Mango cultivation")
        st, body = call(self.port, "POST", "/search", {"query": "mango trees", "limit": 2}, key=self.admin)
        self.assertEqual(st, 200)
        self.assertTrue(body["evidence"])

    def test_scopes(self):
        st, body = call(self.port, "POST", "/ingest", {"title": "x", "text": "y"}, key=self.key)
        self.assertEqual(st, 403)
        st, body = call(self.port, "POST", "/ingest", {"title": "Papaya", "text": "papaya facts"}, key=self.admin)
        self.assertEqual(st, 201)
        st, body = call(self.port, "GET", "/search?q=papaya", key=self.admin)
        self.assertEqual(body["results"][0]["title"], "Papaya")

    def test_rate_limit(self):
        codes = [call(self.port, "GET", "/search?q=mango", key=self.key)[0] for _ in range(12)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 200)

    def test_document_and_errors(self):
        st, body = call(self.port, "GET", "/document?url=https://f.example/mango", key=self.admin)
        self.assertEqual(st, 200)
        self.assertIn("tropical", body["text"])
        st, _ = call(self.port, "GET", "/document?id=999999", key=self.admin)
        self.assertEqual(st, 404)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/search", body=b"{not json", headers={"Authorization": f"Bearer {self.admin}"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 400)

    def test_feedback_and_metrics(self):
        st, _ = call(self.port, "POST", "/feedback", {"query": "mango", "url": "https://f.example/mango", "grade": 3},
                     key=self.admin)
        self.assertEqual(st, 201)
        st, text = call(self.port, "GET", "/metrics")
        self.assertIn("ownsearch_requests_total", text)

    def test_concurrent_agents(self):
        errors = []

        def agent():
            for _ in range(5):
                st, _ = call(self.port, "GET", "/search?q=mango+sun", key=self.admin)
                if st != 200:
                    errors.append(st)
        threads = [threading.Thread(target=agent) for _ in range(7)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class GatewayTests(unittest.TestCase):
    def test_gateway_balances_and_fails_over(self):
        e, tmp = make_engine()
        e.add_document("Guava", "guava fruit", "https://f.example/guava")
        keys = KeyStore(e.settings.keys_path)
        key = keys.create("gw-agent", scopes=["search"])
        nodes = []
        for _ in range(2):
            h = make_handler(e, keys, RateLimiter(), Metrics(), None, False, "node")
            nodes.append(start(h))
        dead = "http://127.0.0.1:9"          # nothing listens here
        gw = Gateway([f"http://127.0.0.1:{p}" for _, p in nodes] + [dead], e.settings.keys_path, require_auth=True)
        time.sleep(0.3)
        srv, port = start(gw.handler())
        try:
            self.assertEqual(call(port, "GET", "/search?q=guava")[0], 401)
            for _ in range(6):
                st, body = call(port, "GET", "/search?q=guava", key=key)
                self.assertEqual(st, 200)
                self.assertEqual(body["results"][0]["title"], "Guava")
            st, info = call(port, "GET", "/gateway")
            self.assertEqual(st, 200)
        finally:
            srv.shutdown()
            srv.server_close()
            gw.stop.set()
            for s, _ in nodes:
                s.shutdown()
                s.server_close()


if __name__ == "__main__":
    unittest.main()
