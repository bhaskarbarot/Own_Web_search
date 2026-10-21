"""UI/API → actual HTTP crawl → ranked/cited response integration tests."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ownsearch.auth import KeyStore
from ownsearch.coordinator import IndependentSearch
from ownsearch.server import SearchServer
from tests.independent_fixture import Site
from tests.test_independent import settings

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site=Site()
        cls.tmp=tempfile.TemporaryDirectory()
        cfg=settings(data_dir=Path(cls.tmp.name),max_pages_per_query=1)
        cls.engine=IndependentSearch(cfg)
        cls.api=SearchServer(('127.0.0.1',0),cls.engine)
        cls.thread=threading.Thread(target=cls.api.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.api.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.api.shutdown();cls.api.server_close();cls.thread.join(1);cls.site.close();cls.tmp.cleanup()
    def request(self,path='/search',body=None,headers=None):
        h={'Content-Type':'application/json'};h.update(headers or {})
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urlopen(req,timeout=5) as response:return response.status,response.headers,response.read()
        except HTTPError as response:return response.code,response.headers,response.read()
    def test_ui_served_and_filters_connected(self):
        status,headers,body=self.request('/ui')
        self.assertEqual(status,200)
        text=body.decode()
        for element in ('seeds','freshness','filetype','site','lang','search-type','timezone','answer-mode','fetch-pages'):
            self.assertIn('id="'+element+'"',text)
        self.assertIn('payload.seeds',text)
        self.assertIn('textContent',text)
        self.assertNotIn('innerHTML',text)
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
    def test_post_search_full_flow_with_answer(self):
        status,_,body=self.request(body={'query':'orbital guidance','seeds':[self.site.base+'/guide'],'answer_mode':True,'explain':True})
        data=json.loads(body)
        self.assertEqual(status,200)
        self.assertEqual(data['mode'],'independent')
        self.assertEqual(data['answer']['citations'][0]['url'],self.site.base+'/guide')
        self.assertIn('features',data['results'][0])
        self.assertEqual(list(Path(self.tmp.name).iterdir()),[])
    def test_streaming_search_flow(self):
        status,headers,body=self.request('/search/stream',body={'query':'orbital guidance','seeds':[self.site.base+'/guide']})
        self.assertEqual(status,200)
        self.assertIn('text/event-stream',headers.get('Content-Type',''))
        text=body.decode()
        self.assertIn('data: ',text)
        self.assertIn('"stage": "final"',text)
    def test_get_query_and_boolean_options(self):
        status,_,body=self.request('/search?q=orbital+guidance&fetch_pages=false&answer_mode=true')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['coverage']['requests'],0)
    def test_bad_query_and_payloads(self):
        for body in ({'query':[]},{'query':'q','limit':100},{'query':'q','unknown':True},{'query':'q','fetch_pages':'invalid'},[]):
            status,_,_=self.request(body=body)
            self.assertEqual(status,400)
    def test_cross_origin_cannot_trigger_crawl(self):
        status,_,_=self.request(body={'query':'q'},headers={'Origin':'https://elsewhere.example'})
        self.assertEqual(status,403)
    def test_dns_rebinding_host_is_rejected(self):
        status,_,_=self.request('/search?q=q',headers={'Host':'attacker.example'})
        self.assertEqual(status,403)
    def test_cross_site_get_cannot_trigger_crawl(self):
        status,_,_=self.request('/search?q=q',headers={'Sec-Fetch-Site':'cross-site'})
        self.assertEqual(status,403)
    def test_health_reports_independent_database_false(self):
        status,_,body=self.request('/health');data=json.loads(body)
        self.assertEqual(status,200)
        self.assertEqual(data['mode'],'independent')
        self.assertFalse(data['database'])
    def test_stats_reports_memory_only(self):
        status,_,body=self.request('/stats')
        self.assertEqual(status,200)
        self.assertFalse(json.loads(body)['cache']['persistent'])
    def test_ingest_is_not_available(self):
        status,_,_=self.request('/ingest',body={'text':'arbitrary text'})
        self.assertEqual(status,404)
    def test_auth_cannot_be_bypassed_by_ui_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=IndependentSearch(settings(data_dir=Path(tmp)))
            token=KeyStore(engine.settings.keys_path).create('test')
            server=SearchServer(('127.0.0.1',0),engine,require_auth=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                self.assertEqual(urlopen(base+'/ui').status,200)
                with self.assertRaises(HTTPError) as ctx:urlopen(base+'/search?q=guidance&fetch_pages=false')
                self.assertEqual(ctx.exception.code,401)
                req=Request(base+'/search?q=guidance&fetch_pages=false',headers={'Authorization':'Bearer '+token})
                with urlopen(req) as response:self.assertEqual(response.status,200)
            finally:
                server.shutdown();server.server_close();thread.join(1)
