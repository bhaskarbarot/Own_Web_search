#!/usr/bin/env python3
"""Fixed-dev frozen-source ablation of query normalization, without live claims."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eval.live_eval import validate_report
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from ownsearch.webproviders import SourceBatch
from ownsearch.queryvariants import compact_request,variants
from ownsearch.query import parse_query
from ownsearch.webmodels import WebRequest
import threading


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    raw=(ROOT/'eval/runs/baseline-dev.json').read_bytes();recorded=json.loads(raw);cases=validate_report(recorded)
    report={'scope':'All fixed dev queries, identical recorded source rows for every variant. Measures parsing/fusion only, not new live retrieval or relevance.',
            'recorded_sha256':hashlib.sha256(raw).hexdigest(),'dev_queries':len(cases),'sealed_queries_run':0,'runs':[]}
    active={}
    class Frozen:
        name='recorded';general_web=True
        def search(self,request,deadline):
            return SourceBatch([dict(row,source_query=request.query) for row in active['rows']])
    with tempfile.TemporaryDirectory() as tmp:
        cfg=Settings.load(tmp,searxng_url='',brave_api_key='',news_feeds='',news_feeds_file='',market_lookup_url='',market_chart_url='',
                          provider_min_interval=0,discovery_provider_timeout=1,live_early_results=50)
        engines=[LiveSearch(replace(cfg,live_query_variants=n),[Frozen()]) for n in (1,3)]
        for run in recorded['runs']:
            active['rows']=[row for batch in run.get('source_batches',[]) for row in batch['rows']][:40]
            results=[engine.search(run['query'],use_cache=False,fetch_pages=False) for engine in engines]
            choices=variants(WebRequest(run['query'],parse_query(run['query']),threading.Event()))
            report['runs'].append({'id':run['id'],'compacted':compact_request(run['query'])!=run['query'],
                                   'variants':choices,'before_urls':[r['url'] for r in results[0]['results']],
                                   'after_urls':[r['url'] for r in results[1]['results']]})
    report['summary']={'before_nonempty':sum(bool(r['before_urls']) for r in report['runs']),
                       'after_nonempty':sum(bool(r['after_urls']) for r in report['runs']),
                       'compacted_queries':sum(r['compacted'] for r in report['runs']),
                       'with_variants':sum(len(r['variants'])>1 for r in report['runs']),
                       'original_query_preserved':all(r['variants'][0]==run['query'] for r,run in zip(report['runs'],recorded['runs'])),
                       'relevance_metrics':None}
    Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report['summary']))

if __name__=='__main__':main()
