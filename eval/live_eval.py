#!/usr/bin/env python3
"""Phase-0 live capture and judging. Normal commands can read only the fixed dev split."""
import argparse
import copy
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.run_eval import bootstrap, fingerprint, quantile
from scripts.benchmark_query_md import Recorder, save_report


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_dev(directory=ROOT / 'eval'):
    directory = Path(directory)
    split = json.loads((directory / 'splits.json').read_text())
    data = (directory / 'dev.jsonl').read_bytes()
    if hashlib.sha256(data).hexdigest() != split['dev_sha256']:
        raise ValueError('Dev dataset fingerprint changed.')
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(split['dev_ids']) or set(ids) & set(split['sealed_ids']):
        raise ValueError('Dev IDs must exactly match the frozen split and exclude every sealed ID.')
    return rows, split


def validate_report(report, directory=ROOT / 'eval'):
    cases, split = load_dev(directory)
    by_id = {c['id']: c for c in cases}
    if report.get('dataset_sha256') != split['dataset_sha256']:
        raise ValueError('Run belongs to a different dataset version.')
    ids = [r['id'] for r in report['runs']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate recorded query IDs.')
    for row in report['runs']:
        if row['id'] not in by_id or row['query'] != by_id[row['id']]['text']:
            raise ValueError('Only matching development queries can be assessed before Phase 5.')
    return by_id


def record(args):
    from ownsearch.config import Settings
    from ownsearch.coordinator import LiveSearch
    cases, split = load_dev()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not args.resume:
        raise ValueError('Recording already exists; use --resume or a new output path.')
    if not 0 <= args.warm_fraction <= 1 or not math.isfinite(args.interval) or args.interval < 1:
        raise ValueError('Use a warm fraction from 0 to 1 and at least one second between network searches.')
    settings = Settings.load()
    if settings.live_local_enabled:
        raise ValueError('Baseline must use live discovery without the optional local corpus.')
    # Do not save credentials or private configuration. This fingerprint prevents
    # mixing configurations during a resumed run without exposing secret values.
    config_hash = digest({k: str(v) for k, v in asdict(settings).items()})
    engine_hash = fingerprint(ROOT)
    protocol = {'fetch_pages': not args.no_fetch, 'answer_mode': True, 'limit': 10,
                'interval_seconds': args.interval, 'warm_fraction': args.warm_fraction,
                'warm_definition': 'Immediate repeat in the same process, using the unchanged configured cache policy; OS/upstream caches uncontrolled.',
                'cold_definition': 'First request for this case, OwnSearch response cache bypassed; OS/upstream caches uncontrolled.',
                'configured_response_cache_ttl_seconds': settings.live_cache_ttl,
                'configured_response_cache_entries': settings.live_cache_entries}
    report = json.loads(output.read_text()) if output.exists() else {
        'schema': 'ownsearch-live-eval-v1', 'split': 'dev', 'started_at': now(),
        'baseline_git_hash': subprocess.check_output(['git', 'rev-parse', 'baseline-v0'], cwd=ROOT, text=True).strip(),
        'code_git_hash': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'engine_fingerprint': engine_hash, 'configuration_sha256': config_hash,
        'dataset_sha256': split['dataset_sha256'], 'protocol': protocol,
        'expected_queries': len(cases), 'runs': [], 'judgment_status': 'unjudged',
        'independent_review': False}
    validate_report(report)
    if (report['engine_fingerprint'], report['configuration_sha256'], report['protocol']) != (engine_hash, config_hash, protocol):
        raise ValueError('Engine, settings or capture protocol changed; do not mix baselines.')
    completed = {row['id'] for row in report['runs']}
    warm_ids = {c['id'] for c in sorted(cases, key=lambda c: digest(c['id']))[:math.ceil(len(cases) * args.warm_fraction)]}
    report['warm_ids'] = sorted(warm_ids)
    report['sessions'] = report.get('sessions', []) + [{'started_at': now(), 'resumed': bool(completed)}]
    with tempfile.TemporaryDirectory(prefix='ownsearch-live-eval-') as isolated:
        # No local data writes; keep the loaded provider settings and safe-fetch limits.
        from dataclasses import replace
        engine = LiveSearch(replace(settings, data_dir=Path(isolated)))
        engine.providers = [Recorder(p) for p in engine.providers]
        if not engine.providers:
            raise ValueError('No general discovery provider configured; cannot record a usable live baseline.')
        report['configuration'] = engine.diagnostics()
        save_report(output, report)
        for case in cases:
            if case['id'] in completed:
                continue
            for provider in engine.providers:
                with provider.lock:
                    provider.rows.clear()
            kwargs = dict(limit=10, fetch_pages=not args.no_fetch, answer_mode=True, explain=True)
            started = time.perf_counter()
            cold = engine.search(case['text'], use_cache=False, **kwargs)
            row = {'id': case['id'], 'query': case['text'], 'category': case['category'],
                   'language': case['language'], 'checked_at': now(), 'response': cold,
                   'cold_wall_ms': (time.perf_counter() - started) * 1000,
                   'source_batches': [b for p in engine.providers for b in p.snapshot(case['text'])]}
            if case['id'] in warm_ids:
                time.sleep(args.interval)
                # A cache-enabled installation needs a normal prime because
                # use_cache=False intentionally does not populate the response cache.
                if settings.live_cache_ttl > 0:
                    prime = engine.search(case['text'], use_cache=True, **kwargs)
                    row['warm_prime_response'] = prime
                    time.sleep(args.interval)
                started = time.perf_counter()
                row['warm_response'] = engine.search(case['text'], use_cache=True, **kwargs)
                row['warm_wall_ms'] = (time.perf_counter() - started) * 1000
                row['warm_checked_at'] = now()
            report['runs'].append(row)
            report['complete'] = len(report['runs']) == len(cases)
            report['updated_at'] = now()
            save_report(output, report)
            print(json.dumps({'completed': len(report['runs']), 'total': len(cases), 'id': case['id'],
                              'results': len(cold['results']), 'cold_ms': round(row['cold_wall_ms'], 2),
                              'warm_ms': round(row['warm_wall_ms'], 2) if 'warm_wall_ms' in row else None}), flush=True)
            time.sleep(args.interval)
    report['completed_at'] = now()
    save_report(output, report)


def url_key(url):
    """Conservative identity for judging only; no query parameters are discarded."""
    if not isinstance(url, str):
        raise ValueError('URL must be text.')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Absolute HTTP(S) evidence URL required.')
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))


def pool_runs(report, extras=()):
    cases = validate_report(report)
    pooled = {}

    def add(case_id, result, source, rank, timestamp):
        key = (case_id, url_key(result['url']))
        item = pooled.setdefault(key, {'id': case_id, 'query': cases[case_id]['text'], 'url': key[1],
                                      'observations': [], 'review_status': 'unjudged',
                                      'independent_review': False})
        observation = {'source': source, 'rank': rank, 'timestamp': timestamp,
                       **{k: result[k] for k in ('title', 'snippet', 'published_at', 'fetched_at', 'fetch_status', 'provenance') if k in result}}
        if observation not in item['observations']:
            item['observations'].append(observation)

    for row in report['runs']:
        for rank, result in enumerate(row['response'].get('results', [])[:10], 1):
            add(row['id'], result, 'ownsearch', rank, row['checked_at'])
        for batch in row.get('source_batches', []):
            for rank, result in enumerate(batch.get('rows', [])[:10], 1):
                if result.get('url'):
                    add(row['id'], result, batch['source'], rank, row['checked_at'])
    for extra in extras:
        if extra.get('id') not in cases or extra.get('query') != cases[extra['id']]['text']:
            raise ValueError('Extra source must use a matching dev query.')
        if not extra.get('source') or not extra.get('checked_at'):
            raise ValueError('Extra source requires its name and real observation timestamp.')
        for rank, result in enumerate(extra.get('results', [])[:10], 1):
            add(extra['id'], result, extra['source'], rank, extra['checked_at'])
    rows = sorted(pooled.values(), key=lambda row: (row['id'], row['url']))
    for row in rows:
        row['evidence_sha256'] = digest({'id': row['id'], 'url': row['url'], 'observations': row['observations']})
    return rows


def load_judgments(path, pool):
    evidence = {(r['id'], r['url']): r for r in pool}
    judgments = {}
    for row in jsonl(path) if path else []:
        key = (row['id'], url_key(row['url']))
        if key not in evidence or row.get('evidence_sha256') != evidence[key]['evidence_sha256']:
            raise ValueError('Judgment must match a pooled query, URL and evidence fingerprint.')
        if key in judgments or type(row.get('grade')) is not int or not 0 <= row['grade'] <= 3:
            raise ValueError('Duplicate judgments or non-integer/out-of-range grades are invalid.')
        if row.get('judge_kind') not in ('human', 'llm') or not row.get('judge_id') or not row.get('rationale'):
            raise ValueError('Judgments require judge_kind, judge_id and a rationale.')
        if type(row.get('independent_review')) is not bool or (row['judge_kind'] == 'llm' and row['independent_review']):
            raise ValueError('LLM grades are always explicitly not independently verified.')
        if 'fabricated_url' in row and (type(row['fabricated_url']) is not bool or not row.get('url_audit_evidence')):
            raise ValueError('URL fabrication audits need a boolean finding and explicit evidence.')
        judgments[key] = row
    return judgments


def relevance(urls, grades):
    """Unjudged rows are never implicitly treated as grade zero."""
    top = urls[:10]
    if any(url not in grades for url in top) or not grades:
        return None
    positives = {u for u, g in grades.items() if g > 0}
    seen = set()
    effective = []
    for url in top:
        effective.append(grades[url] if url not in seen else 0)
        seen.add(url)
    gains = [2 ** grade - 1 for grade in effective]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(sorted(grades.values(), reverse=True)[:10]))
    return {'recall@10': len(set(top) & positives) / len(positives) if positives else None,
            'ndcg@10': dcg / ideal if ideal else 0.0,
            'mrr@10': next((1 / i for i, grade in enumerate(effective, 1) if grade > 0), 0.0),
            'p@5': sum(grade > 0 for grade in effective[:5]) / 5,
            'strict_p@5': sum(grade >= 2 for grade in effective[:5]) / 5}


def assess(report, pool, judgments, samples=1000, seed=20261021):
    cases = validate_report(report)
    pool_ids = {}
    for row in pool:
        pool_ids.setdefault(row['id'], []).append(row['url'])
    rows = []
    audits = []
    audit_total = 0
    for run in report['runs']:
        case_id = run['id']
        urls = [url_key(r['url']) for r in run['response'].get('results', [])[:10]]
        pool_urls = pool_ids.get(case_id, [])
        grades = {u: judgments[(case_id, u)]['grade'] for u in pool_urls if (case_id, u) in judgments}
        fully_judged = bool(pool_urls) and len(grades) == len(pool_urls)
        metrics = relevance(urls, grades) if fully_judged else None
        row = {'id': case_id, 'category': cases[case_id]['category'],
               'returned': len(urls), 'pool_size': len(pool_urls), 'pool_judged': len(grades),
               'fully_judged_pool': fully_judged, 'zero_result': int(not urls),
               'cold_ms': run['cold_wall_ms'], 'warm_ms': run.get('warm_wall_ms'),
               'warm_cache_hit': run.get('warm_response', {}).get('cached', False),
               'metrics': metrics}
        rows.append(row)
        for url in set(urls):
            audit_total += 1
            judgment = judgments.get((case_id, url), {})
            if 'fabricated_url' in judgment:
                audits.append(int(judgment['fabricated_url']))
    def ci(values, statistic=None):
        kwargs = {'samples': samples, 'seed': seed}
        return bootstrap(values, statistic=statistic, **kwargs) if statistic else bootstrap(values, **kwargs)
    quality = {name: ci([r['metrics'][name] for r in rows if r['metrics'] is not None])
               for name in ('recall@10', 'ndcg@10', 'mrr@10', 'p@5', 'strict_p@5')}
    latency = {mode: {f'p{p}_ms': ci([r[f'{mode}_ms'] for r in rows], lambda xs, p=p: quantile(xs, p / 100))
                      for p in (50, 95, 99)} for mode in ('cold', 'warm')}
    statuses = {}
    for run in report['runs']:
        for status in run['response'].get('provider_status', []):
            key = status['provider'] + ':' + status['status']
            statuses[key] = statuses.get(key, 0) + 1
    # Provenance consistency is not proof of URL existence or nonfabrication.
    gaps = []
    for run in report['runs']:
        for result in run['response'].get('results', [])[:10]:
            if not any(p.get('url') == result['url'] for p in result.get('provenance', [])):
                gaps.append({'id': run['id'], 'url': result['url']})
    return {'schema': 'ownsearch-live-metrics-v1', 'dataset_sha256': report['dataset_sha256'],
            'engine_fingerprint': report['engine_fingerprint'], 'split': 'dev',
            'recorded_queries': len(rows), 'expected_queries': report['expected_queries'],
            'complete': len(rows) == report['expected_queries'], 'bootstrap_samples': samples, 'seed': seed,
            'quality': quality, 'latency': latency,
            'zero_result_rate': ci([r['zero_result'] for r in rows]),
            'zero_result_rate_excluding_nonexistent_entity': ci([r['zero_result'] for r in rows if r['category'] != 'nonexistent_entity']),
            'judgment_coverage': {'pooled_urls': len(pool), 'graded_urls': len(judgments),
                                  'fully_judged_queries': sum(r['fully_judged_pool'] for r in rows),
                                  'independently_reviewed_urls': sum(j['independent_review'] for j in judgments.values())},
            'fabricated_url_count': sum(audits) if audit_total and len(audits) == audit_total else None,
            'url_audit': {'audited_returned_urls': len(audits), 'total_returned_urls': audit_total,
                          'confirmed_fabrications': sum(audits), 'unaudited': audit_total - len(audits)},
            'url_provenance_gap_count': len(gaps), 'url_provenance_gaps': gaps,
            'provider_status_counts': statuses, 'protocol': report['protocol'],
            'limitations': ['Relevance is conditional on the observed pool, not all relevant internet pages.',
                            'Only completely judged query pools enter quality metrics; all-zero pools contribute zero except undefined recall.',
                            'Developer-authored split and LLM judgments are not independent evaluation.',
                            'Fabricated-URL count requires explicit URL audits; provenance alone does not verify existence.',
                            'Cold means response-cache bypass, not flushed operating-system or upstream caches.',
                            'Warm means a repeated query under the unchanged cache configuration; inspect actual cache hits.',
                            'Latency bootstrap resamples queries; temporal provider dependence is not modeled.'],
            'per_query': rows}


def review_csv(path, pool, judgments, seed=20261021, candidates=False, fraction=.1):
    path = Path(path)
    if path.exists():
        with path.open(newline='', encoding='utf-8-sig') as handle:
            if any(any(row.get(k, '').strip() for k in ('human_grade', 'human_rationale', 'human_reviewer', 'reviewed_at'))
                   for row in csv.DictReader(handle)):
                raise ValueError(f'{path} contains human edits; copy/import those reviews before regenerating.')
    available = [r for r in pool if ((r['id'], r['url']) in judgments) != candidates]
    selected = random.Random(seed).sample(available, math.ceil(len(available) * fraction))
    selected.sort(key=lambda r: (r['id'], r['url']))
    fields = ['id', 'query', 'url', 'title', 'snippet', 'evidence_sha256', 'grade', 'judge_kind',
              'judge_id', 'independent_review', 'rationale', 'human_grade', 'human_rationale', 'human_reviewer', 'reviewed_at']
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            label = judgments.get((row['id'], row['url']), {})
            obs = row['observations'][0]
            cells = {**{k: row[k] for k in ('id', 'query', 'url', 'evidence_sha256')},
                     'title': obs.get('title', ''), 'snippet': obs.get('snippet', ''),
                     **{k: label[k] for k in fields if k in label}}
            # Retrieved titles/snippets can be spreadsheet formulas. Keep raw
            # evidence in the JSONL pool; make the review CSV safe to open.
            writer.writerow({k: "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@'))
                             else value for k, value in cells.items()})
    return len(selected)


def blinded(pool):
    return [{'id': r['id'], 'query': r['query'], 'url': r['url'], 'evidence_sha256': r['evidence_sha256'],
             'evidence': [{k: o[k] for k in ('title', 'snippet', 'published_at', 'fetched_at', 'fetch_status') if k in o}
                          for o in r['observations']]} for r in pool]


def metrics_command(args):
    if args.bootstrap_samples < 100:
        raise ValueError('At least 100 bootstrap samples required.')
    report = json.loads(Path(args.recorded).read_text())
    extra = [row for path in args.extra_source for row in jsonl(path)]
    pool = pool_runs(report, extra)
    judgments = load_judgments(args.judgments, pool)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pool_path = output.parent / 'pool-dev.jsonl'
    pool_path.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in pool))
    (output.parent / 'pool-dev-blinded.json').write_text(json.dumps(blinded(pool), ensure_ascii=False, indent=2) + '\n')
    result = assess(report, pool, judgments, args.bootstrap_samples, args.seed)
    review = review_csv(ROOT / 'eval/human_review.csv', pool, judgments, args.seed)
    candidates = review_csv(ROOT / 'eval/human_review_candidates.csv', pool, judgments, args.seed, candidates=True)
    queued = review_csv(ROOT / 'eval/human_review_queue.csv', pool, judgments, args.seed, candidates=True, fraction=1)
    result['review_sample'] = {'judgments_sampled': review, 'unjudged_candidates_sampled': candidates,
                               'unjudged_queue': queued, 'seed': args.seed, 'fraction': .1}
    result['phase0_gate'] = {
        'dataset_and_split': True, 'complete_dev_capture': result['complete'],
        'all_query_pools_judged': all(r['fully_judged_pool'] for r in result['per_query']),
        'quality_metrics_available': all(v['value'] is not None for v in result['quality'].values())}
    result['phase0_gate']['passed'] = all(result['phase0_gate'].values())
    save_report(output, result)
    print(json.dumps({k: result[k] for k in ('recorded_queries', 'quality', 'zero_result_rate', 'phase0_gate')}, indent=2))


def judge_command(args):
    report = json.loads(Path(args.recorded).read_text())
    pool = pool_runs(report, [row for path in args.extra_source for row in jsonl(path)])
    if Path(args.output).exists():
        raise ValueError('Judge output exists; choose a new path to preserve labels.')
    # Caller explicitly configures their own judge. No provider or paid API is selected.
    payload = {'rubric': (ROOT / 'eval/RUBRIC.md').read_text(), 'rows': blinded(pool)}
    with tempfile.TemporaryFile(mode='w+') as stdin, tempfile.TemporaryFile(mode='w+') as stdout:
        json.dump(payload, stdin, ensure_ascii=False)
        stdin.seek(0)
        subprocess.run(shlex.split(args.command), stdin=stdin, stdout=stdout, timeout=300, check=True)
        stdout.seek(0)
        labels = json.load(stdout)
    if not isinstance(labels, list):
        raise ValueError('Configured judge must return a JSON array of labels.')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for row in labels:
        row.update(judge_kind='llm', independent_review=False)
    # Validate before publishing the result.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'labels.jsonl'
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in labels))
        load_judgments(path, pool)
        output.write_bytes(path.read_bytes())
    print(json.dumps({'judgments': len(labels), 'independent_review': False, 'output': str(output)}))


def import_review(args):
    report = json.loads(Path(args.recorded).read_text())
    pool = pool_runs(report, [row for path in args.extra_source for row in jsonl(path)])
    labels = load_judgments(args.existing_judgments, pool)
    evidence = {(r['id'], r['url']): r for r in pool}
    output = Path(args.output)
    if output.exists():
        raise ValueError('Output exists; choose a new path to preserve judgment history.')
    added = 0
    with Path(args.csv).open(newline='', encoding='utf-8-sig') as handle:
        seen = set()
        for row in csv.DictReader(handle):
            if not row.get('human_grade', '').strip():
                continue
            if row['human_grade'].strip() not in ('0', '1', '2', '3'):
                raise ValueError('Human grades must be integers 0–3 or blank.')
            key = (row['id'], url_key(row['url']))
            if key in seen or key not in evidence or row.get('evidence_sha256') != evidence[key]['evidence_sha256']:
                raise ValueError('Duplicate, unknown or stale review row.')
            if not all(row.get(k, '').strip() for k in ('human_rationale', 'human_reviewer', 'reviewed_at')):
                raise ValueError('Completed reviews need a rationale, reviewer and review timestamp.')
            seen.add(key)
            labels[key] = {'id': key[0], 'url': key[1], 'evidence_sha256': row['evidence_sha256'],
                           'grade': int(row['human_grade']), 'judge_kind': 'human',
                           'judge_id': row['human_reviewer'], 'rationale': row['human_rationale'],
                           'reviewed_at': row['reviewed_at'], 'independent_review': args.independent_review}
            added += 1
    if not added:
        raise ValueError('No completed human grades found; blank rows are not judgments.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        checked = Path(tmp) / 'labels.jsonl'
        checked.write_text(''.join(json.dumps(labels[key], ensure_ascii=False) + '\n' for key in sorted(labels)))
        load_judgments(checked, pool)
        output.write_bytes(checked.read_bytes())
    print(json.dumps({'human_grades_imported': added, 'total_grades': len(labels), 'output': str(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    capture = commands.add_parser('record')
    capture.add_argument('--output', default=str(ROOT / 'eval/runs/baseline-dev.json'))
    capture.add_argument('--resume', action='store_true')
    capture.add_argument('--interval', type=float, default=1.0)
    capture.add_argument('--warm-fraction', type=float, default=.1)
    capture.add_argument('--no-fetch', action='store_true')
    capture.set_defaults(func=record)
    for name, function in (('metrics', metrics_command), ('judge', judge_command), ('import-review', import_review)):
        command = commands.add_parser(name)
        command.add_argument('--recorded', default=str(ROOT / 'eval/runs/baseline-dev.json'))
        command.add_argument('--extra-source', action='append', default=[])
        command.add_argument('--output', default=str(ROOT / f'eval/runs/{"baseline-dev-metrics.json" if name == "metrics" else "judgments-dev.jsonl"}'))
        command.set_defaults(func=function)
        if name == 'metrics':
            command.add_argument('--judgments')
            command.add_argument('--bootstrap-samples', type=int, default=1000)
            command.add_argument('--seed', type=int, default=20261021)
        elif name == 'judge':
            command.add_argument('--command', required=True, help='Explicit local LLM judge adapter; JSON on stdin/stdout, no shell.')
        else:
            command.add_argument('--csv', required=True)
            command.add_argument('--existing-judgments')
            command.add_argument('--independent-review', action='store_true', help='Use only for a reviewer independent of development.')
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
