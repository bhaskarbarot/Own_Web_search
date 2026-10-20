"""Behavioral regressions for the optional and multilingual upgrade paths; no live services."""
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from tests.helpers import make_engine
from ownsearch.entities import EntityIndex,mask
from ownsearch.language import identify,tag
from ownsearch.temporal import windows
from ownsearch.feeds import registry
from ownsearch.fusion import fuse
from ownsearch.frontier import Frontier

class UpgradePipelineTests(unittest.TestCase):
    def test_language_evidence_and_priors(self):
        sample=[('કૃત્રિમ બુદ્ધિ','gu'),('ひらがな 漢字','ja'),('한국어','ko'),('ภาษาไทย','th')]
        correct=sum(identify(text)['language']==label for text,label in sample)
        self.assertEqual(correct,len(sample)) # sample only; does not establish language support
        self.assertEqual(identify('कृत्रिम')['alternatives'],['hi','mr','ne'])
        self.assertEqual(identify('requests',hint='fr-CA')['language'],'fr-ca')
        self.assertEqual(tag('hi-IN, en;q=.8'),'hi-in')
        self.assertIsNone(tag('not_a_language'))
        self.assertEqual(tag('en;q=0.2, hi-IN;q=0.9'),'hi-in')

    def test_prior_does_not_filter_other_languages_and_bcp47_filter(self):
        e,_=make_engine()
        e.add_document('Nebula manual','Nebula installation manual','https://a.example/',lang='en-GB')
        e.add_document('Nebula reference','Nebula reference and setup','https://b.example/',lang='fr')
        r=e.search('Nebula',preferred_language='en-GB')
        self.assertEqual(len(r['results']),2)
        self.assertEqual([x['url'] for x in e.search('Nebula',lang='en-gb')['results']],['https://a.example/'])

    def test_local_multilingual_entities_and_typed_masking(self):
        e,_=make_engine(knowledge_enabled=True,remote_knowledge_enabled=False)
        index=EntityIndex(e.root)
        record={'id':'Q123456','labels':{'en':{'value':'The Nebula'},'hi':{'value':'नेबुला समूह'}},
                'aliases':{'en':[{'value':'Nebula Group'}]},'entity_type':'COMPANY'}
        self.assertEqual(index.import_records([record],'synthetic test'),1)
        linked=index.link('The Nebula documentation')
        self.assertEqual(linked[0].span,'the nebula')
        self.assertEqual(mask('The Nebula documentation',linked),'__COMPANY__ documentation')
        self.assertEqual(index.link('नेबुला समूह')[0].qid,record['id'])
        e.add_document('Nebula Group manual','Nebula Group has installation documentation.','https://nebula.example/manual')
        with patch('ownsearch.fetcher.Fetcher.fetch',side_effect=AssertionError('Network forbidden')):
            self.assertEqual(e.search('The Nebula documentation',live=False)['results'][0]['url'],'https://nebula.example/manual')

    def test_ambiguous_local_labels_abstain(self):
        with tempfile.TemporaryDirectory() as tmp:
            index=EntityIndex(tmp)
            index.import_records([{'id':qid,'labels':{'en':{'value':'Cloud Atlas'}}} for qid in ('Q111','Q222')])
            self.assertEqual(index.link('Cloud Atlas'),[])

    def test_non_english_intent_falls_back(self):
        from ownsearch.query import parse_query
        self.assertEqual(parse_query('कृत्रिम बुद्धिमत्ता क्या है').intent,'general')
        from ownsearch.intent import get_model
        label,_,status=get_model().classify_calibrated('stock price','hi')
        self.assertEqual(label,'general');self.assertEqual(status['status'],'no_multilingual_model')

    def test_temporal_grammar_and_explicit_timezone(self):
        now=datetime(2026,3,8,15,tzinfo=timezone.utc)
        for phrase,lang in [('today headlines','en'),('आज समाचार','hi'),('આજે સમાચાર','gu')]:
            result=windows(phrase,lang,'America/New_York',now)
            w=result['windows'][0]
            self.assertAlmostEqual(w['before']-w['after']+.001,23*3600,places=2)
        for query in ('May I use requests','march sorting algorithm','sat exam','second argument'):
            self.assertEqual(windows(query,'en','UTC',now)['windows'],[])
        self.assertTrue(windows('कल समाचार','hi','UTC',now)['ambiguous'])
        self.assertFalse(windows('कल क्या हुआ था','hi','UTC',now)['ambiguous'])
        self.assertGreater(windows('कल क्या होगा','hi','UTC',now)['windows'][0]['after'],now.timestamp())
        with self.assertRaises(ValueError):windows('today','en','Invalid/Timezone',now)

    def test_feed_registry_rejects_bad_metadata_and_keeps_legacy(self):
        feeds,errors=registry(['https://news.example/rss\thi-IN\tIN\tnews','https://legacy.example/feed',
                              'https://bad.example/feed\tbad@@\tIN\tnews','https://bad.example/f\ten\tUS\tspam'])
        self.assertEqual(len(feeds),2);self.assertEqual(len(errors),2)
        self.assertEqual(feeds[0].lang,'hi-IN')

    def test_frontier_independent_caps(self):
        e,_=make_engine(max_frontier_urls=5,max_enqueue_batch=3)
        frontier=Frontier(e.settings)
        frontier.enqueue_many(({'url':f'https://a.example/{i}'} for i in range(10000)),respect_scope=False)
        self.assertEqual(frontier.db.one('SELECT COUNT(*) FROM urls')[0],3)
        frontier.enqueue_many(({'url':f'https://a.example/{i}'} for i in range(3,99)),respect_scope=False)
        self.assertEqual(frontier.db.one('SELECT COUNT(*) FROM urls')[0],5)

    def test_background_discovery_returns_before_crawl_completes(self):
        e,_=make_engine(discovery_mode='background')
        release=threading.Event();started=threading.Event()
        def discover(*args,**kwargs):started.set();release.wait(1);return []
        with patch('ownsearch.discover.discover',side_effect=discover):
            try:
                begin=time.perf_counter();r=e.search('undiscovered subject',live=True,use_cache=False)
                self.assertLess(time.perf_counter()-begin,.5)
                self.assertEqual(r['discovery_status']['state'],'queued')
                self.assertTrue(started.wait(.5))
            finally:release.set()

    def test_rrf_deduplicates_and_attributes(self):
        rows=fuse([[{'url':'https://a.example/','title':'Source'}],[{'url':'https://a.example/#part','title':'Other','provider':'remote'}]])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['providers'],['local_index','remote'])

    def test_provider_error_timeout_and_content_gate(self):
        from ownsearch.providers import eligible
        from ownsearch.query import parse_query
        e,_=make_engine(provider_wait_ms=5)
        e.add_document('Nebula manual','Nebula manual and reference.','https://local.example/')
        release=threading.Event()
        class Slow:
            name='slow'
            def search(self,query,deadline):release.wait(2);return []
        class Bad:
            name='bad'
            def search(self,query,deadline):raise ValueError('fixture failure')
        e.providers=[Slow(),Bad()]
        begin=time.perf_counter()
        try:r=e.search('Nebula manual',live=True,use_cache=False)
        finally:release.set()
        self.assertLess(time.perf_counter()-begin,.5)
        self.assertEqual(r['results'][0]['url'],'https://local.example/')
        self.assertTrue(r['provider_status'])
        self.assertFalse(eligible({'url':'https://x.example/','title':'Unrelated','snippet':'Python news'},parse_query('Nebula manual')))

    def test_optional_models_missing_preserve_core(self):
        e,_=make_engine(vector_index=True,reranker_enabled=True,translation_enabled=True,provider_wait_ms=10,rerank_budget_ms=10)
        e.add_document('Nebula manual','Nebula manual and installation reference.','https://core.example/')
        with patch.dict('sys.modules',{'argostranslate':None,'sentence_transformers':None,'faiss':None}):
            r=e.search('Nebula manual',live=False,use_cache=False)
        self.assertEqual(r['results'][0]['url'],'https://core.example/')
        self.assertTrue(r['provider_errors'])
        self.assertEqual(r['rerank_status'],'base_order_retained')

    def test_real_snippet_highlights_and_metadata_only_reindex(self):
        e,_=make_engine()
        url='https://guide.example/'
        e.add_document('Café manual','Café manual has actual instructions.',url,lang='fr')
        r=e.search('cafe manual',timeout_ms='500')['results'][0]
        self.assertTrue(r['highlights'])
        for h in r['highlights']:self.assertEqual(r['snippet'][h['start']:h['end']],h['text'])
        e.store.upsert(url,'Café manual','Café manual has actual instructions.',lang='en-GB')
        e.indexer.run()
        self.assertEqual(e.search('cafe',lang='en-gb')['results'][0]['url'],url)

    def test_public_adapter_keeps_qrels_and_rejects_missing_passages(self):
        from scripts.import_trec_eval import convert
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'corpus.jsonl').write_text(json.dumps({'docid':'a#1','title':'Fixture','text':'A real supplied passage.'})+'\n')
            (root/'topics.tsv').write_text('q1\tfixture question\n')
            (root/'qrels.tsv').write_text('q1\tQ0\ta#1\t1\n')
            report=convert(root/'corpus.jsonl',root/'topics.tsv',root/'qrels.tsv','hi',root/'output')
            self.assertEqual(report['queries'],1)
            (root/'qrels.tsv').write_text('q1\tQ0\tmissing#1\t1\n')
            with self.assertRaises(ValueError):convert(root/'corpus.jsonl',root/'topics.tsv',root/'qrels.tsv','hi',root/'missing')

    def test_package_docs_are_read_from_source_metadata(self):
        from types import SimpleNamespace
        from ownsearch.discover import PackageMetadataProvider
        from ownsearch.query import parse_query
        e,_=make_engine(package_lookup_url='https://registry.example/{name}.json')
        q=parse_query('Nebulapack timeout documentation',data_dir=e.root)
        payload={'info':{'name':'Nebulapack','summary':'An HTTP client library','project_urls':{'Documentation':'https://unpredictable.example/manual/'}}}
        class Client:
            deadline=time.monotonic()+2
            def raw(self,url,**kwargs):return SimpleNamespace(status=200,body=json.dumps(payload).encode())
        items,errors=PackageMetadataProvider().discover(q.raw,q,e.settings,client=Client())
        self.assertFalse(errors)
        self.assertEqual(q.reference_roots,['https://unpredictable.example/manual/'])
        self.assertEqual(q.entities[0].label,'Nebulapack')
        self.assertEqual(q.entities[0].urls,q.reference_roots)

    def test_calibration_can_abstain_on_every_unsupported_case(self):
        from scripts.calibrate_intent import calibrate
        from ownsearch.intent import IntentModel
        model=IntentModel([('news','latest bulletin'),('tech_docs','api reference')])
        table=calibrate([('tech_docs','latest bulletin')],model)
        self.assertTrue(table['reject_all'])
        self.assertEqual(table['coverage'],0)
        label,_,_=model.classify_calibrated('latest bulletin','en',{'en':table})
        self.assertEqual(label,'general')

if __name__=='__main__':unittest.main()
