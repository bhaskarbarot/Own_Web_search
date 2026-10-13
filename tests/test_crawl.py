"""Phase 1 + 2 success criteria: crawl 100+ pages correctly, readable text, no duplicates, restartable frontier."""
import unittest

from ownsearch.crawler import Crawler
from ownsearch.frontier import Frontier

from tests.helpers import TestSite, make_engine


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = TestSite(120)
        cls.engine, cls.tmp = make_engine()
        cls.frontier = Frontier(cls.engine.settings)
        cls.frontier.add_seeds([cls.site.base + "/"], scope="host")
        cls.crawler = Crawler(cls.engine.settings, cls.engine.store, cls.frontier, index=cls.engine.index)
        cls.stats = cls.crawler.run(max_pages=400, threads=4, idle_wait=2)
        # the flaky page is retried later; force it due now and finish the crawl
        cls.frontier.recrawl_now(cls.site.base + "/flaky")
        cls.frontier.db.execute("UPDATE urls SET next_fetch_at=0 WHERE url LIKE '%/flaky'")
        cls.frontier.db.execute("UPDATE hosts SET backoff_until=0, next_due_at=0")
        cls.stats2 = cls.crawler.run(max_pages=5, threads=1, idle_wait=2)

    @classmethod
    def tearDownClass(cls):
        cls.site.close()

    def test_crawled_100_plus_pages(self):
        n = self.engine.store.db.one("SELECT COUNT(*) FROM documents WHERE active=1 AND url LIKE '%/page/%'")[0]
        self.assertGreaterEqual(n, 100)
        self.assertGreaterEqual(self.engine.index.doc_count, 100)

    def test_text_is_readable(self):
        bad = 0
        for d in self.engine.store.all_documents():
            text = d["text"]
            if text and sum(1 for ch in text if ord(ch) < 9 or ch == "�") / len(text) > 0.01:
                bad += 1
        self.assertEqual(bad, 0)
        doc = self.engine.store.get_by_url(self.site.base + "/page/10")      # served gzip-encoded
        self.assertIn("zq10x", doc["text"])
        self.assertEqual(doc["title"], "Page 10 title")

    def test_binary_and_unsupported_encoding_not_indexed(self):
        self.assertIsNone(self.engine.store.get_by_url(self.site.base + "/binary.html"))
        self.assertIsNone(self.engine.store.get_by_url(self.site.base + "/brotli"))
        row = self.frontier.db.one("SELECT status, last_error FROM urls WHERE url LIKE '%/brotli'")
        self.assertEqual(row["status"], "failed")
        self.assertIn("encoding", row["last_error"])

    def test_robots_respected(self):
        self.assertNotIn("/private/secret", self.site.hits)
        row = self.frontier.db.one("SELECT status FROM urls WHERE url LIKE '%/private/secret'")
        self.assertEqual(row["status"], "disallowed")

    def test_no_duplicate_results(self):
        res = self.engine.search("Duplicate page", 10)
        urls = [r["url"] for r in res["results"] if r["title"] == "Duplicate page"]
        self.assertEqual(len(urls), 1)
        res = self.engine.search("zq3x", 10)                 # /page/3 also linked with ?utm_source=
        self.assertEqual(len(res["results"]), 1)
        res = self.engine.search("zq7x", 10)                 # /print/7 is canonical-duplicate of /page/7
        self.assertEqual(len(res["results"]), 1)
        self.assertTrue(res["results"][0]["url"].endswith("/page/7"))

    def test_redirect_gone_noindex(self):
        row = self.frontier.db.one("SELECT status FROM urls WHERE url LIKE '%/redirect'")
        self.assertEqual(row["status"], "redirected")
        row = self.frontier.db.one("SELECT status FROM urls WHERE url LIKE '%/gone'")
        self.assertEqual(row["status"], "gone")
        self.assertEqual(self.engine.search("nzq", 5)["results"], [])

    def test_retry_after_temporary_failure(self):
        self.assertGreaterEqual(self.site.hits.get("/flaky", 0), 2)
        self.assertIsNotNone(self.engine.store.get_by_url(self.site.base + "/flaky"))

    def test_sitemap_feed_pdf_discovered(self):
        self.assertIn("/sitemap.xml", self.site.hits)
        self.assertIn("/feed.xml", self.site.hits)
        news = self.engine.store.get_by_url(self.site.base + "/news/2")
        self.assertIsNotNone(news)
        self.assertTrue(news["published_at"].startswith("2026-10-02"))
        res = self.engine.search("cardamom", 5)
        self.assertEqual(res["results"][0]["source_type"], "pdf")
        self.assertEqual(res["results"][0]["page"], 2)

    def test_frontier_survives_restart(self):
        f2 = Frontier(self.engine.settings)              # new connection = "restarted process"
        st = f2.stats()
        self.assertGreater(st["urls"], 100)
        self.assertEqual(st["by_status"].get("leased", 0), 0)
        f2.add_seeds([self.site.base + "/page/1"])
        self.assertEqual(f2.stats()["urls"], st["urls"])  # already known: no duplicate queue entries

    def test_recrawl_scheduled_not_immediate(self):
        due = self.frontier.stats()["due_now"]
        self.assertLessEqual(due, 3)


if __name__ == "__main__":
    unittest.main()
