"""Offline regressions for entity discovery, source dates, answers and cache boundaries."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ownsearch.cli import _pretty
from ownsearch.discover import NewsFeedProvider, OfficialSiteProvider, candidate_urls, discover, feed_urls
from ownsearch.evaluation import _keys_for, _match, evaluate
from ownsearch.fetcher import FetchResult
from ownsearch.knowledge import Entity, Knowledge
from ownsearch.market import Market, analyse
from ownsearch.pipeline import Processor
from ownsearch.query import parse_query
from ownsearch.robots import RobotsPolicy
from tests.helpers import make_engine, test_settings


def response(url, body, ct="text/html"):
    return FetchResult(url, url, 200, {"content-type":ct}, body.encode())


class FakePages:
    def __init__(self, pages):
        self.pages = pages
        self.deadline = time.monotonic() + 30
        self.requests = 0

    def fetch(self, url, **kwargs):
        self.requests += 1
        return self.pages[url]

    def policy(self, url):
        return RobotsPolicy.allow_all()


class RelevanceTests(unittest.TestCase):
    def test_subjects_and_intents_are_learned_without_topic_examples(self):
        cases = [("Nvidia live price", "financial", ["Nvidia"]),
                 ("today's Trump headlines", "news", ["Trump"]),
                 ("Samrat Ashok birthplace", "reference", ["Samrat", "Ashok"]),
                 ("TCS 6-month analysis", "financial", ["TCS"]),
                 ("Claude docs on MCP", "tech_docs", ["Claude", "MCP"]),
                 ("UnseenCorp live price", "financial", ["UnseenCorp"])]
        for text, intent, subject in cases:
            with self.subTest(text=text):
                q = parse_query(text)
                self.assertEqual(q.intent, intent)
                self.assertEqual(q.entity, subject)
        self.assertEqual(parse_query("TCS 6-month analysis").intent_details["days"], 183)
        self.assertEqual(parse_query("today's Trump headlines").freshness, "day")
        self.assertIn("Python", parse_query("Python requests documentation").entity)

    def test_no_guessed_company_domains_or_wikipedia_titles(self):
        self.assertEqual(candidate_urls("UnknownBrand official site"), [])
        self.assertEqual(candidate_urls("Who is UnseenPerson"), [])

    def test_official_site_walk_selects_focus_from_sitemap_and_anchors(self):
        engine, _ = make_engine()
        q = parse_query("Nebula timeout documentation")
        q.entities = [Entity("Q1", "Nebula", urls=["https://nebula.example/"])]
        pages = FakePages({
            "https://nebula.example/": response("https://nebula.example/", '<html><title>Nebula</title><body><a href="/timeouts">Nebula timeout guide</a><a href="https://spam.example/">Nebula timeout</a></body></html>'),
            "https://nebula.example/sitemap.xml": response("https://nebula.example/sitemap.xml", '<urlset><url><loc>https://nebula.example/timeout-reference</loc></url><url><loc>https://nebula.example/unrelated</loc></url></urlset>', "application/xml")})
        items, errors = OfficialSiteProvider().discover(q.raw, q, engine.settings, client=pages)
        self.assertFalse(errors)
        urls = [i.url for i in items]
        self.assertIn("https://nebula.example/timeouts", urls)
        self.assertIn("https://nebula.example/timeout-reference", urls)
        self.assertNotIn("https://spam.example/", urls)
        self.assertLess(urls.index("https://nebula.example/timeouts"), urls.index("https://nebula.example/"))

    def test_feed_entries_require_subject_and_verified_dates(self):
        engine, _ = make_engine(news_feeds="https://feeds.example/rss")
        q = parse_query("today's Orion headlines")
        now = datetime.now(timezone.utc).isoformat()
        rss = f'<rss><channel><item><title>Orion announcement</title><link>https://news.example/orion</link><pubDate>{now}</pubDate></item><item><title>Headlines about something else</title><link>https://news.example/other</link><pubDate>{now}</pubDate></item><item><title>Orion undated</title><link>https://news.example/undated</link></item></channel></rss>'
        items, errors = NewsFeedProvider().discover(q.raw, q, engine.settings, client=FakePages({"https://feeds.example/rss":response("https://feeds.example/rss",rss,"application/rss+xml")}))
        self.assertFalse(errors)
        self.assertEqual([i.url for i in items], ["https://news.example/orion"])

    def test_feed_publication_date_is_persisted_before_indexing(self):
        engine, _ = make_engine()
        now = datetime.now(timezone.utc).isoformat()
        out = Processor(engine.settings, engine.store).process("https://news.example/orion", "https://news.example/orion",200,{"content-type":"text/html"},b'<html><title>Orion announces launch</title><body><p>Orion announces a new mission to orbit.</p></body></html>',published_at=now,publication_source="news_feeds")
        doc = engine.store.get(out["doc_id"])
        self.assertIsNotNone(doc["published_at"])
        self.assertEqual(doc["metadata"]["publication_source"], "news_feeds")
        engine.rebuild_index()
        self.assertTrue(engine.search("Orion news today",freshness="day")["results"])

    def test_linked_aliases_match_and_unrelated_common_words_are_filtered(self):
        engine, _ = make_engine(knowledge_enabled=True)
        engine.add_document("Alt Orion protocol", "Alt Orion is a protocol for messaging.", "https://docs.example/protocol")
        engine.add_document("Messaging in Otherworld", "Otherworld discusses protocols and Orionis constellations.", "https://other.example/protocol")
        ent = Entity("Q1", "Orion", aliases=["Alt Orion"], span="ORX")
        with patch.object(Knowledge,"link",return_value=[ent]), patch("ownsearch.discover.discover",return_value=[]):
            r = engine.search("ORX protocol docs",live=True,use_cache=False)
        self.assertEqual([x["url"] for x in r["results"]], ["https://docs.example/protocol"])

    def test_live_cache_is_separate_and_direct_answer_prints_source(self):
        engine, _ = make_engine(market_lookup_url="https://lookup.example/{q}",market_chart_url="https://chart.example/{symbol}")
        local = engine.search("UnseenCorp live price")
        self.assertIsNone(local["answer"])
        answer = {"type":"stock_quote","text":"UnseenCorp: 123 USD","as_of":datetime.now(timezone.utc).isoformat(),"source":{"name":"Fixture source","url":"https://quote.example/UC"}}
        with patch.object(Market,"quote",return_value=answer) as quote:
            live = engine.search("UnseenCorp live price",live=True)
            cached = engine.search("UnseenCorp live price",live=True)
        self.assertEqual(quote.call_count,1)
        self.assertEqual(live["answer"],answer)
        self.assertTrue(cached["cached"])
        self.assertFalse(live["coverage"]["low_confidence"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out): _pretty(live)
        self.assertIn("123 USD",out.getvalue())
        self.assertIn("https://quote.example/UC",out.getvalue())

    def test_repeat_discovery_failure_is_cached(self):
        engine, _ = make_engine()
        with patch("ownsearch.discover.discover",return_value=[]) as fn:
            engine.search("unseenzq",live=True,use_cache=False)
            engine.search("unseenzq",live=True,use_cache=False)
        self.assertEqual(fn.call_count,1)

    def test_custom_feed_file_and_disabled_test_services(self):
        engine, _ = make_engine()
        self.assertFalse(engine.settings.knowledge_enabled)
        self.assertFalse(Market(engine.settings).enabled)
        self.assertEqual(feed_urls(engine.settings),[])
        p = engine.root / "feeds.txt"
        p.write_text("# sources\nhttps://example.org/rss\nhttps://example.org/rss\n")
        engine.settings.news_feeds_file=str(p)
        self.assertEqual(feed_urls(engine.settings),["https://example.org/rss"])

    def test_versioned_operator_cases(self):
        engine, _ = make_engine()
        fixture = Path(__file__).with_name("fixtures") / "relevance_corpus.json"
        for doc in json.loads(fixture.read_text())["documents"]: engine.store.upsert(**doc)
        engine.rebuild_index()
        for line in Path(__file__).with_name("search_cases.jsonl").read_text().splitlines():
            case=json.loads(line)
            with self.subTest(query=case["query"]):
                r=engine.search(case["query"],limit=50,use_cache=False)
                urls={x["url"] for x in r["results"]}
                if "expected_urls" in case: self.assertEqual(urls,set(case["expected_urls"]))
                self.assertFalse(urls & set(case.get("forbidden_urls",[])))
                self.assertGreaterEqual(len(urls),case.get("min_results",0))

    def test_host_judgments_count_each_host_once(self):
        results=[{"url":"https://www.example.org/a","id":1},{"url":"https://example.org/b","id":2},{"url":"https://wrong.org/a","id":3}]
        self.assertEqual(_match(_keys_for(results),{"host:example.org":3}),["host:example.org","host:wrong.org"])

    def test_known_history_statistics(self):
        a=analyse([(0,100),(86400,120),(172800,90),(259200,110)])
        self.assertAlmostEqual(a["change_pct"],10)
        self.assertAlmostEqual(a["max_drawdown_pct"],-25)
        self.assertEqual(a["high"],(86400,120))

    def test_context_disambiguates_person_from_a_token_with_same_name(self):
        engine, _ = make_engine()
        k = Knowledge(engine.settings)
        records = {
            "Q1": {"labels":{"en":{"value":"Orion Smith"}},"aliases":{"en":[]},"descriptions":{"en":{"value":"public official"}},"sitelinks":{"enwiki":{"title":"Orion Smith"}}},
            "Q2": {"labels":{"en":{"value":"$Orion"}},"aliases":{"en":[]},"descriptions":{"en":{"value":"cryptocurrency token"}},"sitelinks":{"enwiki":{"title":"$Orion"}}}}
        def wiki(text):
            return [("Orion Smith","Q1")] if "headlines" in text else [("$Orion","Q2"),("Orion Smith","Q1")]
        with patch.object(k,"_wd_search",return_value=[]), patch.object(k,"_wp_search",side_effect=wiki), patch.object(k,"entities",return_value=records):
            linked=k.link(["Orion"],["headlines"],load_claims=False,load_urls=False)
        self.assertEqual([e.qid for e in linked],["Q1"])

    def test_inflection_variant_is_not_hidden_by_an_ambiguous_exact_label(self):
        engine, _ = make_engine()
        k=Knowledge(engine.settings)
        records={"Q1":{"labels":{"en":{"value":"Object framework"}},"aliases":{"en":[{"value":"OOP"}]},"descriptions":{"en":{"value":"supports inheritance"}},"sitelinks":{"enwiki":{"title":"Object framework"}}}}
        def wiki(text): return [("Object framework","Q1")] if "oop" in text.lower().split() else []
        with patch.object(k,"_wd_search",return_value=[]),patch.object(k,"_wp_search",side_effect=wiki),patch.object(k,"entities",return_value=records):
            linked=k.link(["inheritance","OOPS"],load_claims=False,load_urls=False)
        self.assertEqual([e.qid for e in linked],["Q1"])

    def test_unavailable_fact_does_not_become_a_description_card(self):
        engine, _ = make_engine(knowledge_enabled=True)
        entity=Entity("Q1","Orion Smith",span="Orion Smith")
        with patch.object(Knowledge,"link",return_value=[entity]),patch.object(Knowledge,"card") as card,patch("ownsearch.discover.discover",return_value=[]):
            result=engine.search("Orion Smith birthplace",live=True,use_cache=False)
        self.assertIsNone(result["answer"])
        card.assert_not_called()
        self.assertTrue(result["coverage"]["low_confidence"])

    def test_feed_headline_survives_article_fetch_failure(self):
        from ownsearch.discover import CandidateItem
        from ownsearch.fetcher import FetchError
        engine, _=make_engine()
        now=datetime.now(timezone.utc).isoformat()
        item=CandidateItem("https://news.example/orion","news_feeds","Orion mission announced","Orion launches a new mission.",now,"https://feeds.example/rss")
        with patch("ownsearch.discover.gather_candidates",return_value=([item],[])),patch("ownsearch.live.PageClient.fetch",side_effect=FetchError("Timed out","timeout")):
            discover(engine,"Orion news today")
        doc=engine.store.get_by_url(item.url)
        self.assertEqual(doc["source_type"],"news_feed")
        self.assertEqual(doc["metadata"]["feed_url"],item.source_url)
        result=engine.search("Orion news today")
        self.assertEqual([r["url"] for r in result["results"]],[item.url])
        self.assertFalse(result["coverage"]["low_confidence"])

    def test_relative_cutoff_removes_weak_results(self):
        engine, _=make_engine(relevance_score_ratio=0.95)
        engine.add_document("Orion protocol guide","Orion protocol describes secure message exchange.","https://docs.example/orion")
        engine.add_document("Random topics","A discussion of cooking and travel with one reference to Orion.","https://other.example/topics")
        result=engine.search("Orion protocol",use_cache=False)
        self.assertEqual([r["url"] for r in result["results"]],["https://docs.example/orion"])

    def test_direct_answer_obeys_source_filters(self):
        engine, _=make_engine(market_lookup_url="https://lookup.example/{q}",market_chart_url="https://chart.example/{symbol}")
        answer={"type":"stock_quote","text":"Orion 100 USD","as_of":datetime.now(timezone.utc).isoformat(),"source":{"url":"https://finance.example/OR"}}
        with patch.object(Market,"quote",return_value=answer),patch("ownsearch.discover.discover",return_value=[]):
            result=engine.search("Orion live price site:docs.example",live=True,use_cache=False)
        self.assertIsNone(result["answer"])
        self.assertTrue(result["coverage"]["low_confidence"])

    def test_preferred_claim_wins_over_normal_and_deprecated_claims(self):
        engine, _=make_engine()
        def claim(rank,text):return {"rank":rank,"mainsnak":{"datavalue":{"value":text}}}
        values=Knowledge(engine.settings)._values([claim("normal","Old value"),claim("preferred","Current value"),claim("deprecated","Wrong value")])
        self.assertEqual(values,[{"text":"Current value"}])

    def test_searxng_forwards_supported_filters_and_preserves_upstream_errors(self):
        from ownsearch.discover import SearXNGProvider
        from urllib.parse import parse_qs,urlparse
        engine, _=make_engine(searxng_url="https://searx.example")
        q=parse_query("Orion headlines",freshness="week",lang="hi")
        payload={"results":[],"unresponsive_engines":[["provider-a","timeout"]]}
        with patch("ownsearch.live.PageClient.raw",return_value=response("https://searx.example",json.dumps(payload),"application/json")) as raw:
            items,errors=SearXNGProvider().discover(q.raw,q,engine.settings)
        params=parse_qs(urlparse(raw.call_args.args[0]).query)
        self.assertEqual(params["time_range"],["month"])
        self.assertEqual(params["language"],["hi"])
        self.assertEqual(params["categories"],["news"])
        self.assertIn("timeout",errors[0])

    def test_provider_dedup_keeps_publisher_metadata_and_source_list(self):
        from ownsearch.discover import CandidateItem,SearXNGProvider,gather_candidates
        engine, _=make_engine(searxng_url="https://searx.example",news_feeds="https://feed.example/rss")
        now=datetime.now(timezone.utc).isoformat()
        search=CandidateItem("https://news.example/article?utm_source=test","searxng","Search title","Search snippet")
        feed=CandidateItem("https://news.example/article","news_feeds","Publisher title","Publisher summary",now,"https://feed.example/rss")
        with patch.object(SearXNGProvider,"discover",return_value=([search],[])),patch.object(NewsFeedProvider,"discover",return_value=([feed],[])),patch.object(OfficialSiteProvider,"discover",return_value=([],[])):
            items,errors=gather_candidates(engine,"Orion headlines",parse_query("Orion headlines"))
        self.assertFalse(errors)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].sources,["searxng","news_feeds"])
        self.assertEqual(items[0].published_at,now)
        self.assertEqual(items[0].title,"Publisher title")
        self.assertEqual(items[0].snippet,"Publisher summary")

    def test_related_context_names_disambiguate_a_product(self):
        engine, _=make_engine()
        k=Knowledge(engine.settings)
        records={"Q1":{"labels":{"en":{"value":"Nebula"}},"aliases":{"en":[]},"descriptions":{"en":{"value":"software from Acme Labs"}},"sitelinks":{"enwiki":{"title":"Nebula software"}}},
                 "Q2":{"labels":{"en":{"value":"Acme Labs"}},"aliases":{"en":[]},"descriptions":{"en":{"value":"software company"}},"sitelinks":{}},
                 "Q3":{"labels":{"en":{"value":"Nebula"}},"aliases":{"en":[]},"descriptions":{"en":{"value":"town"}},"sitelinks":{}}}
        search=[{"id":"Q1","match":{"type":"label","text":"Nebula"}},{"id":"Q3","match":{"type":"label","text":"Nebula"}}]
        with patch.object(k,"_wd_search",return_value=search),patch.object(k,"_wp_search",return_value=[("Acme Labs","Q2")]),patch.object(k,"entities",return_value=records):
            entities=k.link(["Nebula"],["docs"],load_claims=False,load_urls=False)
        self.assertEqual([e.qid for e in entities],["Q1"])

    def test_missing_or_stale_market_timestamp_cannot_be_a_quote(self):
        engine, _=make_engine(market_lookup_url="https://lookup.example/{q}",market_chart_url="https://chart.example/{symbol}")
        market=Market(engine.settings)
        for stamp in [None,time.time()-8*86400]:
            with self.subTest(stamp=stamp),patch.object(market,"resolve",return_value=("OR","Orion")),patch.object(market,"_chart",return_value={"meta":{"regularMarketPrice":100,"regularMarketTime":stamp}}):
                self.assertIsNone(market.quote(["Orion"]))

    def test_history_labels_adjustments_and_incomplete_session(self):
        engine, _=make_engine()
        market=Market(engine.settings)
        now=int(time.time())
        data={"meta":{"currency":"USD","regularMarketTime":now,"currentTradingPeriod":{"regular":{"end":now+3600}}},
              "timestamp":[now-i*86400 for i in range(5,-1,-1)],"indicators":{"adjclose":[{"adjclose":[100,101,102,103,104,105]}],"quote":[{"close":[110,111,112,113,114,115]}]}}
        with patch.object(market,"resolve",return_value=("OR","Orion")),patch.object(market,"_chart",return_value=data) as chart:
            answer=market.history(["Orion"],183)
        self.assertEqual(answer["price_basis"],"adjusted close")
        self.assertAlmostEqual(answer["analysis"]["change_pct"],5)
        self.assertTrue(answer["incomplete_last_session"])
        self.assertIn("provisional",answer["text"])
        self.assertEqual(chart.call_args.kwargs["interval"],"1d")

    def test_quote_change_uses_previous_session_not_window_baseline(self):
        engine, _=make_engine()
        market=Market(engine.settings)
        now=int(time.time())
        quote={"meta":{"regularMarketPrice":120,"regularMarketTime":now,"chartPreviousClose":90,"currency":"USD"}}
        daily={"timestamp":[now-2*86400,now-86400,now],"indicators":{"quote":[{"close":[90,100,120]}]}}
        with patch.object(market,"resolve",return_value=("OR","Orion")),patch.object(market,"_chart",side_effect=[quote,daily]):
            answer=market.quote(["Orion"])
        self.assertEqual(answer["previous_close"],100)
        self.assertEqual(answer["change_pct"],20)
        self.assertEqual(answer["scope"],"regular_market")

    def test_discovery_request_budget_counts_redirect_hops(self):
        from ownsearch.live import PageClient
        from ownsearch.fetcher import FetchError
        engine, _=make_engine(discovery_max_requests=1)
        client=PageClient(engine.settings,time.monotonic()+10)
        with patch.object(client.fetcher,"_request_once",return_value=(302,{"location":"https://next.example/page"},b"",False)) as request:
            with self.assertRaises(FetchError):client.raw("https://first.example/page")
        self.assertEqual(client.requests,1)
        self.assertEqual(request.call_count,1)

    def test_focused_docs_beat_overview_with_incidental_protocol_mention(self):
        engine, _=make_engine(knowledge_enabled=True)
        engine.add_document("Nebula documentation overview","Nebula documentation covers writing, reasoning, language and productivity. "*20+" ORX support is also available.","https://brand.example/overview")
        engine.add_document("Connect local ORX servers","Nebula connects to ORX using a local server. Configure Nebula with ORX permissions and restart Nebula. ORX clients can access tools through Nebula with approval.","https://protocol.example/connect")
        entities=[Entity("Q1","Nebula",span="Nebula"),Entity("Q2","ORX",span="ORX")]
        with patch.object(Knowledge,"link",return_value=entities),patch("ownsearch.discover.discover",return_value=[]):
            result=engine.search("Nebula docs on ORX",live=True,use_cache=False)
        self.assertEqual(result["results"][0]["url"],"https://protocol.example/connect")


if __name__ == "__main__": unittest.main()
