#!/usr/bin/env python3
"""Evaluate either checkout using the same URL/host metrics and a frozen local corpus."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main():
    own_root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine-root', default=str(own_root))
    p.add_argument('--data-dir', required=True)
    p.add_argument('--qrels', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    sys.path.insert(0, str(Path(args.engine_root).resolve()))
    from ownsearch.config import Settings
    from ownsearch.engine import SearchEngine
    settings = Settings.load(args.data_dir, log_queries=False, news_feeds='', news_feeds_file='',
                             market_chart_url='', market_lookup_url='', knowledge_enabled=False)
    engine = SearchEngine(settings=settings)
    spec = importlib.util.spec_from_file_location('ownsearch.comparison_metrics', own_root / 'ownsearch/evaluation.py')
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    report = metrics.evaluate(engine, metrics.load_qrels(args.qrels))
    report['index_documents'] = engine.index.doc_count
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
