#!/usr/bin/env python3
"""Record live results and evaluate reviewed judgments, never development scores as accuracy.

Input JSONL: {"id","query","language","category","review_status":"reviewed|unreviewed",
"judgments":{"https://...":0..3},"answer_correct":true|false|null,"citations_supported":true|false|null}
Leave judgments unreviewed until an independent reviewer has inspected the sources.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from ownsearch.evaluation import mrr, ndcg, precision, recall
from eval.run_eval import bootstrap, quantile


def assess(runs, judgments):
    reviewed, answers, citations, abstentions, task_outcomes = [], [], [], [], []
    for run in runs:
        case = judgments[run['id']]
        # Answer/citation labels have a separate denominator from page relevance.
        actual_hash = hashlib.sha256(json.dumps(run['response'].get('answer'), sort_keys=True).encode()).hexdigest()
        if case.get('answer_sha256') == actual_hash and run['response'].get('answer'):
            if type(case.get('answer_correct')) is bool:
                answers.append(int(case['answer_correct']))
            if type(case.get('citations_supported')) is bool:
                citations.append(int(case['citations_supported']))
        if case.get('review_status') != 'reviewed':
            continue
        if type(case.get('task_success')) is bool:
            task_outcomes.append(int(case['task_success']))
        if case.get('expected_empty') is True:
            abstentions.append(int(not run['response']['results'] and not run['response'].get('answer')))
            continue
        grades = case.get('judgments')
        if not isinstance(grades, dict) or not grades:
            continue
        if any(type(v) is not int or not 0 <= v <= 3 for v in grades.values()):
            raise ValueError('Reviewed relevance grades must be integers 0–3.')
        urls = [r['url'] for r in run['response']['results']]
        reviewed.append({'id': run['id'], 'top5_useful': int(any(grades.get(u, 0) > 0 for u in urls[:5])),
                         'precision@5': precision(urls, grades, 5), 'recall@10': recall(urls, grades, 10),
                         'mrr@10': mrr(urls, grades, 10),
                         'ndcg@10': ndcg(urls, grades, 10) if any(grades.values()) else None,
                         'judgment_coverage': sum(url in grades for url in urls[:10])/max(1, len(urls[:10]))})
    return {'reviewed_queries': len(reviewed), 'metrics': {
        metric: bootstrap([r[metric] for r in reviewed if r[metric] is not None])
        for metric in ('top5_useful', 'precision@5', 'recall@10', 'mrr@10', 'ndcg@10')},
        'answer_correctness': bootstrap(answers), 'citation_support': bootstrap(citations),
        'abstention_correctness': bootstrap(abstentions),
        'task_success': bootstrap(task_outcomes),
        'judgment_coverage': bootstrap([r['judgment_coverage'] for r in reviewed]),
        'per_query': reviewed}


def release_gate(report, cases, minimum_reviewed=100, target=.90, p95_limit_ms=1000):
    """A qualified benchmark verdict, never a guarantee about arbitrary future queries."""
    reasons = []
    runs = report.get('runs', [])
    labels = [cases[run['id']] for run in runs]
    reviewed = [case for case in labels if case.get('review_status') == 'reviewed'
                and type(case.get('task_success')) is bool]
    if len(reviewed) != len(labels) or len(reviewed) < minimum_reviewed:
        reasons.append('Insufficient complete task-level judgments for the recorded query set.')
    if not reviewed or any(case.get('independent_review') is not True for case in reviewed):
        reasons.append('Independent review is missing; developer/AI self-review cannot certify the target.')
    task_score = report.get('evaluation', {}).get('task_success', {}).get('value')
    if task_score is None or task_score < target:
        reasons.append('Reviewed task success does not meet the declared target.')
    latency = report.get('latency', {}).get('p95_ms')
    if not isinstance(latency, (float, int)) or not math.isfinite(latency) or latency > p95_limit_ms:
        reasons.append('Recorded cold p95 latency does not meet the declared limit.')
    if any(case.get('scope') == 'workflow_retrieval_only' and case.get('workflow_completed') is not True for case in reviewed):
        reasons.append('Initial workflow retrieval is not a completed workflow.')
    return {'passed': not reasons, 'scope': 'The recorded and independently reviewed benchmark only.',
            'minimum_reviewed': minimum_reviewed, 'task_success_target': target,
            'cold_p95_limit_ms': p95_limit_ms, 'reasons': reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queries', required=True, help='JSONL queries and independently reviewed URL judgments')
    parser.add_argument('--output', required=True)
    parser.add_argument('--recorded', help='assess an existing recorded JSON report without changing the evidence')
    parser.add_argument('--no-fetch', action='store_true')
    parser.add_argument('--answer', action='store_true')
    parser.add_argument('--minimum-reviewed', type=int, default=100)
    parser.add_argument('--target', type=float, default=.90)
    parser.add_argument('--p95-limit-ms', type=float, default=1000)
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between uncached queries; respect provider quotas')
    args = parser.parse_args()
    if args.minimum_reviewed < 1 or not math.isfinite(args.target) or not 0 < args.target <= 1 or not math.isfinite(args.p95_limit_ms) or args.p95_limit_ms <= 0:
        raise ValueError('Review count, quality target and latency limit must be finite and positive.')
    rows = [json.loads(line) for line in Path(args.queries).read_text().splitlines() if line.strip()]
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Queries must be nonempty with distinct IDs.')
    by_id = {r['id']: r for r in rows}
    if args.recorded:
        report = json.loads(Path(args.recorded).read_text())
        runs = report['runs']
        if any(run['id'] not in by_id or run['query'] != by_id[run['id']]['query'] for run in runs):
            raise ValueError('Judgments must describe the same recorded queries.')
    else:
        engine = LiveSearch(Settings.load())
        report = {'scope': 'Uncached live search with local corpus disabled; independent review required.',
                  'configuration': engine.diagnostics(), 'runs': [], 'general_live_integration': 'not_configured' if not engine.providers else 'attempted'}
        runs = report['runs']
        for case in rows:
            response = engine.search(case['query'], limit=10, use_cache=False, fetch_pages=not args.no_fetch,
                                     answer_mode=args.answer, lang=case.get('language_filter'),
                                     preferred_language=case.get('language'), timezone_name=case.get('timezone'))
            answer_hash = hashlib.sha256(json.dumps(response.get('answer'), sort_keys=True).encode()).hexdigest()
            runs.append({'id': case['id'], 'query': case['query'], 'language': case.get('language'),
                         'category': case.get('category'), 'answer_sha256': answer_hash, 'response': response})
            if engine.providers and args.interval > 0:
                time.sleep(args.interval)
    report['evaluation'] = assess(runs, by_id)
    latency = [r['response']['took_ms'] for r in runs]
    report['latency'] = {'sample_size': len(latency), 'cache': 'disabled',
                         'p50_ms': quantile(latency, .5), 'p95_ms': quantile(latency, .95)}
    report['release_gate'] = release_gate(report, by_id, args.minimum_reviewed, args.target, args.p95_limit_ms)
    report['green_flag'] = report['release_gate']['passed']
    report['limitation'] = 'A verdict applies only to the recorded benchmark. Broader generalization requires a diverse independent holdout; retrieval relevance, direct-answer correctness and task completion are separate.'
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'output': args.output, 'reviewed_queries': report['evaluation']['reviewed_queries'],
                      'runs': len(runs), 'general_live_integration': report.get('general_live_integration'), 'green_flag': report['green_flag']}))


if __name__ == '__main__':
    main()
