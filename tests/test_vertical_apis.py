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
from ownsearch.vertical import WikipediaApiProvider,WikidataApiProvider,configured_verticals
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


if __name__=='__main__':unittest.main()
