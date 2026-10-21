"""Unit tests for background batch crawler and sitemap parser."""
import unittest
from unittest.mock import MagicMock, patch
from ownsearch.crawler import parse_sitemap_urls, BackgroundCrawler, CrawlStats
from ownsearch.config import Settings
from ownsearch.persistent_cache import PersistentPageCache
from ownsearch.webmodels import WebCandidate

class TestCrawler(unittest.TestCase):
    def test_parse_sitemap_urls_valid(self):
        sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/page1</loc>
                <lastmod>2026-01-01</lastmod>
            </url>
            <url>
                <loc>https://example.com/page2</loc>
            </url>
        </urlset>"""
        urls = parse_sitemap_urls(sitemap_xml, "https://example.com/")
        self.assertEqual(urls, ["https://example.com/page1", "https://example.com/page2"])

    def test_parse_sitemap_rejects_doctype(self):
        xml_with_entity = b"""<!DOCTYPE sitemap [<!ENTITY test SYSTEM "file:///etc/passwd">]>
        <urlset><url><loc>&test;</loc></url></urlset>"""
        urls = parse_sitemap_urls(xml_with_entity, "https://example.com/")
        self.assertEqual(urls, [])

    def test_crawler_ingests_mock_pages(self):
        settings = Settings(data_dir=None, persistent_cache_enabled=False)
        cache = MagicMock()

        mock_item = WebCandidate(
            title="React useEffect",
            url="https://react.dev/reference/react/useEffect",
            content="useEffect cleanup runs when component unmounts",
        )
        mock_page = MagicMock()
        mock_page.url = "https://react.dev/reference/react/useEffect"
        mock_page.item = mock_item
        mock_page.links = [("https://react.dev/reference/react/useState", "useState", "page")]

        crawler = BackgroundCrawler(settings=settings, cache=cache, max_workers=1)

        with patch("ownsearch.crawler.WebFetchSession") as MockWebFetch:
            instance = MockWebFetch.return_value
            instance.crawl.return_value = mock_page

            stats = crawler.crawl_seeds(
                seeds=["https://react.dev/reference/react/useEffect"],
                max_pages=1,
                max_depth=0,
            )
            self.assertEqual(stats.pages_indexed, 1)
            cache.put.assert_called_once()
            call_url = cache.put.call_args[0][0]
            self.assertEqual(call_url, "https://react.dev/reference/react/useEffect")


if __name__ == "__main__":
    unittest.main()
