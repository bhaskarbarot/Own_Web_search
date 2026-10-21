"""Official API contracts with source-provided URLs, no public requests."""
import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from ownsearch.fetcher import Fetcher,FetchResult
from ownsearch.query import parse_query
from ownsearch.webmodels import WebRequest
from ownsearch.vertical import WikipediaApiProvider,WikidataApiProvider,GitHubApiProvider,PyPIApiProvider,NpmApiProvider,configured_verticals
from ownsearch.coordinator import LiveSearch
from tests.test_live_web import settings,Source,row


class VerticalApiTests(unittest.TestCase):
    def request(self,text='orbital sensor calibration'):
        return WebRequest(text,parse_query(text),threading.Event())
    def payload(self,value):
        return patch.object(Fetcher,'fetch',return_value=FetchResult('','',200,{},json.dumps(value).encode()))
    def test_wikipedia_uses_only_actual_fullurl_and_never_revision_date_as_publication(self):
        p=WikipediaApiProvider(settings())
        with self.payload({'query':{'pages':[{'title':'Orbital sensor calibration','fullurl':'https://reference.example.org/sensor','extract':'Calibrating orbital sensors.','touched':'2026-10-21'},
                                           {'title':'Missing URL','pageid':123}]}}):
            batch=p.search(self.request(),time.monotonic()+1)
        self.assertEqual([r['url'] for r in batch.rows],['https://reference.example.org/sensor'])
        self.assertIsNone(batch.rows[0]['published_at'])
    def test_wikidata_uses_concepturi_without_fabricating_result_urls(self):
        p=WikidataApiProvider(settings())
        with self.payload({'search':[{'id':'Q987','label':'Sensor','description':'Measurement instrument','concepturi':'https://entities.example.org/Q987'},
                                    {'id':'Q986','label':'No URL'}]}):batch=p.search(self.request(),time.monotonic()+1)
        self.assertEqual(len(batch.rows),1)
        self.assertEqual(batch.rows[0]['url'],'https://entities.example.org/Q987')
    def test_vertical_config_is_independent_and_general_fallback_stays_enabled(self):
        self.assertEqual(configured_verticals(settings()),[])
        self.assertEqual([p.name for p in configured_verticals(settings(vertical_providers='wikipedia,wikidata'))],['wikipedia','wikidata'])
        with self.assertRaises(ValueError):configured_verticals(settings(vertical_providers='unknown'))
        p=WikipediaApiProvider(settings());p.accepts=lambda req:False
        result=LiveSearch(settings(),[p,Source('general')]).search('Nebula installation',fetch_pages=False)
        self.assertTrue(result['results'])
        self.assertTrue(any(s['provider']=='wikipedia' and s['status']=='not_selected' for s in result['provider_status']))
        self.assertFalse(LiveSearch(settings(),[p]).diagnostics()['general_discovery_configured'])
    def test_unsafe_api_result_urls_are_rejected(self):
        p=WikipediaApiProvider(settings())
        for url in ('http://127.0.0.1/admin','file:///etc/passwd','https://user:secret@example.org/'):
            self.assertIsNone(p.row(self.request(),url,'Unsafe'))
    def test_github_issue_search_preserves_real_links_and_open_status_qualifier(self):
        p=GitHubApiProvider(settings())
        with self.payload({'items':[{'html_url':'https://code.example.org/a/issues/9','title':'Orbital bug','body':'Sensor calibration error.'}], 'incomplete_results':True}) as fetch:
            batch=p.search(self.request('GitHub open bugs orbital sensor'),time.monotonic()+1)
        self.assertEqual(batch.rows[0]['url'],'https://code.example.org/a/issues/9')
        query=parse_qs(urlsplit(fetch.call_args.args[0]).query)['q'][0]
        self.assertIn('is:issue',query);self.assertIn('is:open',query)
        self.assertTrue(batch.warnings)
        self.assertEqual(p.health_snapshot()['budget_window_seconds'],3600)
    def test_pypi_is_exact_lookup_and_uses_only_owner_published_links(self):
        p=PyPIApiProvider(settings())
        req=self.request('Python NebulaKit timeout documentation')
        data={'info':{'name':'NebulaKit','summary':'Timeout configuration library.',
                      'project_urls':{'Documentation':'https://docs.example.org/nebula','Local':'http://127.0.0.1/admin'}}}
        with self.payload(data):batch=p.search(req,time.monotonic()+1)
        self.assertEqual([r['url'] for r in batch.rows],['https://docs.example.org/nebula'])
        self.assertEqual(batch.rows[0]['source_query'],'NebulaKit')
        self.assertFalse(p.accepts(self.request('Find Python libraries extracting webpage text')))
        self.assertFalse(p.accepts(self.request('Python code examples')))
    def test_pypi_missing_project_does_not_poison_healthy_service(self):
        p=PyPIApiProvider(settings())
        with patch.object(Fetcher,'fetch',return_value=FetchResult('','',404,{},b'')):
            for _ in range(2):
                # Respect the adapter spacing without waiting in this schema test.
                p.minimum_interval=0
                self.assertEqual(p.search(self.request('Python MissingNebula package'),time.monotonic()+1).rows,[])
        self.assertEqual(p.health_snapshot()['errors'],0)
    def test_npm_returns_only_actual_package_links_with_bounded_rows(self):
        p=NpmApiProvider(settings())
        package={'name':'orbital-sensor','description':'Orbital sensor calibration library.',
                 'date':'2026-10-21','links':{'npm':'https://registry.example.org/actual-package','homepage':'http://127.0.0.1/admin'}}
        with self.payload({'objects':[{'package':package},{'package':{'name':'No links'}}]}):batch=p.search(self.request('JavaScript orbital sensor npm'),time.monotonic()+1)
        self.assertEqual(len(batch.rows),1)
        self.assertEqual(batch.rows[0]['url'],'https://registry.example.org/actual-package')
        self.assertIsNone(batch.rows[0]['published_at'])


if __name__=='__main__':unittest.main()
