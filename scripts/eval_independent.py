#!/usr/bin/env python3
"""DEV-only independent recordings, pooled review and honest judged metrics.

Never reads eval/queries.jsonl. No judge or search service is invoked.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261021


def digest(data):
    return hashlib.sha256(data).hexdigest()


def runtime_fingerprint(root):
    paths = sorted((root / 'ownsearch').rglob('*.py')) + [root / 'sources.txt', root / 'pyproject.toml']
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in paths if p.exists()}


def load_dev():
    # Only the unsealed DEV file and split IDs are opened. No alternate dataset option.
    splits = json.loads((ROOT / 'eval/splits.json').read_text())
    rows = [json.loads(l) for l in (ROOT / 'eval/dev.jsonl').read_text().splitlines() if l.strip()]
    ids = [r['id'] for r in rows]
    allowed = set(splits.get('dev', splits.get('dev_ids', [])))
    if not allowed:
        # Split files may name the ID lists under a nested mapping.
        allowed = set(splits.get('splits', {}).get('dev', []))
    if len(rows) != 300 or len(set(ids)) != 300 or set(ids) != allowed:
        raise ValueError('DEV IDs do not match the frozen split')
    return rows


def quantile(values, p):
    ordered = sorted(values)
    if not ordered:
        return None
    x = (len(ordered) - 1) * p
    i = int(x)
    return ordered[i] + (ordered[min(i + 1, len(ordered) - 1)] - ordered[i]) * (x - i)


def ci(values, metric=None):
    if not values:
        return None
    metric = metric or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(SEED)
    samples = [metric(rng.choices(values, k=len(values))) for _ in range(1000)]
    return {'value': metric(values), 'ci95': [quantile(samples, .025), quantile(samples, .975)], 'n': len(values)}


def csv_safe(value):
    value = str(value or '')
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def evidence(row):
    return digest(json.dumps({k: row.get(k) for k in ('url', 'title', 'content', 'published_at', 'language')},
                             sort_keys=True, ensure_ascii=False).encode())


def read_records(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def pool_rows(records):
    pool = {}
    for record in records:
        pages = record.get('pages', [])
        for page in pages:
            item = page.get('item')
            if not item:
                continue
            key = (record['id'], item['url'], evidence(item))
            pool[key] = {'id': record['id'], 'query': record['query'], 'url': item['url'],
                         'title': item['title'], 'content': item.get('content', ''),
                         'published_at': item.get('published_at'), 'fetched_at': item.get('fetched_at'),
                         'evidence_sha256': key[2]}
    return pool


def read_grades(paths, pool):
    grades = {}
    for path in paths:
        with Path(path).open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                value = (row.get('human_grade') or '').strip()
                if not value:
                    continue
                key = (row['id'], row['url'], row['evidence_sha256'])
                if key not in pool:
                    raise ValueError('Review does not match captured evidence')
                if value not in ('0', '1', '2', '3') or not all((row.get(k) or '').strip() for k in ('human_reviewer', 'reviewed_at', 'human_rationale')):
                    raise ValueError('Incomplete or invalid human judgment')
                grade = int(value)
                if key in grades and grades[key] != grade:
                    raise ValueError('Conflicting human grades require explicit adjudication')
                grades[key] = grade
    return grades


def judged_metrics(records, pool, grades):
    by_query = {}
    for key, row in pool.items():
        by_query.setdefault(key[0], []).append((key, row))
    values = {k: [] for k in ('strict_p_at_5', 'ndcg_at_10', 'recall_at_10', 'mrr_at_10')}
    known_direct, known_absent, complete_queries = set(), set(), 0
    for record in records:
        rows = by_query.get(record['id'], [])
        own_keys = {(record['id'], page['item']['url'], evidence(page['item']))
                    for page in record.get('pages', []) if page.get('item')}
        if any(grades.get(key, -1) >= 2 for key in own_keys):
            known_direct.add(record['id'])
        elif own_keys and all(key in grades for key in own_keys):
            known_absent.add(record['id'])
        if not rows or any(key not in grades for key, _ in rows):
            continue
        complete_queries += 1
        # Multiple observations may disagree; complete pools use the strongest
        # captured relevance for a URL, while keeping raw grades auditable.
        qrels = {}
        for key, row in rows:
            qrels[row['url']] = max(qrels.get(row['url'], 0), grades[key])
        urls, seen = [], set()
        for item in record['cold'].get('results', [])[:10]:
            url = item['url']
            if url in seen:
                urls.append(None)
            else:
                urls.append(url)
                seen.add(url)
        captured_grades = {page['item']['url']: grades.get((record['id'], page['item']['url'], evidence(page['item'])), 0)
                           for page in record.get('pages', []) if page.get('item')}
        ranked = [captured_grades.get(url, 0) for url in urls]
        values['strict_p_at_5'].append(sum(g >= 2 for g in ranked[:5]) / 5)
        dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ranked))
        ideal = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(sorted(qrels.values(), reverse=True)[:10]))
        values['ndcg_at_10'].append(dcg / ideal if ideal else 0)
        positives = {u for u, g in qrels.items() if g > 0}
        if positives:
            values['recall_at_10'].append(len({url for url, grade in zip(urls, ranked) if grade > 0} & positives) / len(positives))
        values['mrr_at_10'].append(next((1/(i+1) for i, g in enumerate(ranked) if g > 0), 0))
    count = len(records)
    complete = count > 0 and len(known_direct | known_absent) == count
    ceiling = [int(r['id'] in known_direct) for r in records] if complete else []
    return {**{name: ci(xs) for name, xs in values.items()},
            'fully_judged_queries': complete_queries, 'human_graded_pairs': len(grades),
            'unjudged_pairs': len(pool)-len(grades),
            'coverage_ceiling': ci(ceiling),
            'coverage_ceiling_bounds': [len(known_direct)/count, 1-len(known_absent)/count] if count else None,
            'coverage_ceiling_scope': 'Observed fetched pool with grade >=2, not unrestricted web reachability',
            'reason_if_unmeasured': 'Human relevance grades are missing; unjudged is not irrelevant.' if not complete else None}


def report(directory, review_csvs=(), extras=(), output=None):
    directory = Path(directory)
    records = read_records(directory / 'records.jsonl.gz')
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate recorded DEV IDs')
    extra_records = [row for name in extras for row in read_records(Path(name) / 'records.jsonl.gz')]
    pool = pool_rows(records + extra_records)
    grades = read_grades(review_csvs, pool)
    timings = {}
    for mode in ('cold', 'warm_live', 'warm_cache_only'):
        xs = [r[mode]['client_ms'] for r in records if mode in r and not r[mode].get('error')]
        timings[mode] = {f'p{int(p*100)}_ms': ci(xs, lambda values, p=p: quantile(values, p)) for p in (.5, .95, .99)}
    zero = [int(not r['cold'].get('results')) for r in records]
    in_scope = [r for r in records if r['category'] != 'nonexistent_entity']
    summary = {'recorded_queries': len(records), 'expected_dev_queries': 300, 'complete': len(records) == 300,
               'nonempty_queries': sum(not z for z in zero), 'zero_result_rate': ci(zero),
               'zero_result_rate_excluding_nonexistent_controls': ci([int(not r['cold'].get('results')) for r in in_scope]),
               'fetch_coverage_proxy': ci([int(any(p.get('item') for p in r.get('pages', []))) for r in records]),
               'fetch_coverage_proxy_note': 'At least one fetched page, irrespective of relevance; not the coverage ceiling.',
               'errors': sum(bool(r['cold'].get('error')) for r in records),
               'timing': timings, 'relevance': judged_metrics(records, pool, grades),
               'sealed_queries_used': 0}
    destination = Path(output) if output else directory
    destination.mkdir(parents=True, exist_ok=True)
    review = destination / 'review'
    review.mkdir(exist_ok=True)
    target = review / 'human_review_queue.csv'
    if target.exists():
        with target.open(newline='') as f:
            if any((r.get('human_grade') or '').strip() for r in csv.DictReader(f)):
                raise ValueError('Refusing to overwrite human review edits; choose a new report directory')
    fields = ['id','query','url','title','snippet','evidence_sha256','human_grade','human_rationale','human_reviewer','reviewed_at']
    ordered = sorted(pool.items())
    sample = random.Random(SEED).sample(ordered, math.ceil(len(ordered)*.1))
    details = {}
    for review_csv in review_csvs:
        with Path(review_csv).open(newline='', encoding='utf-8') as source:
            for row in csv.DictReader(source):
                if (row.get('human_grade') or '').strip():
                    details[(row['id'], row['url'], row['evidence_sha256'])] = row
    for name, selected in [('human_review_queue.csv', ordered), ('human_review_candidates.csv', sample)]:
        with (review / name).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields);writer.writeheader()
            for key, row in selected:
                writer.writerow({**{k: csv_safe(row.get(k, '')) for k in ('id','query','url','title','evidence_sha256')},
                                 'snippet': csv_safe(row['content'][:2000]), 'human_grade': grades.get(key, ''),
                                 **{k: csv_safe(details.get(key, {}).get(k, '')) for k in ('human_rationale','human_reviewer','reviewed_at')}})
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    return summary


def record(args):
    root = Path(args.runtime_root).resolve()
    sys.path.insert(0, str(root))
    from ownsearch.config import Settings
    from ownsearch.coordinator import IndependentSearch
    from ownsearch.webfetch import OriginState
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_dev()
    overrides = json.loads(Path(args.settings_json).read_text()) if args.settings_json else {}
    if not isinstance(overrides, dict) or any(key in overrides for key in ('data_dir','sources_file','allow_private_hosts')):
        raise ValueError('Unsupported capture overrides')
    manifest = {'runtime_files': runtime_fingerprint(root),
                'dev_sha256': digest((ROOT/'eval/dev.jsonl').read_bytes()),
                'protocol': {'concurrency': args.concurrency, 'global_fetch_workers': 4,
                             'search_timeout_ms': args.timeout_ms, 'cold': 'New page cache for each query; shared robots/politeness state',
                             'warm_live': 'Immediate live repeat for stable-hash-selected 10% subset',
                             'warm_cache_only': 'Immediate cache-only repeat for every query; distinct from warm_live',
                             'timezone': 'Asia/Kolkata', 'overrides': overrides, 'os_and_upstream_caches_controlled': False},
                'started_at': datetime.now(timezone.utc).isoformat(), 'python': sys.version}
    manifest_path = directory/'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if any(old[k] != manifest[k] for k in ('runtime_files','dev_sha256','protocol')):
            raise ValueError('Cannot resume under changed runtime, source registry or protocol')
        manifest = old
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')
    path = directory/'records.jsonl.gz'
    prior = read_records(path) if path.exists() else []
    done = {r['id'] for r in prior}
    rows = [r for r in rows if r['id'] not in done]
    if args.limit:
        rows = rows[:args.limit]
    cfg = Settings(sources_file=str(root/'sources.txt'), search_timeout_ms=args.timeout_ms,
                   timezone='Asia/Kolkata', data_dir=Path(tempfile.mkdtemp(prefix='ownsearch-eval-config-')), **overrides)
    manifest_path.write_text(json.dumps({**manifest, 'settings': {k: str(v) for k,v in vars(cfg).items()}}, indent=2)+'\n')
    origins, workers = OriginState(cfg.origin_cache_entries), threading.BoundedSemaphore(4)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    def one(row):
        if stop.is_set():
            return None
        engine = IndependentSearch(cfg)
        engine.origins, engine.workers = origins, workers
        result = {'id': row['id'], 'query': row['text'], 'category': row['category'],
                  'captured_at': datetime.now(timezone.utc).isoformat()}
        for mode in ('cold','warm_cache_only','warm_live'):
            if mode == 'warm_live' and int(digest(row['id'].encode()),16) % 10:
                continue
            start = time.perf_counter()
            try:
                response = engine.search(row['text'], limit=10, answer_mode=True,
                                         fetch_pages=mode != 'warm_cache_only', use_cache=True)
            except Exception as error:
                response = {'results': [], 'error': type(error).__name__+': '+str(error)}
            response['client_ms'] = (time.perf_counter()-start)*1000
            result[mode] = response
            if mode == 'cold':
                result['pages'] = [asdict(page) for page in engine.cache.snapshot()]
        engine.close()
        return result
    with gzip.open(path, 'at', encoding='utf-8') as stream:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(one,row) for row in rows]
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    continue
                stream.write(json.dumps(result,ensure_ascii=False)+'\n');stream.flush()
                done.add(result['id'])
                if len(done) % 10 == 0 or len(done) == 300:
                    print(json.dumps({'recorded':len(done),'last_id':result['id'],'last_result_count':len(result['cold']['results'])}),flush=True)
    if stop.is_set():
        (directory/'STOPPED.json').write_text(json.dumps({'recorded':len(done),'reason':'Capture stopped by signal; queued queries were not executed.'})+'\n')
    print(json.dumps(report(directory),indent=2),flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    rec = sub.add_parser('record')
    rec.add_argument('--runtime-root',default=str(ROOT))
    rec.add_argument('--output',required=True)
    rec.add_argument('--concurrency',type=int,choices=(1,2,3,4),default=1)
    rec.add_argument('--timeout-ms',type=int,default=12000)
    rec.add_argument('--settings-json', help='Explicit experimental settings; recorded in protocol')
    rec.add_argument('--limit',type=int,default=0,help='Diagnostic partial capture; never presented as full DEV')
    rep = sub.add_parser('report')
    rep.add_argument('directory')
    rep.add_argument('--review-csv',action='append',default=[])
    rep.add_argument('--extra-run',action='append',default=[])
    rep.add_argument('--report-output',help='New review/report directory; preserves edited CSVs')
    args = parser.parse_args(argv)
    if args.command == 'record':record(args)
    else:print(json.dumps(report(args.directory,args.review_csv,args.extra_run,args.report_output),indent=2))
    return 0

if __name__ == '__main__':raise SystemExit(main())
