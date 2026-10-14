"""Adversarial retrieval and direct-answer checks; every external call is forbidden or mocked."""
import copy
import json
import math
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ownsearch.answer_evaluation import assess_answer
from ownsearch.engine import _official_scope
from ownsearch.evaluation import ndcg, mrr, precision, _keys_for, _match, evaluate, load_qrels
from ownsearch.knowledge import Entity, Knowledge
from ownsearch.live import PageClient
from ownsearch.market import Market
from ownsearch.query import parse_query
from ownsearch.dates import parse_duration, start_of_today_utc
from scripts.audit_query_checklist import read_checklist
from tests.helpers import make_engine

FIXTURE = Path(__file__).with_name('fixtures') / 'acceptance_relevance.json'


class RelevanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.engine, _ = make_engine(knowledge_enabled=True)
        for original in cls.fixture['documents']:
            doc = dict(original)
            if doc.pop('recent', False):
                doc['published_at'] = datetime.now(timezone.utc).isoformat()
            cls.engine.store.upsert(**doc)
        for n in range(350):
            cls.engine.store.upsert(f'https://noise{n}.example/article', f'Community {n}',
                f'The great class and program {n}. Ashok contributed a Python package. '
                'Inheritance and price today are mentioned with model context news.')
        cls.engine.rebuild_index()

    def run_case(self, query):
        case = next(c for c in self.fixture['queries'] if c['query'] == query)
        with patch.object(Knowledge, 'link', return_value=[Entity(**e) for e in case['entities']]), patch('ownsearch.discover.discover', return_value=[]), patch('ownsearch.fetcher.Fetcher.fetch', side_effect=AssertionError('External network forbidden')):
            result = self.engine.search(query, live=True, use_cache=False, limit=10)
        urls = {r['url'] for r in result['results']}
        self.assertEqual(urls, set(case['judgments']))
        self.assertLess(result['coverage']['matched_documents'], 10)
        keys = _match(_keys_for(result['results']), case['judgments'])
        self.assertEqual(mrr(keys, case['judgments']), 1)
        self.assertEqual(ndcg(keys, case['judgments']), 1)
        return result

    def test_nvidia_live_price(self):
        self.run_case('Nvidia live price')

    def test_todays_trump_headlines(self):
        self.run_case("today's Trump headlines")

    def test_ashoka_birthplace_rejects_modi_and_buddha_birthplace(self):
        self.run_case('Samrat Ashok birthplace')

    def test_tcs_six_month_analysis(self):
        self.run_case('TCS 6-month analysis')

    def test_inheritance_in_oops(self):
        self.run_case('inheritance in OOPS')

    def test_claude_mcp_content_and_official_scopes(self):
        self.run_case('Claude docs on MCP')

    def test_python_requests_timeout_parameter(self):
        self.run_case('Python requests timeout parameter documentation')

    def test_unseen_subjects_and_names_do_not_depend_on_acceptance_queries(self):
        engine, _ = make_engine(knowledge_enabled=True)
        engine.add_document('Quasar toolkit retry instructions', 'Quasar retries requests using a configured delay. Quasar toolkit supports retry limits.', 'https://quasar.example/retry')
        engine.add_document('Another product', 'A footer mentions Quasar once. Other products explain retry rules.', 'https://other.example/')
        entity = Entity('Q99', 'Quasar toolkit', aliases=['Quasar'], span='QTK')
        with patch.object(Knowledge, 'link', return_value=[entity]), patch('ownsearch.discover.discover', return_value=[]):
            r = engine.search('QTK retry docs', live=True, use_cache=False)
        self.assertEqual([x['url'] for x in r['results']], ['https://quasar.example/retry'])

    def test_exact_phrase_and_explicit_or_preserved(self):
        engine, _ = make_engine()
        engine.add_document('Blue river', 'A blue river flows through the valley.', 'https://one.example/')
        engine.add_document('River in the sky', 'A blue sky is above the river.', 'https://two.example/')
        self.assertEqual(len(engine.search('"blue river"')['results']), 1)
        self.assertEqual(len(engine.search('valley OR sky')['results']), 2)
        self.assertEqual(len(engine.search('blue nonexistent')['results']), 0)

    def test_alias_words_are_not_a_phrase_when_scattered(self):
        engine, _ = make_engine(knowledge_enabled=True)
        engine.add_document('Unrelated', 'Quasar is a star. Toolkit design appears elsewhere.', 'https://noise.example/')
        with patch.object(Knowledge, 'link', return_value=[Entity('Q99','Quasar toolkit',span='QTK')]), patch('ownsearch.discover.discover', return_value=[]):
            self.assertEqual(engine.search('QTK docs',live=True)['results'], [])

    def test_github_authority_is_repository_scoped(self):
        entities = [Entity('Q1','Quasar',urls=['https://github.com/org/quasar'])]
        self.assertTrue(_official_scope('https://github.com/org/quasar/tree/main', entities))
        self.assertFalse(_official_scope('https://github.com/another/quasar', entities))
        self.assertFalse(_official_scope('https://github.com/org/quasar-extra', entities))
        results=[{'id':1,'url':'https://github.com/org/quasar/tree/main'},
                 {'id':2,'url':'https://github.com/other/quasar'}]
        judgments={'prefix:https://github.com/org/quasar':3,'host:github.com':0}
        self.assertEqual(_match(_keys_for(results),judgments),['prefix:https://github.com/org/quasar','host:github.com'])

    def test_cached_timing_is_request_time(self):
        first = self.engine.search('Nvidia live price', use_cache=True)
        second = self.engine.search('Nvidia live price', use_cache=True)
        self.assertTrue(second['cached'])
        self.assertEqual(second['timing']['total_ms'], second['took_ms'])
        self.assertEqual(second['timing']['discovery_ms'], 0)
        self.assertEqual(second['timing']['cached_response_original_ms'], first['took_ms'])

    def test_useful_docs_skip_provider_discovery(self):
        case = next(c for c in self.fixture['queries'] if c['query']=='Claude docs on MCP')
        with patch.object(Knowledge,'link',return_value=[Entity(**e) for e in case['entities']]), patch('ownsearch.discover.discover') as discover:
            self.engine.search(case['query'],live=True,use_cache=False)
        discover.assert_not_called()

    def test_one_useful_document_is_enough_to_skip_slow_providers(self):
        case=next(c for c in self.fixture['queries'] if c['query']=='Python requests timeout parameter documentation')
        with patch.object(Knowledge,'link',return_value=[Entity(**e) for e in case['entities']]), patch('ownsearch.discover.discover') as discover:
            self.engine.search(case['query'],live=True,use_cache=False)
        discover.assert_not_called()

    def test_network_timeout_is_capped_by_global_and_provider_deadlines(self):
        engine, _ = make_engine(discovery_provider_timeout=0.1)
        client = PageClient(engine.settings, time.monotonic()+10)
        start = time.monotonic()
        with patch.object(client.fetcher,'fetch') as fetch:
            client.raw('https://slow.example/')
        self.assertLessEqual(fetch.call_args.kwargs['deadline'], start+0.11)
        client.deadline = start+0.05
        with patch.object(client.fetcher,'fetch') as fetch:
            client.raw('https://slow.example/')
        self.assertEqual(fetch.call_args.kwargs['deadline'], client.deadline)

    def test_reranking_wait_cannot_exceed_expired_request_budget(self):
        engine, _ = make_engine(max_concurrent_searches=1,discovery_timeout=0.02)
        def blocked_discovery(*args,**kwargs):
            engine._slots.acquire()
            time.sleep(0.03)
            return [{'result':'cached','url':'https://example.test/'}]
        started=time.monotonic()
        try:
            with patch('ownsearch.discover.discover',side_effect=blocked_discovery):
                result=engine.search('UnseenQuasar',live=True,use_cache=False)
        finally:
            engine._slots.release()
        self.assertLess(time.monotonic()-started,0.2)
        self.assertTrue(result['timed_out'])

    def test_category_checklist_has_150_queries_and_30_categories(self):
        cases = read_checklist(FIXTURE.with_name('daily_search_checklist.json'))
        self.assertEqual(len(cases),150)
        self.assertEqual(len({c['category'] for c in cases}),30)

    def test_written_duration_is_grammar_and_not_a_company_name(self):
        q = parse_query('Quasar six-month stock analysis')
        self.assertEqual(parse_duration('six months'),183)
        self.assertEqual(q.entity,['Quasar'])
        self.assertNotIn('six',q.required)

    def test_today_yesterday_and_named_month_use_calendar_boundaries(self):
        today = parse_query("today's Quasar headlines")
        self.assertEqual(today.after,start_of_today_utc())
        yesterday = parse_query('Quasar headlines yesterday')
        self.assertEqual(yesterday.after,start_of_today_utc()-86400)
        self.assertLess(yesterday.before,today.after)
        month = parse_query('technology news in September 2026')
        self.assertEqual(datetime.fromtimestamp(month.after,timezone.utc).strftime('%Y-%m-%d'),'2026-09-01')
        self.assertEqual(datetime.fromtimestamp(month.before,timezone.utc).strftime('%Y-%m-%d'),'2026-09-30')

    def test_reference_hint_uses_source_item_id_without_topic_mapping(self):
        engine, _ = make_engine()
        knowledge = Knowledge(engine.settings)
        record = {'labels':{'en':{'value':'Quasar'}},'aliases':{},'descriptions':{'en':{'value':'Python networking library'}},'sitelinks':{},'claims':{}}
        with patch.object(knowledge,'entities',return_value={'Q99':record}), patch.object(knowledge,'_wd_search',return_value=[]), patch.object(knowledge,'_wp_search',return_value=[]):
            entities = knowledge.link(['Python','Quasar','timeout'],['docs'],candidate_ids=[('Quasar library','Q99')])
        self.assertEqual([e.qid for e in entities],['Q99'])

    def test_cached_records_are_independent_of_original_request_batch(self):
        engine, _ = make_engine()
        knowledge = Knowledge(engine.settings)
        record = {'labels':{'en':{'value':'Quasar'}},'claims':{}}
        knowledge.cache.put('source-request',{'entities':{'Q99':record}})
        with patch.object(knowledge,'_json',side_effect=AssertionError('A cached record must not fetch')):
            self.assertEqual(knowledge.entities(['Q99'],claims=True),{'Q99':record})

    def test_property_records_do_not_become_named_entities(self):
        engine, _ = make_engine()
        knowledge = Knowledge(engine.settings)
        record={'labels':{'en':{'value':'Quasar'}}}
        knowledge.cache.put('source',{'entities':{'P99':record,'Q99':record}})
        self.assertEqual([r['id'] for r in knowledge._local_search('Quasar')],['Q99'])

    def test_reference_topic_identity_rejects_related_monument(self):
        engine, _ = make_engine(knowledge_enabled=True)
        for title, topic in [('Quasar biography','Q99'),('Monument of Quasar','Q100')]:
            engine.store.upsert('https://en.wikipedia.org/wiki/'+topic,title,
                'Quasar was a ruler. Quasar early life requires historical research.',source_type='reference',
                links=[('https://www.wikidata.org/wiki/'+topic,'Wikidata item',False)])
        engine.rebuild_index()
        with patch.object(Knowledge,'link',return_value=[Entity('Q99','Quasar',span='Quasar')]), patch('ownsearch.discover.discover',return_value=[]):
            result=engine.search('Quasar birthplace',live=True,use_cache=False)
        self.assertEqual([r['title'] for r in result['results']],['Quasar biography'])

    def test_unreviewed_category_cases_are_not_accuracy_measurements(self):
        engine, _ = make_engine()
        path = engine.root / 'unreviewed.json'
        path.write_text(json.dumps({'queries':[{'query':'unseen subject','judgments':{},'review_status':'unreviewed'}]}))
        report = evaluate(engine,load_qrels(path))
        self.assertEqual(report['queries'],0)
        self.assertEqual(report['summary'],{})


class AnswerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = make_engine()
        self.market = Market(self.engine.settings)
        self.now = int(time.time())

    def quote(self, meta):
        with patch.object(self.market,'resolve',return_value=('NVDA','Nvidia')), patch.object(self.market,'_chart',return_value={'meta':meta}):
            return self.market.quote(['Nvidia'])

    def test_quote_identity_time_currency_change_and_disclaimer(self):
        answer = self.quote({'regularMarketTime':self.now,'regularMarketPrice':110,'previousClose':100,'currency':'USD'})
        check = assess_answer(answer, {'type':'stock_quote','symbol':'NVDA','currency':'USD','scope':'regular_market','price':110,'change_pct':10}, self.now)
        self.assertTrue(check['correct'])
        self.assertTrue(answer['delayed'])

    def test_nonfinite_negative_or_future_quotes_rejected(self):
        for value in [float('nan'),float('inf'),0,-1,True]:
            self.assertIsNone(self.quote({'regularMarketTime':self.now,'regularMarketPrice':value}))
        for stamp in [float('nan'),float('inf'),self.now+600,self.now-8*86400]:
            self.assertIsNone(self.quote({'regularMarketTime':stamp,'regularMarketPrice':100}))

    def history(self, data, days=183):
        with patch.object(self.market,'resolve',return_value=('TCS.NS','Tata Consultancy Services')), patch.object(self.market,'_chart',return_value=data):
            return self.market.history(['TCS'],days)

    def full_history(self):
        ts=[self.now-n*86400 for n in range(182,-1,-1) if datetime.fromtimestamp(self.now-n*86400,timezone.utc).weekday()<5]
        return {'meta':{'regularMarketTime':self.now,'currency':'INR'},'timestamp':ts,'indicators':{'adjclose':[{'adjclose':[100+i for i in range(len(ts))]}]}}

    def test_six_month_history_has_full_window_and_correct_return(self):
        answer=self.history(self.full_history())
        self.assertIsNotNone(answer)
        analysis=answer['analysis']
        self.assertAlmostEqual(analysis['change_pct'],(analysis['end'][1]/analysis['start'][1]-1)*100)
        self.assertGreater(len(answer['series']),100)
        self.assertEqual(answer['currency'],'INR')
        self.assertIn('delayed',answer['disclaimer'])

    def test_sparse_duplicate_missing_or_future_history_rejected(self):
        base=self.full_history()
        cases=[]
        sparse=copy.deepcopy(base);sparse['timestamp']=sparse['timestamp'][-5:];sparse['indicators']['adjclose'][0]['adjclose']=[100]*5;cases.append(sparse)
        duplicate=copy.deepcopy(base);duplicate['timestamp'][1]=duplicate['timestamp'][0];cases.append(duplicate)
        missing=copy.deepcopy(base);missing['indicators']['adjclose'][0]['adjclose']=[];cases.append(missing)
        future=copy.deepcopy(base);future['timestamp'][-1]=self.now+3600;cases.append(future)
        gap=copy.deepcopy(base);gap['indicators']['adjclose'][0]['adjclose'][20:50]=[None]*30;cases.append(gap)
        for data in cases:
            self.assertIsNone(self.history(data))

    def test_wikidata_claim_is_not_an_independently_confirmed_answer(self):
        knowledge=Knowledge(self.engine.settings)
        entity=Entity('Q123','An unseen ruler',claims={'P99':[{'rank':'normal','mainsnak':{'datavalue':{'value':'Somewhere'}}}]})
        with patch.object(knowledge,'_properties',return_value={'P99':{'label':'place of birth','aliases':['birthplace'],'datatype':'string'}}):
            answer=knowledge.answer(entity,['birthplace'])
        self.assertEqual(answer['verification'],'unverified')
        self.assertIsNone(assess_answer(answer,{'type':'fact'},self.now)['correct'])
        self.assertIn('not independently verified',answer['text'])

    def test_answer_evaluation_does_not_confuse_unavailable_with_correct(self):
        self.assertEqual(assess_answer(None,{'type':'stock_quote'},self.now)['status'],'unavailable')
        self.assertEqual(assess_answer({'type':'entity','text':'Overview'}, {},self.now)['status'],'unjudged')

    def test_partial_company_match_cannot_answer_another_instrument(self):
        with patch.object(self.market,'_lookup',return_value=[{'symbol':'TCS.NS','longname':'Tata Consultancy Services','quoteType':'EQUITY'}]), patch.object(self.market,'_chart',return_value={'meta':{}}):
            self.assertEqual(self.market.resolve(['TCS','Infosys']),(None,None))

    def test_volatility_omits_intervals_with_missing_source_prices(self):
        data={'meta':{'regularMarketTime':self.now,'currency':'INR'},
              'timestamp':[self.now-n*86400 for n in range(6,-1,-1)],
              'indicators':{'quote':[{'close':[100,110,None,220,242,266.2,292.82]}]}}
        answer=self.history(data,days=7)
        self.assertIsNotNone(answer)
        self.assertAlmostEqual(answer['analysis']['volatility_pct'],0)
        self.assertEqual(answer['data_quality']['missing_prices'],1)
        self.assertEqual(answer['data_quality']['volatility_observations'],4)

    def test_market_cache_persists_without_refreshing_its_capture_time(self):
        from ownsearch.market import _cache, _lock
        key=('fixture',str(self.engine.root))
        value={'example':'dated data'}
        self.assertEqual(self.market._cached(key,60,lambda:value),value)
        stamp=self.market._last_cached_at
        with _lock: _cache.pop(key,None)
        other=Market(self.engine.settings)
        self.assertEqual(other._cached(key,60,lambda:self.fail('Persistent cache must avoid fetching')),value)
        self.assertEqual(other._last_cached_at,stamp)

    def test_previous_close_uses_exchange_calendar_day(self):
        quote_time=int(datetime.fromtimestamp(self.now-2*86400,timezone.utc).replace(hour=4,minute=0,second=0).timestamp())
        chart={'meta':{'regularMarketTime':quote_time,'regularMarketPrice':140,'exchangeTimezoneName':'Australia/Sydney'}}
        daily={'timestamp':[quote_time-2*86400-5*3600,quote_time-5*3600],
               'indicators':{'quote':[{'close':[130,140]}]}}
        with patch.object(self.market,'resolve',return_value=('EX','Example')), patch.object(self.market,'_chart',side_effect=[chart,daily]):
            answer=self.market.quote(['Example'])
        self.assertEqual(answer['previous_close'],130)
        self.assertEqual(answer['change'],10)
