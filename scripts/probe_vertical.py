#!/usr/bin/env python3
"""Probe stable-hash-selected applicable DEV cases with one official API adapter."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eval.live_eval import load_dev
from ownsearch.config import Settings
from ownsearch.query import parse_query
from ownsearch.webquery import conservative_intent
from ownsearch.webmodels import WebRequest
from ownsearch.vertical import ADAPTERS


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--provider',required=True);p.add_argument('--output',required=True)
    p.add_argument('--max-queries',type=int,default=2);a=p.parse_args()
    cases,split=load_dev();cfg=Settings.load();provider=ADAPTERS[a.provider](cfg)
    report={'provider':a.provider,'scope':'Small real official-API DEV probe, not accuracy or a full dev benchmark.',
            'dataset_sha256':split['dataset_sha256'],'dev_cases_considered':len(cases),'eligible_cases':0,'runs':[]}
    requests=[]
    for c in sorted(cases,key=lambda c:hashlib.sha256(c['id'].encode()).hexdigest()):
        req=WebRequest(c['text'],conservative_intent(parse_query(c['text'])),threading.Event())
        if provider.accepts(req): report['eligible_cases']+=1;requests.append((c,req))
    for case,req in requests[:a.max_queries]:
        started=time.perf_counter()
        row={'id':case['id'],'query':case['text'],'checked_at':datetime.now(timezone.utc).isoformat()}
        try:
            batch=provider.search(req,time.monotonic()+8)
            row.update(status='ok',rows=batch.rows,warnings=batch.warnings)
        except Exception as e: row.update(status=getattr(e,'status','error'),error=type(e).__name__+': '+str(e),rows=[])
        row.update(elapsed_ms=round((time.perf_counter()-started)*1000,2),health=provider.health_snapshot())
        report['runs'].append(row)
        # Do not repeat an API denial or wait out a server suspension in a probe.
        if row['health']['circuit']=='open':break
        time.sleep(max(1,getattr(provider,'minimum_interval',1)))
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'provider':a.provider,'considered':300,'eligible':report['eligible_cases'],
                      'attempted':len(report['runs']),'statuses':[r['status'] for r in report['runs']],
                      'returned_rows':sum(len(r['rows']) for r in report['runs'])}))

if __name__=='__main__':main()
