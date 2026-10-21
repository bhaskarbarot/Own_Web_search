"""Unit tests for Common Crawl CDX client and WARC archive resolver."""
import gzip
import io
import json
import unittest
from unittest.mock import MagicMock, patch
from ownsearch.commoncrawl import CDXRecord, query_cdx, fetch_warc_html, get_latest_index

class TestCommonCrawl(unittest.TestCase):
    def test_query_cdx_success(self):
        sample_lines = [
            b'{"url": "https://example.com/test", "timestamp": "20240901", "mime": "text/html", "status": 200, "digest": "abc", "filename": "crawl-data/test.warc.gz", "offset": 100, "length": 500}\n',
            b'{"url": "https://example.com/doc", "timestamp": "20240902", "mime": "text/html", "status": 200, "digest": "def", "filename": "crawl-data/doc.warc.gz", "offset": 600, "length": 800}\n',
        ]
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = iter(sample_lines)
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            records = query_cdx("example.com/*", limit=10)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].url, "https://example.com/test")
            self.assertEqual(records[0].status, 200)
            self.assertEqual(records[0].offset, 100)
            self.assertEqual(records[1].url, "https://example.com/doc")

    def test_query_cdx_handles_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("Network down")):
            records = query_cdx("example.com/*")
            self.assertEqual(records, [])

    def test_fetch_warc_html_success(self):
        warc_header = b"WARC/1.0\r\nWARC-Type: response\r\n\r\n"
        http_header = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
        html_body = b"<html><head><title>Test Page</title></head><body>Hello Common Crawl</body></html>"
        raw_warc = warc_header + http_header + html_body
        compressed = gzip.compress(raw_warc)

        mock_resp = MagicMock()
        mock_resp.read.return_value = compressed
        mock_resp.__enter__.return_value = mock_resp

        record = CDXRecord(
            url="https://example.com/test",
            timestamp="20240901",
            mime="text/html",
            status=200,
            digest="abc",
            filename="crawl-data/test.warc.gz",
            offset=100,
            length=len(compressed),
        )

        with patch("urllib.request.urlopen", return_value=mock_resp):
            html = fetch_warc_html(record)
            self.assertIsNotNone(html)
            self.assertIn("Hello Common Crawl", html)

    def test_get_latest_index(self):
        mock_data = json.dumps([{"id": "CC-MAIN-2025-05-index", "name": "Feb 2025"}]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            idx = get_latest_index()
            self.assertEqual(idx, "CC-MAIN-2025-05-index")


if __name__ == "__main__":
    unittest.main()
