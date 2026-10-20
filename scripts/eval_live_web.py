#!/usr/bin/env python3
"""Record live results and evaluate reviewed judgments, never development scores as accuracy.

Input JSONL: {"id","query","language","category","review_status":"reviewed|unreviewed",
"judgments":{"https://...":0..3},"answer_correct":true|false|null,"citations_supported":true|false|null}
Leave judgments unreviewed until an independent reviewer has inspected the sources.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from ownsearch.evaluation import mrr, ndcg, precision, recall
from eval.run_eval import bootstrap, quantile


def assess(runs, judgments):
    reviewed, answers, citations = [], [], []
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
        grades = case.get('judgments')
        if not isinstance(grades, dict) or not grades or not any(type(v) is int and v > 0 for v in grades.values()):
            continue
        if any(type(v) is not int or not 0 <= v <= 3 for v in grades.values()):
            raise ValueError('Reviewed relevance grades must be integers 0–3.')
        urls = [r['url'] for r in run['response']['results']]
        reviewed.append({'id': run['id'], 'top5_useful': int(any(grades.get(u, 0) > 0 for u in urls[:5])),
                         'precision@5': precision(urls, grades, 5), 'recall@10': recall(urls, grades, 10),
                         'mrr@10': mrr(urls, grades, 10), 'ndcg@10': ndcg(urls, grades, 10)})
    return {'reviewed_queries': len(reviewed), 'metrics': {
        metric: bootstrap([r[metric] for r in reviewed])
        for metric in ('top5_useful', 'precision@5', 'recall@10', 'mrr@10', 'ndcg@10')},
        'answer_correctness': bootstrap(answers), 'citation_support': bootstrap(citations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queries', required=True, help='JSONL queries and independently reviewed URL judgments')
    parser.add_argument('--output', required=True)
    parser.add_argument('--recorded', help='assess an existing recorded JSON report without changing the evidence')
    parser.add_argument('--no-fetch', action='store_true')
    parser.add_argument('--answer', action='store_true')
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between uncached queries; respect provider quotas')
    args = parser.parse_args()
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
    report['green_flag'] = False
    report['limitation'] = 'No general accuracy claim. Initial milestone requires 300–500 diverse independently judged holdout queries; report categories/languages and failures separately.'
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'output': args.output, 'reviewed_queries': report['evaluation']['reviewed_queries'],
                      'runs': len(runs), 'general_live_integration': report.get('general_live_integration'), 'green_flag': False}))


if __name__ == '__main__':
    main()
