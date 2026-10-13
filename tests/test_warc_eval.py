import gzip
import io
import json
import os
import tempfile
import unittest

from ownsearch.evaluation import evaluate, load_qrels, ndcg, recall, train
from ownsearch.warc import import_warc, parse_http_response

from tests.helpers import make_engine


def warc_record(url, html, date="2025-05-01T00:00:00Z"):
    http = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html)
    head = (f"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: {url}\r\nWARC-Date: {date}\r\n"
            f"Content-Type: application/http; msgtype=response\r\nContent-Length: {len(http)}\r\n\r\n").encode()
    return gzip.compress(head + http + b"\r\n\r\n")


class WarcTests(unittest.TestCase):
    def test_import_warc(self):
        e, tmp = make_engine()
        path = os.path.join(tmp, "test.warc.gz")
        with open(path, "wb") as f:
            for i in range(3):
                f.write(warc_record(f"https://archive.example/{i}",
                                    f"<html><head><title>Archived {i}</title></head><body><p>archived pomelo {i}</p></body></html>".encode()))
        stats = import_warc(path, e)
        self.assertEqual(stats["indexed"], 3)
        self.assertEqual(len(e.search("pomelo", 10)["results"]), 3)

    def test_chunked_http(self):
        raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        st, h, body = parse_http_response(raw)
        self.assertEqual((st, body), (200, b"hello world"))


class EvalTests(unittest.TestCase):
    def test_metrics(self):
        j = {"a": 3, "b": 1, "c": 0}
        self.assertAlmostEqual(ndcg(["a", "b", "c"], j), 1.0)
        self.assertLess(ndcg(["c", "b", "a"], j), 1.0)
        self.assertEqual(recall(["x", "a"], j, 100), 0.5)

    def test_evaluate_and_train(self):
        e, tmp = make_engine()
        e.add_document("Lychee guide", "lychee fruit growing guide lychee", "https://f.example/lychee")
        e.add_document("Fruit list", "many fruit names including lychee and more fruit", "https://f.example/list")
        qrels_path = os.path.join(tmp, "q.json")
        with open(qrels_path, "w") as f:
            json.dump({"queries": [{"query": "lychee", "judgments": {"https://f.example/lychee": 3}}]}, f)
        qrels = load_qrels(qrels_path)
        res = evaluate(e, qrels)
        self.assertEqual(res["summary"]["ndcg@10"], 1.0)
        t = train(e, qrels, rounds=1)
        self.assertGreaterEqual(t["ndcg@10_after"], t["ndcg@10_before"])


if __name__ == "__main__":
    unittest.main()
