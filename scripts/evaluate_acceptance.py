#!/usr/bin/env python3
"""Offline seven-query regression benchmark, with identical supplied entity fixtures across checkouts."""
import argparse
import importlib.util
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine-root', default=str(root))
    p.add_argument('--output', required=True)
    args = p.parse_args()
    sys.path.insert(0, str(Path(args.engine_root).resolve()))
    from ownsearch.config import Settings
    from ownsearch.engine import SearchEngine
    from ownsearch.knowledge import Knowledge, Entity
    fixture = json.loads((root / 'tests/fixtures/acceptance_relevance.json').read_text())
    settings = Settings.load(tempfile.mkdtemp(prefix='ownsearch-acceptance-'), log_queries=False,
        knowledge_enabled=True, news_feeds='', news_feeds_file='', market_chart_url='', market_lookup_url='')
    engine = SearchEngine(settings=settings)
    for doc in fixture['documents']:
        doc = dict(doc)
        if doc.pop('recent', False):
            doc['published_at'] = datetime.now(timezone.utc).isoformat()
        engine.store.upsert(**doc)
    # Adversarial boilerplate previously matched query-language and alias words.
    for n in range(350):
        engine.store.upsert(f'https://noise{n}.example/article', f'Community update {n}',
            f'The great class and program. Samrat contributor Ashok wrote comment {n}. '
            'Python programmer uses classes and inheritance. Model context news and price today.')
    engine.rebuild_index()
    spec = importlib.util.spec_from_file_location('ownsearch.acceptance_metrics', root / 'ownsearch/evaluation.py')
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    runs, per_query, elapsed = [], [], []
    for case in fixture['queries']:
        entities = [Entity(**e) for e in case['entities']]
        with patch.object(Knowledge, 'link', return_value=entities), patch('ownsearch.discover.discover', return_value=[]), patch('ownsearch.fetcher.Fetcher.fetch', side_effect=AssertionError('Network forbidden in benchmark')):
            res = engine.search(case['query'], limit=10, live=True, use_cache=False)
        keys = metrics._match(metrics._keys_for(res['results']), case['judgments'])
        row = {'query': case['query'], 'p@5': metrics.precision(keys, case['judgments'], 5),
               'mrr@10': metrics.mrr(keys, case['judgments'], 10),
               'ndcg@10': metrics.ndcg(keys, case['judgments'], 10)}
        per_query.append(row)
        runs.append(res)
    summary = {key: round(sum(row[key] for row in per_query) / len(per_query), 4) for key in ('p@5','mrr@10','ndcg@10')}
    report = {'mode':'Synthetic offline relevance benchmark; supplied entity fixtures; answers evaluated separately in tests',
              'index_documents':engine.index.doc_count,'queries':len(runs),'summary':summary,'per_query':per_query,'runs':runs}
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
