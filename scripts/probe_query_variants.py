#!/usr/bin/env python3
"""Small paired live DEV probe of lexical variants on self-hosted general search."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eval.live_eval import load_dev,now
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from ownsearch.queryvariants import compact_request
from scripts.benchmark_query_md import Recorder,save_report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    cases,split=load_dev();cfg=Settings.load()
    selected=[c for c in sorted(cases,key=lambda c:hashlib.sha256(c['id'].encode()).hexdigest())
              if compact_request(c['text'])!=c['text']][:4]
    report={'scope':'Small paired live dev discovery probe, no page enrichment or relevance judgments. Not a full dev benchmark.',
            'dataset_sha256':split['dataset_sha256'],'dev_cases_considered':len(cases),'runs':[]}
    engines=[LiveSearch(replace(cfg,live_query_variants=n,vertical_providers='',brave_api_key='')) for n in (1,3)]
    for engine in engines:engine.providers=[Recorder(p) for p in engine.providers]
    for case in selected:
        row={'id':case['id'],'query':case['text'],'checked_at':now()}
        for name,engine in zip(('before','after'),engines):
            row[name]=engine.search(case['text'],use_cache=False,fetch_pages=False,explain=True)
            row[name+'_source_batches']=[b for p in engine.providers for b in p.snapshot(case['text'])]
            time.sleep(1)
        report['runs'].append(row);save_report(Path(a.output),report)
    report['summary']={'paired_queries':len(selected),'before_nonempty':sum(bool(r['before']['results']) for r in report['runs']),
                       'after_nonempty':sum(bool(r['after']['results']) for r in report['runs']),'relevance_metrics':None}
    save_report(Path(a.output),report);print(json.dumps(report['summary']))

if __name__=='__main__':main()
