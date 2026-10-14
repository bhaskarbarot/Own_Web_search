#!/usr/bin/env python3
"""Run a reviewable acceptance report; never assigns a green flag automatically."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ownsearch.config import Settings
from ownsearch.engine import SearchEngine
from ownsearch.answer_evaluation import assess_answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, help='use a separate acceptance index')
    parser.add_argument('--output', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--budget', type=float, default=Settings().discovery_timeout)
    parser.add_argument('--query', action='append', help='run only this query; repeat to select several')
    parser.add_argument('--answer-judgments', help='optional separately reviewed answer expectations in JSON')
    args = parser.parse_args()
    settings = Settings.load(args.data_dir, discovery_timeout=args.budget, fetch_timeout=5,
                             log_queries=False, user_agent=Settings().user_agent)
    engine = SearchEngine(settings=settings)
    cases = json.loads(Path(__file__).resolve().parents[1].joinpath('tests/relevance_hosts.json').read_text())
    runs = []
    answer_judgments = json.loads(Path(args.answer_judgments).read_text()) if args.answer_judgments else {}
    for item in cases['queries']:
        if args.query and item['query'] not in args.query:
            continue
        result = engine.search(item['query'], limit=5, live=args.live, use_cache=False)
        result['answer_assessment'] = assess_answer(result.get('answer'), answer_judgments.get(item['query'], {}), time.time())
        runs.append(result)
        print(f"{item['query']}: {len(result['results'])} results; answer={(result.get('answer') or {}).get('type')}; low_confidence={result['coverage']['low_confidence']}; {result['took_ms']} ms", flush=True)
    Path(args.output).write_text(json.dumps({'live': args.live, 'green_flag': False,
        'review_required': 'Verify answer correctness, market identity and timestamps, publication dates, and the web-search comparison.',
        'runs': runs}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
