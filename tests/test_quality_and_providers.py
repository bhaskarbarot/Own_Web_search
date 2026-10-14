"""Tests for Phase 2-9: Query intent detection, provider discovery, news, financial data,
freshness validation, failure handling, timeouts, and ranking improvements.
"""
import http.server
import json
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from ownsearch.config import Settings
from ownsearch.discover import (
    CandidateItem,
    NewsFeedProvider,
    SearXNGProvider,
    WikipediaProvider,
    candidate_urls,
    discover,
    gather_candidates,
)
from ownsearch.engine import SearchEngine
from ownsearch.knowledge import Entity
from ownsearch.query import parse_query

from tests.helpers import make_engine, test_settings


def iso_date(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


class MockServer(http.server.ThreadingHTTPServer):
    def __init__(self, handler_cls):
        super().__init__(("127.0.0.1", 0), handler_cls)
        self.daemon_threads = True
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.shutdown()
        self.server_close()


class QualityAndProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an engine with sample documents
        e, tmp = make_engine()
        up = e.store.upsert
        # Official documentation
        up("https://docs.python.org/3/library/requests.html", "Requests: HTTP for Humans",
           "Requests is an elegant and simple HTTP library for Python, built for human beings. "
           "Official documentation and tutorials for requests.", published_at=iso_date(30))
        # Random blog mentioning requests and python
        up("https://blog.example.org/random-stuff", "Random Thoughts on Coding",
           "Today I cooked dinner and then made a request to python friends about movie recommendations.",
           published_at=iso_date(5))
        # Reference article about Nvidia
        up("https://en.wikipedia.org/wiki/Nvidia", "Nvidia - Wikipedia",
           "Nvidia Corporation is an American multinational corporation and technology company. "
           "Nvidia designs graphics processing units and APIs.", published_at=iso_date(200))
        # Planet Python mentioning stock simulation and Nvidia in disparate sections
        up("https://planetpython.org/", "Planet Python",
           "Section A: Monte Carlo retirement simulations and company stock offering prices. "
           + ("filler text " * 120) +
           "Section B: CalVer versioning used by Apple, Nvidia and others for software releases.",
           published_at=iso_date(1))
        # Real news article with verified recent date
        up("https://news.example.com/modi-summit-2026", "Narendra Modi addresses global green energy summit",
           "Prime Minister Narendra Modi today addressed the global green energy summit in New Delhi. "
           "Modi outlined India's targets for renewable infrastructure.", published_at=iso_date(0.5))
        # Old historical article about Modi
        up("https://history.example.com/modi-early-years", "Narendra Modi: An early biography",
           "A look back at Narendra Modi early political career in Gujarat.", published_at=iso_date(1500))
        # Genuine financial overview document for Nvidia
        up("https://finance.example.com/nvda", "Nvidia Stock Quote and Market Overview",
           "Nvidia stock price today, trading volume, valuation metrics and market cap for Nvidia.",
           published_at=iso_date(1))
        # Document with NO published_at (only discovered_at will be set)
        up("https://undated.example.com/page", "Undated Web Page",
           "This is a general page crawled today with no publication date metadata.")

        e.rebuild_index()
        cls.e = e

    # A. Current news query tests
    def test_news_query_intent_and_wikipedia_avoidance(self):
        q = parse_query("Narendra modi news today")
        self.assertEqual(q.intent, "news")
        self.assertTrue(q.fresh_intent)
        self.assertEqual(q.intent_details.get("topic"), "narendra modi")

        # WikipediaProvider MUST NOT return candidates for news intent
        prov = WikipediaProvider()
        cands, errs = prov.discover("Narendra modi news today", q, self.e.settings)
        self.assertEqual(cands, [], "Wikipedia should not be used as discovery target for news queries")

        # In search results, verified recent news article should rank above Wikipedia
        res = self.e.search("Narendra modi news today", 5, False)
        self.assertTrue(res["results"])
        top_result = res["results"][0]
        self.assertEqual(top_result["url"], "https://news.example.com/modi-summit-2026")
        self.assertEqual(top_result["date_source"], "published")

    # B. Financial query tests
    def test_financial_query_intent_and_honest_message(self):
        q = parse_query("Nvidia current stock price")
        self.assertEqual(q.intent, "financial")
        self.assertTrue(q.intent_details.get("wants_live_quote"))

        res = self.e.search("Nvidia current stock price", 5, False)
        # Without a financial provider, coverage must flag low confidence and explain live quote limitation
        cov = res["coverage"]
        self.assertTrue(cov["low_confidence"])
        self.assertIn("financial", cov["intent"])
        self.assertIn("financial provider", cov["message"].lower())

        # Genuine finance document ranks above Planet Python
        if res["results"]:
            first_url = res["results"][0]["url"]
            self.assertEqual(first_url, "https://finance.example.com/nvda")
            self.assertNotEqual(first_url, "https://planetpython.org/")

    # C. Reference query tests
    def test_reference_query_allows_wikipedia(self):
        q = parse_query("What is Nvidia?")
        self.assertEqual(q.intent, "reference")

        prov = WikipediaProvider()
        q.entities = [Entity("Q182477", "Nvidia", wiki_title="Nvidia")]
        cands, _ = prov.discover("What is Nvidia?", q, self.e.settings)
        self.assertTrue(any("wikipedia.org/wiki/Nvidia" in c.url for c in cands))

        res = self.e.search("What is Nvidia?", 5, False)
        self.assertTrue(res["results"])
        self.assertIn("Nvidia", res["results"][0]["title"])

    # D. Technical documentation query tests
    def test_tech_docs_ranking(self):
        q = parse_query("Python requests documentation")
        self.assertEqual(q.intent, "tech_docs")

        res = self.e.search("Python requests documentation", 5, False)
        self.assertTrue(res["results"])
        self.assertEqual(res["results"][0]["url"], "https://docs.python.org/3/library/requests.html")

    # E. Partial-match query handling
    def test_partial_match_query(self):
        res = self.e.search("Narendra quantum robotics", 5, False)
        cov = res["coverage"]
        # Partial match should report mode and low_confidence
        self.assertIn(cov["mode"], ("partial_terms", "all_terms+partial"))
        self.assertTrue(cov["low_confidence"])

    # F. Freshness vs Crawl date
    def test_freshness_filter_rejects_discovered_crawl_date(self):
        # The undated page was crawled today, but has no published date
        res = self.e.search("undated web page", 5, freshness="day")
        # Should NOT match because date_source is "discovered" (crawl date), not verified publication
        matching_urls = [r["url"] for r in res["results"]]
        self.assertNotIn("https://undated.example.com/page", matching_urls)

    # G. Provider failure graceful degradation
    def test_provider_failure_graceful_degradation(self):
        # Configure an unreachable SearXNG endpoint
        settings = test_settings(self.e.settings.data_dir,
                                 searxng_url="http://127.0.0.1:59999",
                                 discovery_timeout=1.0)
        e = SearchEngine(settings=settings)
        # Query for something not in the index to trigger live discovery
        res = e.search("Novel unindexed robotics topic 999", 5, False, live=True)

        # Local search must still succeed without crashing
        self.assertTrue(res["providers_configured"]["searxng"])
        self.assertTrue(len(res["provider_errors"]) > 0 or any("failed" in str(err).lower() for err in res["provider_errors"]))

    # H. Provider timeout bounded behavior
    def test_provider_timeout_bounded(self):
        # Mock server that sleeps longer than discovery timeout
        class HangingHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(1.2)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"results": []}')
                except Exception:
                    pass

            def log_message(self, *args):
                pass

        server = MockServer(HangingHandler)
        try:
            port = server.server_address[1]
            settings = test_settings(self.e.settings.data_dir,
                                     searxng_url=f"http://127.0.0.1:{port}",
                                     searxng_timeout=0.5,
                                     discovery_timeout=0.6)
            e = SearchEngine(settings=settings)
            t0 = time.perf_counter()
            res = e.search("Some novel query with hanging provider", 5, False, live=True)
            elapsed = time.perf_counter() - t0
            # Must finish well under 3 seconds despite hanging provider
            self.assertLess(elapsed, 2.5)
            self.assertIn("provider_errors", res)
        finally:
            server.stop()

    # I. Candidate deduplication
    def test_candidate_deduplication(self):
        q = parse_query("What is Nvidia?")
        cands, _ = gather_candidates(self.e, "What is Nvidia?", q, max_urls=10)
        urls = [c.url for c in cands]
        self.assertEqual(len(urls), len(set(urls)), "Candidate URLs must be unique")

    # J. News Feed discovery provider with local mock RSS
    def test_news_feed_discovery(self):
        class FeedHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                rss = f"""<?xml version="1.0" encoding="UTF-8"?>
                <rss version="2.0">
                  <channel>
                    <title>Mock Tech News</title>
                    <link>http://127.0.0.1</link>
                    <item>
                      <title>Narendra Modi launches AI initiative today</title>
                      <link>https://technews.example.org/modi-ai-2026</link>
                      <description>New national AI initiative announced.</description>
                      <pubDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
                    </item>
                  </channel>
                </rss>"""
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                self.wfile.write(rss.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = MockServer(FeedHandler)
        try:
            feed_url = f"http://127.0.0.1:{server.server_address[1]}/rss.xml"
            settings = test_settings(self.e.settings.data_dir, news_feeds=feed_url)
            prov = NewsFeedProvider()
            q = parse_query("Modi AI initiative today")
            cands, errs = prov.discover("Modi AI initiative today", q, settings)
            self.assertEqual(errs, [])
            self.assertTrue(len(cands) >= 1)
            self.assertIn("modi-ai-2026", cands[0].url)
            self.assertIsNotNone(cands[0].published_at)
        finally:
            server.stop()

    # K. SearXNG discovery provider with local mock SearXNG JSON API
    def test_searxng_discovery(self):
        class SearxHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data = {
                    "results": [
                        {
                            "url": "https://searx-result.example.org/article1",
                            "title": "Article 1",
                            "content": "Relevant content snippet",
                            "publishedDate": iso_date(1),
                        }
                    ]
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))

            def log_message(self, *args):
                pass

        server = MockServer(SearxHandler)
        try:
            searx_url = f"http://127.0.0.1:{server.server_address[1]}"
            settings = test_settings(self.e.settings.data_dir, searxng_url=searx_url)
            prov = SearXNGProvider()
            q = parse_query("Latest semiconductor developments")
            cands, errs = prov.discover("Latest semiconductor developments", q, settings)
            self.assertEqual(errs, [])
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0].url, "https://searx-result.example.org/article1")
            self.assertEqual(cands[0].provider, "searxng")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
