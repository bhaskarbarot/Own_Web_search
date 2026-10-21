"""Named origins and actually declared sitemap/feed links, with no public network."""
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from ownsearch.coordinator import LiveSearch
from ownsearch.fetcher import FetchError,FetchResult
from ownsearch.query import parse_query
from ownsearch.robots import RobotsPolicy
from ownsearch.webfetch import WebFetchSession
from ownsearch.webfocus import feed_links,named_site_seed,sitemap_links
from ownsearch.webmodels import WebCandidate
from ownsearch.webranking import constraints
from tests.test_live_web import settings,Source


class FocusedDiscoveryTests(unittest.TestCase):
    def test_user_origin_never_becomes_an_unfetched_result(self):
        q=parse_query('site:docs.example.org "orbital sensor calibration"')
        seed=named_site_seed([],q)[0]
        self.assertFalse(constraints(seed,q,final=True))
        with patch.object(WebFetchSession,'page',side_effect=FetchError('Robots denied','robots')):
            result=LiveSearch(settings(),[]).search(q.raw)
        self.assertEqual(result['results'],[])
        for text in ('site:127.0.0.1 sensor','site:localhost sensor','site:user:password@example.org sensor'):
            self.assertEqual(named_site_seed([],parse_query(text)),[])
    def test_named_site_recovers_from_empty_general_discovery_through_declared_index(self):
        root='https://docs.example.org/'
        bodies={root+'robots.txt':('text/plain',b'User-agent: *\nAllow: /\nSitemap: https://docs.example.org/declared.xml\n'),
                root:('text/html',b'<html><head><title>Reference home</title></head><body><p>Welcome to the documentation collection.</p></body></html>'),
                root+'declared.xml':('application/xml',b'<sitemapindex><sitemap><loc>https://docs.example.org/child.xml</loc></sitemap></sitemapindex>'),
                root+'child.xml':('application/xml',b'<urlset><url><loc>https://docs.example.org/orbital-sensor-calibration</loc></url></urlset>'),
                root+'orbital-sensor-calibration':('text/html',b'<html><head><title>Orbital sensor calibration</title></head><body><p>Orbital sensor calibration requires measuring sensor drift before calibration.</p></body></html>')}
        calls=[]
        def request(client,url,headers,max_bytes,method='GET',deadline=None):
            calls.append(url)
            if url not in bodies:raise AssertionError('Unobserved target: '+url)
            kind,body=bodies[url];return 200,{'content-type':kind},body,False
        with patch.object(WebFetchSession,'_request_once',request):
            with patch('ownsearch.webfocus.named_site_seed',return_value=[]):
                before=LiveSearch(settings(live_fetch_timeout=.7,discovery_timeout=1.5),[]).search(
                    'site:docs.example.org "orbital sensor calibration"')
            self.assertEqual(before['results'],[])
            self.assertEqual(calls,[])
            result=LiveSearch(settings(live_fetch_timeout=.7,discovery_timeout=1.5),[]).search(
                'site:docs.example.org "orbital sensor calibration"')
        self.assertEqual([r['url'] for r in result['results']],[root+'orbital-sensor-calibration'])
        self.assertEqual(len(calls),5)
        self.assertEqual(result['results'][0]['fetch_status'],'fetched')
    def test_only_one_declared_same_origin_feed_is_requested_and_updated_is_not_publication(self):
        page=WebCandidate('Orbital sensor','https://news.example.org/',feeds=[
            'https://external.example.org/feed','https://news.example.org/actual-feed','https://news.example.org/unused-feed'])
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Orbital sensor release</title><link href="https://news.example.org/real-article"/><updated>2026-10-20T00:00:00Z</updated></entry><entry><title>Orbital sensor</title><link href="http://127.0.0.1/private"/></entry></feed>'
        calls=[]
        class Session:
            def page(self,url,deadline):
                calls.append(url);return FetchResult(url,url,200,{'content-type':'application/atom+xml'},xml)
        q=parse_query('orbital sensor news');q.fresh_intent=True
        rows=feed_links(Session(),page,q,time.monotonic()+1)
        self.assertEqual(calls,['https://news.example.org/actual-feed'])
        self.assertEqual([r.url for r in rows],['https://news.example.org/real-article'])
        self.assertIsNone(rows[0].published_at)
        self.assertEqual(rows[0].provenance[-1]['parent_url'],page.url)
    def test_feed_does_not_guess_a_url_or_expand_entities(self):
        page=WebCandidate('Sensor','https://news.example.org/')
        q=parse_query('sensor news');q.fresh_intent=True
        class NoRequests:
            def page(self,*args):raise AssertionError('No declared feed')
        self.assertEqual(feed_links(NoRequests(),page,q,time.monotonic()+1),[])
        page.feeds=['https://news.example.org/actual-feed']
        class EntityFeed:
            def page(self,url,deadline):return FetchResult(url,url,200,{},b'<!DOCTYPE x [<!ENTITY x "y">]><rss/>')
        self.assertEqual(feed_links(EntityFeed(),page,q,time.monotonic()+1),[])
    def test_sitemap_index_cannot_escape_origin_or_recurse_unbounded(self):
        page=WebCandidate('Sensor','https://docs.example.org/')
        calls=[]
        class Session:
            settings=globals()['settings']()
            def policy(self,*args):return RobotsPolicy(sitemaps=['https://docs.example.org/map'])
            def page(self,url,deadline):
                calls.append(url)
                xml=b'<sitemapindex><sitemap><loc>https://outside.example.org/map</loc></sitemap><sitemap><loc>https://docs.example.org/second</loc></sitemap></sitemapindex>'
                return FetchResult(url,url,200,{'content-type':'application/xml'},xml)
        self.assertEqual(sitemap_links(Session(),page,parse_query('sensor'),time.monotonic()+1),[])
        self.assertEqual(calls,['https://docs.example.org/map','https://docs.example.org/second'])
