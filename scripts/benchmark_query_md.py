#!/usr/bin/env python3
"""Record every query.md table case; retrieval is not workflow completion or accuracy."""
import argparse
import copy
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ownsearch.config import Settings
from ownsearch.coordinator import LiveSearch
from eval.run_eval import quantile


def cases_from_markdown(path):
    cases, category = [], ''
    for line in Path(path).read_text().splitlines():
        if line.startswith('## '):
            category = line[3:].strip()
        cells = [v.strip() for v in re.split(r'(?<!\\)\|', line)]
        if len(cells) != 5 or not re.fullmatch(r'[A-Z][0-9]{2}', cells[1]):
            continue
        case_id, query, criteria = cells[1:4]
        cases.append({'id': case_id, 'query': query.replace('`', ''), 'markdown_query': query,
                      'category': category, 'criteria': criteria,
                      'scope': 'workflow_retrieval_only' if case_id.startswith('M') else 'single_query',
                      'review_status': 'unreviewed'})
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Duplicate benchmark IDs.')
    return cases


class Recorder:
    def __init__(self, provider):
        self.source, self.name = provider, provider.name
        self.general_web = getattr(provider, 'general_web', True)
        self.rows, self.lock = [], threading.Lock()

    def search(self, request, deadline):
        batch = self.source.search(request, deadline)
        with self.lock:
            self.rows.append({'query': request.query, 'source': self.name,
                              'rows': copy.deepcopy(batch.rows), 'warnings': batch.warnings})
        return batch

    def snapshot(self, query):
        with self.lock:
            return [copy.deepcopy(row) for row in self.rows if row['query'] == query]


def summarize(runs):
    latencies = [r['response']['took_ms'] for r in runs if 'took_ms' in r['response']]
    return {'queries': len(runs), 'nonempty_queries': sum(bool(r['response'].get('results')) for r in runs),
            'queries_with_answers': sum(bool(r['response'].get('answer')) for r in runs),
            'p50_ms': quantile(latencies, .5) if latencies else None,
            'p95_ms': quantile(latencies, .95) if latencies else None,
            'reviewed_queries': 0, 'accuracy': None, 'green_flag': False}


def save_report(output, report):
    temporary = output.with_suffix(output.suffix+'.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n')
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='query.md')
    parser.add_argument('--output', required=True)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    cases = cases_from_markdown(args.input)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = json.loads(output.read_text()) if args.resume and output.exists() else {
        'started_at': datetime.now(timezone.utc).isoformat(), 'input': str(args.input),
        'scope': 'All table cases; M cases test initial retrieval only, not completed workflows.',
        'fetch_pages': args.fetch, 'runs': [], 'green_flag': False}
    if report.get('fetch_pages') != args.fetch:
        raise ValueError('Cannot resume with a different page-fetch mode.')
    lookup = {case['id']: case['query'] for case in cases}
    if any(lookup.get(run['id']) != run['query'] for run in report['runs']):
        raise ValueError('Cannot resume a different query set.')
    report.setdefault('source_sha256', {str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (Path(__file__).resolve().parents[1]/'ownsearch').rglob('*') if path.is_file() and path.suffix in ('.py', '.txt', '.tsv', '.json')})
    engine = LiveSearch(Settings.load())
    engine.providers = [Recorder(p) for p in engine.providers]
    report['configuration'] = engine.diagnostics()
    completed = {r['id'] for r in report['runs']}
    for case in cases:
        if case['id'] in completed:
            continue
        response = engine.search(case['query'], limit=10, use_cache=False,
                                 fetch_pages=args.fetch, answer_mode=True, explain=True)
        report['runs'].append({**case, 'checked_at': datetime.now(timezone.utc).isoformat(),
                               'response': response,
                               'source_batches': [batch for p in engine.providers for batch in p.snapshot(case['query'])]})
        report['summary'] = summarize(report['runs'])
        save_report(output, report)
        print(json.dumps({'id': case['id'], 'count': len(response['results']),
                          'candidates': response['total_candidates'], 'took_ms': response['took_ms'],
                          'top': [r['title'] for r in response['results'][:2]]}), flush=True)
        if args.interval > 0:
            time.sleep(args.interval)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    report['summary'] = summarize(report['runs'])
    save_report(output, report)
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
