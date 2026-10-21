#!/usr/bin/env python3
"""Controlled direct-crawl benchmark and fixed DEV parsing; no sealed query access."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ownsearch.coordinator import IndependentSearch
from ownsearch.fetcher import Fetcher
from ownsearch.query import parse_query
from tests.independent_fixture import Site
from tests.test_independent import settings


def quantile(values,p):
    ordered=sorted(values)
    if not ordered:return None
    x=(len(ordered)-1)*p;i=int(x)
    return ordered[i]+(ordered[min(i+1,len(ordered)-1)]-ordered[i])*(x-i)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='eval/runs/independent/fixture-baseline.json')
    args=parser.parse_args(argv)
    dev=ROOT/'eval/dev.jsonl'
    rows=[json.loads(line) for line in dev.read_text().splitlines() if line.strip()]
    parse_times=[]
    for row in rows:
        start=time.perf_counter();parse_query(row['text']);parse_times.append((time.perf_counter()-start)*1000)
    checksums={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [dev,ROOT/'eval/splits.json',ROOT/'eval/human_review_queue.csv',ROOT/'eval/human_review_candidates.csv']}
    cases=[('orbital guidance','/',['/guide','/mapped'],{}),
           ('orbital guidance','/feed',['/guide','/mapped'],{}),
           ('"orbital guidance"','/',['/guide','/mapped'],{}),
           ('orbital guidance','/pdf',['/pdf'],{'filetype':'pdf'}),
           ('orbital guidance','/office',['/office'],{'filetype':'docx'}),
           ('orbital guidance','/image',['/image'],{'search_type':'images'}),
           ('orbital guidance','/video',['/video'],{'search_type':'video'}),
           ('orbital guidance','/foreign',['/foreign'],{'lang':'hi'}),
           ('orbital guidance','/guide',['/guide','/mapped'],{'freshness':'day'}),
           ('unfindable synthetic entity','/guide',[],{}),
           ('orbital guidance -spacecraft','/guide',[],{})]
    measured=[]
    with Site() as site:
        for query,start_path,positive_paths,kw in cases:
            engine=IndependentSearch(settings())
            empty=engine.search(query,fetch_pages=False,**kw)
            cold=engine.search(query,seeds=[site.base+start_path],**kw)
            with patch.object(Fetcher,'_request_once',side_effect=AssertionError('warm cache made request')):
                warm=engine.search(query,fetch_pages=False,**kw)
            expected={site.base+p for p in positive_paths}
            actual=[r['url'] for r in cold['results']]
            warm_actual=[r['url'] for r in warm['results']]
            recall=len(set(actual[:10])&expected)/len(expected) if expected else None
            # Strict precision always uses denominator five, even for short lists.
            precision=len(set(actual[:5])&expected)/5
            measured.append({'query':query,'starting_path':start_path,'filters':kw,
                             'expected_paths':positive_paths,'result_paths':[u.removeprefix(site.base) for u in actual],
                             'empty_cache_results':len(empty['results']),'cold_ms':cold['took_ms'],'warm_ms':warm['took_ms'],
                             'requests':cold['coverage']['requests'],'warm_requests':warm['coverage']['requests'],
                             'warm_signature_preserved':actual==warm_actual,'recall_at_10':recall,
                             'strict_precision_at_5':precision,'negative_control_passed':not actual if not expected else None})
    report={'scope':'Controlled synthetic website only. Not live web accuracy or human relevance judgments.',
            'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'runtime_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'ownsearch').rglob('*.py')))).hexdigest(),
            'dev_queries_parsed':len(rows),'dev_parse_p50_ms':quantile(parse_times,.5),'dev_parse_p95_ms':quantile(parse_times,.95),
            'preserved_fingerprints':checksums,'sealed_queries_used':0,
            'case_count':len(measured),'positive_cases':sum(r['recall_at_10'] is not None for r in measured),
            'fixture_mean_recall_at_10':statistics.mean(r['recall_at_10'] for r in measured if r['recall_at_10'] is not None),
            'fixture_mean_strict_precision_at_5':statistics.mean(r['strict_precision_at_5'] for r in measured),
            'cold_p50_ms':quantile([r['cold_ms'] for r in measured],.5),
            'cold_p95_ms':quantile([r['cold_ms'] for r in measured],.95),
            'warm_p50_ms':quantile([r['warm_ms'] for r in measured],.5),
            'warm_p95_ms':quantile([r['warm_ms'] for r in measured],.95),
            'warm_requests':sum(r['warm_requests'] for r in measured),
            'all_warm_signatures_preserved':all(r['warm_signature_preserved'] for r in measured),
            'negative_controls_passed':all(r['negative_control_passed'] for r in measured if r['negative_control_passed'] is not None),
            'live_relevance_metrics':None,'cases':measured}
    output=Path(args.output)
    if output.exists():raise SystemExit('Refusing to overwrite an earlier benchmark; choose a new output')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
