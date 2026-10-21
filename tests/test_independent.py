"""Independent runtime safety, discovery, extraction, filtering and cache regressions."""
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ownsearch.cache import PageCache
from ownsearch.config import Settings
from ownsearch.coordinator import IndependentSearch, Busy
from ownsearch.fetcher import Fetcher, FetchError, decode_content
from ownsearch.query import parse_query
from ownsearch.robots import RobotsPolicy
from ownsearch.webfetch import OriginState, WebFetchSession, CrawledPage
from ownsearch.webmodels import WebCandidate, web_url
from ownsearch.webranking import rank
from tests.independent_fixture import Site, article


def settings(**kw):
    return replace(Settings(sources_file='', allow_private_hosts=True, default_delay=0,
                            fetch_timeout=1, search_timeout_ms=1500, max_pages_per_query=12), **kw)

class IndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.site=Site()
    @classmethod
    def tearDownClass(cls): cls.site.close()
    def engine(self, **kw):return IndependentSearch(settings(**kw))
    def query(self, path='/guide', query='orbital guidance', **kw):
        engine=self.engine(max_pages_per_query=1)
        return engine.search(query,seeds=[self.site.base+path],**kw)

    def test_link_and_nested_sitemap_discovery_with_no_provider(self):
        out=self.engine().search('orbital guidance',seeds=[self.site.base+'/'])
        urls={r['url'] for r in out['results']}
        self.assertIn(self.site.base+'/guide',urls)
        self.assertIn(self.site.base+'/mapped',urls)
        self.assertNotIn(self.site.base+'/other',urls)
        self.assertNotIn('/nofollow',self.site.hits)
        self.assertNotIn('/private/secret',self.site.hits)
        self.assertEqual(out['mode'],'independent')
        self.assertTrue(all(r['fetch_status']=='fetched' for r in out['results']))

    def test_query_qualifier_prioritizes_observed_topic_link_over_versions(self):
        with Site(robots='User-agent: *\nAllow: /') as site:
            site.rows['/navigation']=(200,'text/html',article('Reference directory','Published navigation.').replace(b'</main>',
                b'<a href="/v1/">Orbital version one</a><a href="/v2/">Orbital version two</a><a href="/tutorial/">Tutorial</a></main>'),{})
            site.rows['/tutorial/']=(200,'text/html',article('Orbital tutorial'),{})
            out=self.engine(max_pages_per_query=2).search('orbital tutorial',seeds=[site.base+'/navigation'])
            self.assertIn('/tutorial/',site.hits)
            self.assertNotIn('/v1/',site.hits)
            self.assertIn(site.base+'/tutorial/',{r['url'] for r in out['results']})

    def test_answer_is_exact_fetched_excerpt_with_real_citation(self):
        engine=self.engine();out=engine.search('orbital guidance',seeds=[self.site.base+'/guide'],answer_mode=True)
        self.assertIsNotNone(out['answer'])
        page=next(p for p in engine.cache.snapshot() if p.url.endswith('/guide'))
        self.assertIn(out['answer']['text'], page.item.content)
        self.assertEqual(out['answer']['citations'][0]['url'],page.item.url)

    def test_injection_content_cannot_supply_answer(self):
        engine=self.engine(max_pages_per_query=1)
        out=engine.search('orbital guidance',seeds=[self.site.base+'/injection'],answer_mode=True)
        self.assertTrue(out['results'][0]['injection_risk'])
        self.assertIsNone(out['answer'])

    def test_no_sources_returns_explanation_and_never_opens_network(self):
        with patch.object(Fetcher,'_request_once',side_effect=AssertionError('unexpected request')):
            out=self.engine().search('unknown topic')
        self.assertEqual(out['results'],[])
        self.assertEqual(out['coverage']['requests'],0)
        self.assertTrue(any('starting sites' in n for n in out['limitations']))

    def test_unfetched_anchor_cannot_become_result(self):
        engine=self.engine(max_pages_per_query=1)
        out=engine.search('orbital guidance',seeds=[self.site.base+'/'])
        self.assertNotIn(self.site.base+'/guide',{r['url'] for r in out['results']})
        self.assertTrue(all(r['url']==self.site.base+'/' for r in out['results']))

    def test_cache_only_has_no_network_and_preserves_fetch_timestamp(self):
        engine=self.engine(max_pages_per_query=1)
        cold=engine.search('orbital guidance',seeds=[self.site.base+'/guide'])
        with patch.object(Fetcher,'_request_once',side_effect=AssertionError('cache-only network')):
            warm=engine.search('orbital guidance',fetch_pages=False)
        self.assertEqual(warm['results'][0]['fetched_at'],cold['results'][0]['fetched_at'])
        self.assertTrue(warm['results'][0]['cached'])
        self.assertEqual(warm['coverage']['requests'],0)

    def test_expired_cache_cannot_supply_old_results(self):
        engine=self.engine(max_pages_per_query=1,cache_ttl=.02)
        engine.search('orbital guidance',seeds=[self.site.base+'/guide'])
        time.sleep(.03)
        self.assertEqual(engine.search('orbital guidance',fetch_pages=False)['results'],[])

    def test_failed_response_never_ranked(self):
        out=self.query('/missing')
        self.assertEqual(out['results'],[])
        self.assertTrue(any('404' in s.get('detail','') for s in out['crawl_status']))

    def test_robots_blocks_before_page_request(self):
        with Site(robots='User-agent: *\nDisallow: /guide') as site:
            out=self.engine().search('orbital guidance',seeds=[site.base+'/guide'])
            self.assertEqual(out['results'],[])
            self.assertNotIn('/guide',site.hits)
            self.assertEqual(out['crawl_status'][0]['status'],'robots')

    def test_origin_denial_cooldown_is_shared_across_queries(self):
        with Site(robots='User-agent: *\nAllow: /') as site:
            engine=self.engine(max_pages_per_query=1)
            engine.search('orbital guidance',seeds=[site.base+'/limited'])
            out=engine.search('orbital guidance',seeds=[site.base+'/guide'])
            self.assertNotIn('/guide',site.hits)
            self.assertEqual(out['crawl_status'][0]['status'],'cooldown')

    def test_shared_origin_politeness_across_queries(self):
        with Site(robots='User-agent: *\nCrawl-delay: 0.04') as site:
            engine=self.engine(default_delay=.01,max_pages_per_query=1)
            engine.search('orbital guidance',seeds=[site.base+'/guide'])
            engine.search('orbital guidance',seeds=[site.base+'/mapped'])
            stamps=[stamp for path,stamp in site.times if path!='robots.txt']
            self.assertGreaterEqual(stamps[-1]-stamps[-2],.035)
            self.assertEqual(site.hits['/robots.txt'],1)

    def test_request_budget_includes_robots(self):
        engine=self.engine(max_requests_per_query=1)
        out=engine.search('orbital guidance',seeds=[self.site.base+'/guide'])
        self.assertEqual(out['coverage']['requests'],1)
        self.assertEqual(out['results'],[])

    def test_depth_zero_excludes_linked_pages(self):
        out=self.engine(max_depth=0).search('orbital guidance',seeds=[self.site.base+'/'])
        self.assertNotIn(self.site.base+'/guide',{r['url'] for r in out['results']})

    def test_deadline_returns_without_waiting_for_slow_page(self):
        start=time.monotonic()
        out=self.engine().search('orbital guidance',seeds=[self.site.base+'/slow'],timeout_ms=80)
        self.assertLess(time.monotonic()-start,.3)
        self.assertEqual(out['results'],[])
        self.assertTrue(out['timed_out'] or any(s['status']=='timeout' for s in out['crawl_status']))

    def test_no_late_cache_write_after_cutoff(self):
        engine=self.engine()
        engine.search('orbital guidance',seeds=[self.site.base+'/slow'],timeout_ms=50)
        time.sleep(.4)
        self.assertEqual(engine.cache.stats()['pages'],0)

    def test_byte_limit_prevents_oversized_page(self):
        out=self.engine(max_page_bytes=512).search('orbital guidance',seeds=[self.site.base+'/large'])
        self.assertEqual(out['results'],[])
        self.assertTrue(any(s['status']=='too_large' for s in out['crawl_status']))

    def test_failed_responses_cannot_bypass_total_byte_budget(self):
        with Site(robots='User-agent: *\nAllow: /') as site:
            for path in ('/oversize-a','/oversize-b','/oversize-c'):
                site.rows[path]=(200,'text/plain',b'x'*20000,{})
            out=self.engine(max_page_bytes=512,max_bytes_per_query=700).search('orbital guidance',
                seeds=[site.base+p for p in ('/oversize-a','/oversize-b','/oversize-c')])
            self.assertLessEqual(out['coverage']['budget_bytes'],700)
            self.assertNotIn('/oversize-c',site.hits)
            self.assertEqual(out['results'],[])

    def test_gzip_page_can_be_ranked(self):self.assertTrue(self.query('/gzip')['results'])
    def test_noindex_page_not_ranked(self):self.assertEqual(self.query('/noindex')['results'],[])
    def test_header_noindex_page_not_ranked(self):self.assertEqual(self.query('/header-noindex')['results'],[])
    def test_nofollow_stops_page_links(self):
        self.query('/none')
        self.assertNotIn('/hidden-link',self.site.hits)

    def test_redirect_checks_target_scope(self):
        out=self.query('/redirect-outside')
        self.assertEqual(out['results'],[])
        self.assertTrue(any(s['status']=='scope' for s in out['crawl_status']))
    def test_redirect_uses_actual_final_url(self):
        self.assertEqual(self.query('/redirect')['results'][0]['url'],self.site.base+'/guide')
    def test_canonical_duplicates_collapse(self):
        engine=self.engine();out=engine.search('orbital guidance',seeds=[self.site.base+'/guide',self.site.base+'/duplicate'])
        self.assertEqual(sum(r['url'].endswith(('/guide','/duplicate')) for r in out['results']),1)
    def test_feed_links_are_fetched_before_ranking(self):
        out=self.engine().search('orbital guidance',seeds=[self.site.base+'/feed'])
        self.assertIn(self.site.base+'/guide',{r['url'] for r in out['results']})
    def test_xml_entities_rejected(self):
        out=self.query('/evil.xml')
        self.assertEqual(out['results'],[])
        self.assertTrue(any(s['status']=='content_type' for s in out['crawl_status']))

    def test_exact_phrase_and_exclusion_filters(self):
        self.assertTrue(self.query(query='"orbital guidance"')['results'])
        self.assertEqual(self.query(query='"orbital missing guidance"')['results'],[])
        self.assertEqual(self.query(query='orbital guidance -spacecraft')['results'],[])
    def test_language_filter(self):
        self.assertEqual(self.query('/foreign',lang='en')['results'],[])
        self.assertTrue(self.query('/foreign',lang='hi')['results'])
    def test_freshness_rejects_unknown_publication(self):
        self.assertEqual(self.query('/undated',freshness='day')['results'],[])
        self.assertTrue(self.query(freshness='day')['results'])
    def test_html_actual_filetype(self):
        self.assertTrue(self.query(filetype='web')['results'])
        self.assertEqual(self.query(filetype='pdf')['results'],[])
    def test_pdf_without_pdf_extension(self):
        out=self.query('/pdf',filetype='pdf')
        self.assertTrue(out['results'])
        self.assertEqual(out['results'][0]['filetype'],'pdf')
    def test_office_without_office_extension(self):
        out=self.query('/office',filetype='docx')
        self.assertTrue(out['results'])
        self.assertEqual(out['results'][0]['filetype'],'docx')
    def test_custom_text_filetype_from_content_type(self):
        out=self.query('/csv',filetype='csv')
        self.assertTrue(out['results'])
    def test_images_derive_from_fetched_page(self):
        out=self.query('/image',search_type='images')
        self.assertEqual(out['images'][0]['image_url'],self.site.base+'/actual.png')
        self.assertEqual(self.query(search_type='images')['results'],[])
    def test_video_requires_actual_metadata(self):
        self.assertTrue(self.query('/video',search_type='video')['results'])
        self.assertEqual(self.query(search_type='video')['results'],[])
    def test_explicit_url_is_crawl_input_not_query_noise(self):
        out=self.query(query='orbital guidance '+self.site.base+'/guide')
        self.assertTrue(out['results'])
        self.assertNotIn('http',out['query_understanding']['required'])
    def test_site_filter_excludes_other_host(self):
        engine=self.engine(max_pages_per_query=1)
        engine.search('orbital guidance',seeds=[self.site.base+'/guide'])
        self.assertEqual(engine.search('orbital guidance',site='different.example',fetch_pages=False)['results'],[])
    def test_zero_database_files_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=IndependentSearch(replace(settings(max_pages_per_query=1),data_dir=Path(tmp)))
            engine.search('orbital guidance',seeds=[self.site.base+'/guide'])
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_concurrent_search_capacity(self):
        engine=self.engine(max_concurrent_searches=1)
        engine.slots.acquire()
        try:
            with self.assertRaises(Busy):engine.search('orbital guidance')
        finally:engine.slots.release()
    def test_invalid_inputs_rejected(self):
        for kw in ({'limit':51},{'timeout_ms':1},{'search_type':'bad'},{'seeds':'url'},{'offset':-1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):self.engine().search('query',**kw)

class QueryUnderstandingTests(unittest.TestCase):
    def test_uncertain_intent_does_not_add_an_unrequested_date_filter(self):
        q=parse_query('orbital research');q.intent='news';q.freshness='week';q.after=123
        q.intent_scores={'news':.24,'tech_docs':.23}
        q.intent_confidence={'status':'uncalibrated','margin':.01}
        q.explicit_date_filter=False;q.fresh_intent=False
        with patch('ownsearch.coordinator.parse_query',return_value=q):
            out=IndependentSearch(settings()).search('orbital research',fetch_pages=False)
        self.assertEqual(out['query_understanding']['intent'],'general')
        self.assertIsNone(out['query_understanding']['after'])
    def test_explicit_dates_survive_uncertain_intent(self):
        q=parse_query('orbital after:2026-01-01');q.intent='news'
        expected=q.after
        q.intent_scores={'news':.24,'tech_docs':.23}
        q.intent_confidence={'status':'uncalibrated','margin':.01}
        with patch('ownsearch.coordinator.parse_query',return_value=q):
            out=IndependentSearch(settings()).search('orbital after:2026-01-01',fetch_pages=False)
        self.assertEqual(out['query_understanding']['after'],expected)
    def test_unicode_subject_tokens_are_preserved(self):
        from ownsearch.textproc import tokenize,exact_tokens
        for text in ('પાણી સંગ્રહ','पानी संरक्षण','潮汐原理','المد والجزر'):
            self.assertTrue(tokenize(text))
            self.assertTrue(exact_tokens(text))
    def test_calendar_timezone_remains_explicit(self):
        q=parse_query('published last month',timezone_name='Asia/Kolkata')
        from ownsearch.webquery import conservative_intent
        q=conservative_intent(q)
        self.assertEqual(q.temporal['timezone'],'Asia/Kolkata')
        self.assertLess(q.after,q.before)

class DocumentationRankingTests(unittest.TestCase):
    def test_project_documentation_with_version_only_title_uses_fetched_evidence(self):
        q=parse_query('orbital tutorial');q.intent='tech_docs'
        page=WebCandidate('3.15 Documentation','https://docs.orbital.example/3/',
                          content='Orbital documentation describes the orbital programming tutorial and reference.')
        self.assertEqual([p.url for p in rank([page],q)],[page.url])
    def test_matching_hostname_cannot_rank_unrelated_content(self):
        q=parse_query('orbital tutorial');q.intent='tech_docs'
        page=WebCandidate('3.15 Documentation','https://docs.orbital.example/3/',content='Cooking recipes and vegetable preparation.')
        self.assertEqual(rank([page],q),[])

class SecurityTests(unittest.TestCase):
    def test_ssrf_private_literals_blocked(self):
        for url in ('http://127.0.0.1/','http://169.254.169.254/','http://[::1]/','file:///etc/passwd','http://user:pass@example.org/'):
            self.assertIsNone(web_url(url))
            with self.assertRaises(FetchError):
                fetcher=Fetcher(Settings())
                target=fetcher.check_url(url)
                fetcher.resolve(target.hostname, target.port or 80)
    def test_dns_rebinding_private_answer_blocked(self):
        fetcher=Fetcher(Settings())
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]):
            with self.assertRaises(FetchError):fetcher._resolve_for_request('example.org',80,time.monotonic()+1)
    def test_query_parameter_order_and_duplicates_preserved(self):
        url='https://example.org/p?x=1&x=2&z=3'
        self.assertEqual(web_url(url),url)
    def test_robots_longest_match_and_wildcards(self):
        p=RobotsPolicy.parse('User-agent: *\nDisallow: /hidden\nAllow: /hidden/open\nDisallow: /*?secret=*','ownsearchbot')
        self.assertFalse(p.allowed('https://example.org/hidden/x'))
        self.assertTrue(p.allowed('https://example.org/hidden/open'))
        self.assertFalse(p.allowed('https://example.org/a?secret=yes'))
    def test_memory_cache_byte_limit(self):
        cache=PageCache(10,10,10)
        cache.put('u',CrawledPage('u',WebCandidate('title','https://example.org/',content='x'*500)))
        self.assertEqual(cache.stats()['pages'],0)
    def test_memory_cache_entry_limit(self):
        cache=PageCache(1,100000,10)
        for url in ('https://example.org/a','https://example.org/b'):
            cache.put(url,CrawledPage(url))
        self.assertEqual([p.url for p in cache.snapshot()],['https://example.org/b'])
    def test_stale_provider_config_cannot_enable_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'ownsearch.json').write_text(json.dumps({'searxng_url':'http://127.0.0.1:8080','brave_api_key':'legacy','sources_file':''}))
            cfg=Settings.load(tmp)
            self.assertFalse(hasattr(cfg,'searxng_url'))
            with patch.object(Fetcher,'_request_once',side_effect=AssertionError('old provider called')):
                self.assertEqual(IndependentSearch(cfg).search('query')['coverage']['requests'],0)
    def test_bounded_origin_state_cannot_drop_live_cooldown(self):
        state=OriginState(1)
        state.get('a').cooldown=time.monotonic()+10
        with self.assertRaises(FetchError):state.get('b')
