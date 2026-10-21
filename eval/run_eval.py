#!/usr/bin/env python3
"""Versioned retrieval evaluation; offline by default, with query-bootstrap uncertainty."""
import argparse
import hashlib
import json
import platform
import random
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from unittest.mock import patch


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    left = int(position)
    return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (position - left)


def bootstrap(values, statistic=statistics.mean, samples=1000, seed=20261020):
    values = [v for v in values if v is not None]
    if not values:
        return {'value': None, 'ci95': None, 'queries': 0}
    rng = random.Random(seed)
    draws = [statistic(rng.choices(values, k=len(values))) for _ in range(samples)]
    return {'value': round(statistic(values), 6),
            'ci95': [round(quantile(draws, p), 6) for p in (0.025, 0.975)], 'queries': len(values)}


def summarize(rows, samples=1000, seed=20261020):
    result = {'queries': len(rows), 'answerable_queries': sum(not r['expected_empty'] for r in rows)}
    for metric in ('p@5', 'p@5_ceiling', 'recall@10', 'mrr@10', 'ndcg@10',
                   'zero_result_rate', 'empty_query_correct'):
        result[metric] = bootstrap([r[metric] for r in rows], samples=samples, seed=seed)
    for percentile in (50, 95, 99):
        result[f'latency_p{percentile}_ms'] = bootstrap([r['latency_ms'] for r in rows],
            lambda values, p=percentile: quantile(values, p / 100), samples, seed)
    attempts = [r for r in rows if r['discovery_attempted']]
    result['live_discovery_success_rate'] = bootstrap(
        [r['discovery_success'] for r in attempts], samples=samples, seed=seed)
    return result


def load_queries(path, documents=None):
    queries, seen = [], set()
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        if q.get('review_status') == 'unreviewed':
            continue
        if not q.get('id') or q['id'] in seen or not q.get('query') or not q.get('language'):
            raise ValueError('Each query needs a unique id, query text, and explicit language label.')
        seen.add(q['id'])
        grades = q.get('judgments', {})
        if any(type(g) is not int or not 0 <= g <= 3 for g in grades.values()):
            raise ValueError('Judgment grades must be integers from 0 to 3.')
        empty = not any(grades.values())
        if q.get('expected_empty') is not empty:
            raise ValueError('Explicit expected_empty must agree with the relevance judgments.')
        if documents is not None and any(u not in documents for u in grades):
            raise ValueError(f"Judgment URL missing from fixture corpus: {q['id']}")
        queries.append(q)
    if not queries:
        raise ValueError('No reviewed query judgments are available.')
    return queries


def fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted((root / 'ownsearch').rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.tsv', '.txt'):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run(args):
    root = Path(args.engine_root).resolve()
    sys.path.insert(0, str(root))
    from ownsearch.config import Settings
    from ownsearch.engine import SearchEngine
    from ownsearch.evaluation import precision, recall, mrr, ndcg, _keys_for, _match
    import ownsearch.engine as engine_module
    import ownsearch.dates as dates_module
    import ownsearch.query as query_module
    import ownsearch.discover as discovery_module

    corpus_path, query_path = Path(args.corpus), Path(args.queries)
    corpus = json.loads(corpus_path.read_text(encoding='utf-8'))
    cases = load_queries(query_path, None if args.live else {d['url'] for d in corpus['documents']})
    if args.live and (not args.data_dir or any(q.get('judgment_scope') != 'real_web' for q in cases)):
        raise ValueError('--live requires --data-dir and separate real_web judgments; synthetic fixtures cannot verify the web.')
    as_of = datetime.fromisoformat(corpus['as_of']).astimezone(timezone.utc)
    stamp = as_of.timestamp()

    class EvaluationDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(stamp, tz)

    stage_times = defaultdict(list)
    discoveries = []

    def timed(label, fn):
        @wraps(fn)
        def call(*a, **kw):
            start = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                stage_times[label].append((time.perf_counter() - start) * 1000)
        return call

    def discovered(*a, **kw):
        # Count actual calls, including failures, rather than inferring success
        # from result count or pretending an offline run contacted a provider.
        outcome = {'success': False}
        discoveries.append(outcome)
        result = original_discover(*a, **kw)
        outcome['success'] = any(r.get('result') in ('ok', 'cached') for r in result)
        return result

    original_discover = discovery_module.discover
    with tempfile.TemporaryDirectory(prefix='ownsearch-eval-') as tmp, ExitStack() as stack:
        settings = Settings.load(args.data_dir or tmp, log_queries=False)
        if not args.live:
            settings = Settings.load(tmp, log_queries=False, knowledge_enabled=False,
                news_feeds='', news_feeds_file='', market_lookup_url='', market_chart_url='',
                searxng_url='', brave_api_key='', financial_provider_url='')
            stack.enter_context(patch('ownsearch.fetcher.Fetcher.fetch', side_effect=AssertionError('Offline evaluation forbids network access')))
            stack.enter_context(patch.object(query_module, 'datetime', EvaluationDateTime))
            stack.enter_context(patch.object(dates_module, 'datetime', EvaluationDateTime))
            stack.enter_context(patch.object(time, 'time', return_value=stamp))
        engine = SearchEngine(settings=settings)
        build_start = time.perf_counter()
        if not args.live:
            for original in corpus['documents']:
                doc = dict(original)
                days = doc.pop('published_days_ago', None)
                if days is not None:
                    doc['published_at'] = (as_of - timedelta(days=days)).isoformat()
                engine.store.upsert(**doc)
            engine.rebuild_index()
        build_ms = (time.perf_counter() - build_start) * 1000
        index_bytes = sum(p.stat().st_size for p in settings.index_dir.rglob('*') if p.is_file())
        for attribute, label in [('parse_query', 'query_parse_and_intent'), ('retrieve', 'candidate_retrieval'),
                                 ('positional_features', 'positional_features'), ('passages', 'passage_selection')]:
            stack.enter_context(patch.object(engine_module, attribute, timed(label, getattr(engine_module, attribute))))
        for attribute, label in [('features', 'document_metadata'), ('texts', 'document_text_reads')]:
            stack.enter_context(patch.object(engine.store, attribute, timed(label, getattr(engine.store, attribute))))
        stack.enter_context(patch.object(discovery_module, 'discover', discovered))
        measurements = defaultdict(list)
        runs, first_pass = {}, {}
        for repeat in range(args.repeats):
            for case in cases:
                start = time.perf_counter()
                prior = len(discoveries)
                res = engine.search(case['query'], limit=10, fetch_evidence=False,
                    use_cache=False, live=args.live, **case.get('params', {}))
                ms = (time.perf_counter() - start) * 1000
                measurements[case['id']].append(ms)
                keys = _match(_keys_for(res['results']), case['judgments'])
                empty = case['expected_empty']
                row = {**{k: case[k] for k in ('id', 'query', 'language', 'categories', 'expected_empty')},
                    'p@5': None if empty else precision(keys, case['judgments'], 5),
                    'p@5_ceiling': None if empty else min(5, sum(g > 0 for g in case['judgments'].values())) / 5,
                    'recall@10': None if empty else recall(keys, case['judgments'], 10),
                    'mrr@10': None if empty else mrr(keys, case['judgments'], 10),
                    'ndcg@10': None if empty else ndcg(keys, case['judgments'], 10),
                    'zero_result_rate': int(not res['results']),
                    'empty_query_correct': int(not res['results']) if empty else None,
                    'latency_ms': ms, 'result_urls': [r['url'] for r in res['results']],
                    'provider_errors': res.get('provider_errors', []),
                    'discovery_attempted': len(discoveries) > prior,
                    'discovery_success': int(any(d['success'] for d in discoveries[prior:]))}
                previous = runs.get(case['id'])
                if previous and not args.live and previous['result_urls'] != row['result_urls']:
                    raise ValueError('Result ordering changed between repeats; inspect temporal or external nondeterminism.')
                if previous:
                    row['discovery_attempted'] |= previous['discovery_attempted']
                    row['discovery_success'] |= previous['discovery_success']
                    row['provider_errors'] = list(dict.fromkeys(previous['provider_errors'] + row['provider_errors']))
                if repeat == 0:
                    first_pass[case['id']] = ms
                runs[case['id']] = row
        rows = list(runs.values())
        for row in rows:
            values = measurements[row['id']]
            row.update(latency_ms=statistics.median(values), first_pass_ms=first_pass[row['id']],
                       repeat_latencies_ms=values)
        per_language = {language: summarize([r for r in rows if r['language'] == language], args.bootstrap_samples, args.seed)
                        for language in sorted({r['language'] for r in rows})}
        stages = sorted([{'stage': label, 'calls': len(times), 'total_ms': round(sum(times), 3),
                          'call_p95_ms': round(quantile(times, .95), 3)} for label, times in stage_times.items()],
                        key=lambda stage: stage['total_ms'], reverse=True)
        return {'schema_version': 1, 'mode': 'live' if args.live else 'offline_synthetic',
            'engine_identity_sha256': fingerprint(root), 'python': platform.python_version(), 'platform': platform.platform(),
            'corpus_sha256': hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            'queries_sha256': hashlib.sha256(query_path.read_bytes()).hexdigest(),
            'evaluation_time_utc': as_of.isoformat() if not args.live else datetime.now(timezone.utc).isoformat(),
            'index_documents': engine.index.doc_count, 'index_bytes': index_bytes, 'fixture_build_ms': round(build_ms, 3),
            'repeats': args.repeats, 'bootstrap_samples': args.bootstrap_samples, 'seed': args.seed,
            'summary': summarize(rows, args.bootstrap_samples, args.seed), 'per_language': per_language,
            'profile': stages, 'per_query': rows,
            'notes': ['Ranking metrics exclude expected-empty cases; abstention is evaluated separately.',
                      'Precision@5 uses denominator 5. Its judgment ceiling is reported, not relabeled accuracy.',
                      '95% percentile bootstrap resamples queries within each reported language; small samples are uncertain.',
                      'Latency uses each query median across repeats; first-pass values remain available. Python/OS caches are not reset.',
                      'Stage timings include instrumentation overhead and describe this small corpus, not production-scale capacity.',
                      'Offline live-discovery success is null: no provider was contacted. No fact or financial-answer accuracy is inferred.',
                      'Fixtures are reused development judgments, not a held-out open-web or language-support certification.']}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-root', default=str(root))
    parser.add_argument('--queries', default=str(root / 'eval/legacy/queries.jsonl'))
    parser.add_argument('--corpus', default=str(root / 'eval/corpus.json'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--bootstrap-samples', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=20261020)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    if args.repeats < 1 or args.bootstrap_samples < 100:
        parser.error('Use at least one repeat and 100 bootstrap samples.')
    if args.data_dir and not args.live:
        parser.error('Offline evaluation always creates a disposable index; --data-dir is for explicit live runs.')
    report = run(args)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
