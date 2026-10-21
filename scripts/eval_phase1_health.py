#!/usr/bin/env python3
"""Fixed-dev source replay with two denied HTTP sources; no public network calls."""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eval.live_eval import validate_report
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from ownsearch.fetcher import Fetcher, FetchResult
from ownsearch.webproviders import JsonProvider, SourceBatch


def measure(recorded, base):
    calls=Counter(); statuses=Counter(); signatures=[]; current={}
    class Fixture(base):
        def __init__(self,cfg,name): super().__init__(cfg);self.name=name
        def search(self,request,deadline):
            value=self.request(request,'https://api.example.org/'+self.name,deadline)
            return SourceBatch(value['rows'])
    def fetch(client,url,**kwargs):
        name=url.rsplit('/',1)[-1];calls[name]+=1
        return FetchResult(url,url,403 if name!='healthy' else 200,{},
                           b'' if name!='healthy' else json.dumps({'rows':current['rows']}).encode())
    with tempfile.TemporaryDirectory() as tmp:
        cfg=Settings.load(tmp,searxng_url='',brave_api_key='',news_feeds='',news_feeds_file='',market_lookup_url='',market_chart_url='',
                          provider_min_interval=0,provider_cooldown=3600,provider_request_budget=10000,provider_budget_window=3600)
        engine=LiveSearch(cfg,[Fixture(cfg,n) for n in ('denied_one','denied_two','healthy')])
        with patch.object(Fetcher,'fetch',fetch):
            for run in recorded['runs']:
                current['rows']=[row for batch in run.get('source_batches',[]) for row in batch['rows']][:40]
                result=engine.search(run['query'],use_cache=False,fetch_pages=False,answer_mode=False)
                statuses.update(s['provider']+':'+s['status'] for s in result['provider_status'])
                signatures.append({'id':run['id'],'urls':[row['url'] for row in result['results']]})
    return {'actual_fixture_http_calls':dict(calls),'provider_status_counts':dict(statuses),
            'queries_with_results':sum(bool(r['urls']) for r in signatures),'per_query':signatures}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    source=ROOT/'eval/runs/baseline-dev.json';data=source.read_bytes();recorded=json.loads(data);validate_report(recorded)
    old=types.ModuleType('ownsearch._phase1_baseline');sys.modules[old.__name__]=old;old.__package__='ownsearch'
    exec(compile(subprocess.check_output(['git','show','b02f1dd:ownsearch/webproviders.py'],cwd=ROOT),'<baseline-provider>','exec'),old.__dict__)
    before=measure(recorded,old.JsonProvider);after=measure(recorded,JsonProvider)
    assert before['per_query']==after['per_query']
    assert after['queries_with_results']>0
    report={'scope':'Offline fixed-dev source replay; two injected HTTP 403 sources plus one healthy recorded-source fixture. Not live web accuracy.',
            'recorded_sha256':hashlib.sha256(data).hexdigest(),'dev_queries':len(recorded['runs']),
            'before':before,'after':after,'two_source_failure_injection_passed':True,
            'ranked_url_signatures_preserved':True,'relevance_metrics':None,'sealed_queries_run':0}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('dev_queries','two_source_failure_injection_passed','ranked_url_signatures_preserved')}))
    print(json.dumps({'before_calls':before['actual_fixture_http_calls'],'after_calls':after['actual_fixture_http_calls']}))

if __name__=='__main__':main()
