#!/usr/bin/env python3
"""Compare complete fixed-dev captures and create a NEW human review pool."""
import argparse
import csv
from collections import Counter
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from eval.live_eval import assess,blinded,digest,load_dev,load_judgments,pool_runs,review_csv,validate_report,url_key
from eval.run_eval import bootstrap
from scripts.benchmark_query_md import save_report


def paired_quality(before,after,case_ids,names):
    output={}
    for name in names:
        values=[]
        for case_id in case_ids:
            left=before[case_id]['metrics'];right=after[case_id]['metrics']
            if left is None or right is None:continue
            if left[name] is None or right[name] is None:continue
            values.append(right[name]-left[name])
        output[name]=bootstrap(values,seed=20261021)
    return output


def judgments_complete(rows):
    # Nonexistent controls can legitimately have no observed URL pool. Other
    # empty pools need reference evidence before a complete quality claim.
    return all(row['fully_judged_pool'] for row in rows if row['category']!='nonexistent_entity')


def csv_judgments(path,pool,independent=False):
    evidence={(r['id'],r['url']):r for r in pool};labels={}
    with Path(path).open(newline='',encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle):
            grade=row.get('human_grade','').strip()
            if not grade:continue
            if grade not in ('0','1','2','3'):raise ValueError('Human grade must be an integer 0–3.')
            key=(row['id'],url_key(row['url']))
            if key in labels or key not in evidence or row.get('evidence_sha256')!=evidence[key]['evidence_sha256']:
                raise ValueError('Duplicate, unknown or stale union-pool review.')
            if not all(row.get(k,'').strip() for k in ('human_rationale','human_reviewer','reviewed_at')):
                raise ValueError('Human reviews need rationale, reviewer and timestamp.')
            labels[key]={'id':key[0],'url':key[1],'evidence_sha256':row['evidence_sha256'],'grade':int(grade),
                         'judge_kind':'human','judge_id':row['human_reviewer'],'rationale':row['human_rationale'],
                         'reviewed_at':row['reviewed_at'],'independent_review':independent}
    if not labels:raise ValueError('No completed human grades found; blanks are not judgments.')
    return labels


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',default='eval/runs/baseline-dev.json')
    p.add_argument('--candidate',required=True);p.add_argument('--output',required=True)
    p.add_argument('--review-dir',required=True);p.add_argument('--judgments')
    p.add_argument('--review-csv',help='Completed CSV from the same baseline/candidate union pool.')
    p.add_argument('--independent-review',action='store_true',help='Only for a reviewer independent of development.')
    p.add_argument('--failure-injection',default='eval/runs/phase1/final-dev-preservation.json')
    p.add_argument('--tests',default='eval/runs/phase1/final-tests.txt');a=p.parse_args()
    reports=[json.loads(Path(path).read_text()) for path in (a.baseline,a.candidate)]
    cases,split=load_dev()
    for report in reports:
        validate_report(report)
        if {r['id'] for r in report['runs']}!=set(split['dev_ids']):raise ValueError('Both captures must include all fixed dev IDs.')
    pooled={}
    for report in reports:
        for row in pool_runs(report):
            key=(row['id'],row['url'])
            if key not in pooled:pooled[key]=row
            else:
                observations=pooled[key]['observations']
                observations.extend(obs for obs in row['observations'] if obs not in observations)
    pool=sorted(pooled.values(),key=lambda r:(r['id'],r['url']))
    for row in pool:row['evidence_sha256']=digest({k:row[k] for k in ('id','url','observations')})
    judgments=load_judgments(a.judgments,pool)
    if a.review_csv:judgments.update(csv_judgments(a.review_csv,pool,a.independent_review))
    metrics=[assess(report,pool,judgments) for report in reports]
    by_id=[{row['id']:row for row in m['per_query']} for m in metrics]
    real_ids=[c['id'] for c in cases if c['category']!='nonexistent_entity']
    zero_delta=bootstrap([by_id[1][i]['zero_result']-by_id[0][i]['zero_result'] for i in real_ids],seed=20261021)
    quality_delta=paired_quality(by_id[0],by_id[1],[c['id'] for c in cases],metrics[0]['quality'])
    contributions={}
    for run in reports[1]['runs']:
        for batch in run.get('source_batches',[]):
            source=batch['source'];counts=contributions.setdefault(source,Counter())
            counts['successful_batches']+=1;counts['returned_rows']+=len(batch.get('rows',[]))
        for row in run['response'].get('results',[])[:10]:
            for source in {p.get('provider') for p in row.get('provenance',[]) if p.get('provider')}:
                contributions.setdefault(source,Counter())['top10_result_contributions']+=1
    review=Path(a.review_dir)
    if review.exists():raise ValueError('Review directory exists; choose a new path to preserve human edits.')
    review.mkdir(parents=True)
    if judgments:
        (review/'judgments-dev.jsonl').write_text(''.join(json.dumps(judgments[key],ensure_ascii=False)+'\n' for key in sorted(judgments)))
    (review/'pool-dev.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in pool))
    (review/'pool-dev-blinded.json').write_text(json.dumps(blinded(pool),ensure_ascii=False,indent=2)+'\n')
    review_csv(review/'human_review_queue.csv',pool,judgments,candidates=True,fraction=1)
    review_csv(review/'human_review_candidates.csv',pool,judgments,candidates=True)
    failure=json.loads(Path(a.failure_injection).read_text())
    test_text=Path(a.tests).read_text();test_count=re.search(r'Ran (\d+) tests',test_text)
    all_tests=bool(test_count and test_text.rstrip().endswith('OK'))
    grade_ready=(all(v['value'] is not None for v in quality_delta.values())
                 and all(judgments_complete(m['per_query']) for m in metrics))
    gates={'all_tests_pass':all_tests,'two_source_failure_injection_pass':failure['two_source_failure_injection_passed'],
           'dev_zero_result_rate_drops_excluding_nonexistent':zero_delta['value']<0,
           'recall_improves':quality_delta['recall@10']['value']>0 if grade_ready else None,
           'strict_p5_does_not_regress':quality_delta['strict_p@5']['value']>=0 if grade_ready else None,
           'judged_quality_comparison_available':grade_ready}
    gates['passed']=all(value is True for value in gates.values())
    report={'scope':'Fixed dev captures at different times; live provider availability is a confound. No sealed query was read or run.',
            'baseline':metrics[0],'candidate':metrics[1],'paired_zero_rate_delta_excluding_nonexistent':zero_delta,
            'paired_quality_deltas':quality_delta,'source_contributions':contributions,'phase1_gate':gates,
            'tests_passed':int(test_count.group(1)) if all_tests else None,
            'review_directory':str(review),'existing_review_files_modified':False,'sealed_queries_run':0,
            'configuration_note':'Candidate free/keyless supplements only. Paid sources and denied arXiv disabled; local general source retained.',
            'limitations':['Pool growth, successful API requests and nonempty results are not accuracy scores.',
                           'Missing human grades remain null; no quality gate is implicitly passed.',
                           'Warm repeats retain the configured cache policy; upstream/OS caches are uncontrolled.']}
    save_report(Path(a.output),report)
    print(json.dumps({'gate':gates,'zero_rate_before':metrics[0]['zero_result_rate_excluding_nonexistent_entity'],
                      'zero_rate_after':metrics[1]['zero_result_rate_excluding_nonexistent_entity'],
                      'pool_rows':len(pool)},indent=2))

if __name__=='__main__':main()
