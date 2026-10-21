#!/usr/bin/env python3
"""Replay recorded dev snippet presentation; never claim ranking or live latency gains."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.live_eval import validate_report
from eval.run_eval import bootstrap
from ownsearch.textproc import analyze
from ownsearch.webmodels import WebCandidate


def word_character(character):
    return bool(character) and (character.isalnum() or character == '_' or unicodedata.category(character).startswith('M'))


def inspect_excerpt(source, rendered):
    """Compare with captured source characters, not a guess from the display alone."""
    if source.startswith(rendered):
        body = rendered
    elif rendered.endswith('…') and source.startswith(rendered[:-1]):
        body = rendered[:-1]
    else:
        return {'valid_source_prefix': False, 'clipped': False, 'mid_word_end': False,
                'sentence_boundary': False, 'omitted': False}
    clipped = len(body) < len(source)
    broken = bool(clipped and body and word_character(body[-1]) and word_character(source[len(body)]))
    sentence = bool(re.search(r'''[.!?…。！？।]["'”’»\)\]]*$''', body))
    return {'valid_source_prefix': True, 'clipped': clipped, 'mid_word_end': broken,
            'sentence_boundary': sentence, 'omitted': not body.strip()}


def complete_word_prefix(source, rendered):
    """Do not count a cut-off final identifier as a complete query-word match."""
    body = rendered if source.startswith(rendered) else rendered.removesuffix('…')
    if inspect_excerpt(source, rendered)['mid_word_end']:
        end = len(body)
        while end and word_character(body[end - 1]):
            end -= 1
        body = body[:end]
    return body


def candidate_from_record(result, passages):
    item = WebCandidate(result['title'], result['url'], result.get('snippet', ''),
                        result.get('provider', ''), result.get('source_type', 'provider_snippet'))
    # These are captured evidence passages, not reconstructed full page bodies.
    item.evidence = passages
    item.score = result.get('score', 0)
    item.provenance = result.get('provenance', [])
    item.fetch_status = result.get('fetch_status', 'not_fetched')
    return item


def replay(recorded, samples=1000, seed=20261021, renderer='current'):
    cases = validate_report(recorded)
    if len(recorded['runs']) != len(cases):
        raise ValueError('The complete fixed dev recording is required.')
    rows, changes = [], []
    render_seconds = 0.0
    identities_unchanged = True
    for run in recorded['runs']:
        evidence = {entry['url']: entry.get('passages', []) for entry in run['response'].get('evidence', [])}
        row = {'id': run['id'], 'returned': len(run['response']['results']), 'eligible': 0,
               'before_mid_word_ends': 0, 'after_mid_word_ends': 0,
               'before_clipped': 0, 'after_clipped': 0,
               'before_sentence_boundary': 0, 'after_sentence_boundary': 0,
               'before_omitted': 0, 'after_omitted': 0,
               'invalid_source_prefixes': 0, 'changed_snippets': 0,
               'query_terms_before': 0, 'query_terms_after': 0,
               'whole_query_terms_before': 0, 'whole_query_terms_after': 0}
        terms = set(analyze(run['query']))
        for position, result in enumerate(run['response']['results'], 1):
            passages = evidence.get(result['url'], [])
            before = result.get('snippet', '')
            if passages and before != passages[0]['text'][:600]:
                raise ValueError('Recorded passage and old renderer disagree; cannot use this baseline.')
            item = candidate_from_record(result, passages)
            started = time.perf_counter()
            if renderer == 'recorded':
                after_result = {'snippet': before, 'url': result['url'], 'score': result['score'],
                                'rank': result.get('rank', position)}
            else:
                after_result = item.result(result.get('rank', position), explain=True,
                                           query_terms=terms if renderer == 'current' else ())
            render_seconds += time.perf_counter() - started
            after = after_result['snippet']
            identities_unchanged &= (after_result['url'], after_result['score'], after_result['rank']) == (
                result['url'], result['score'], result.get('rank', position))
            if before != after:
                row['changed_snippets'] += 1
                changes.append({'id': run['id'], 'url': result['url'], 'before': before, 'after': after,
                                'passage': passages[0]['text'] if passages else None})
            if not passages:
                if before != after:
                    raise ValueError('Provider-only snippets must be preserved in this component.')
                continue
            row['eligible'] += 1
            for mode, rendered in (('before', before), ('after', after)):
                observed = inspect_excerpt(passages[0]['text'], rendered)
                row['invalid_source_prefixes'] += int(not observed['valid_source_prefix'])
                for metric, observation in (('mid_word_ends', 'mid_word_end'), ('clipped', 'clipped'),
                                            ('sentence_boundary', 'sentence_boundary'), ('omitted', 'omitted')):
                    row[f'{mode}_{metric}'] += int(observed[observation])
                row[f'query_terms_{mode}'] += len(terms & set(analyze(rendered)))
                row[f'whole_query_terms_{mode}'] += len(terms & set(analyze(complete_word_prefix(passages[0]['text'], rendered))))
        rows.append(row)
    eligible_rows = [row for row in rows if row['eligible']]
    def rate(sample, mode):
        return sum(r[f'{mode}_mid_word_ends'] for r in sample) / sum(r['eligible'] for r in sample)
    summary = {'dev_queries': len(rows), 'returned_snippets': sum(r['returned'] for r in rows),
               'evidence_backed_snippets': sum(r['eligible'] for r in rows),
               'changed_snippets': sum(r['changed_snippets'] for r in rows),
               'invalid_source_prefixes': sum(r['invalid_source_prefixes'] for r in rows),
               'recorded_result_identity_score_and_order_preserved': bool(identities_unchanged)}
    for mode in ('before', 'after'):
        summary[mode] = {metric: sum(r[f'{mode}_{metric}'] for r in rows)
                         for metric in ('mid_word_ends', 'clipped', 'sentence_boundary', 'omitted')}
        summary[mode]['matched_query_terms_diagnostic'] = sum(r[f'query_terms_{mode}'] for r in rows)
        summary[mode]['complete_query_word_matches_diagnostic'] = sum(r[f'whole_query_terms_{mode}'] for r in rows)
        summary[mode]['mid_word_end_rate'] = bootstrap(eligible_rows, statistic=lambda sample, mode=mode: rate(sample, mode), samples=samples, seed=seed)
    summary['paired_mid_word_end_rate_delta'] = bootstrap(eligible_rows, statistic=lambda sample: rate(sample, 'after') - rate(sample, 'before'), samples=samples, seed=seed)
    summary['snippet_renderer_total_ms_observational'] = round(render_seconds * 1000, 3)
    return {'schema': 'ownsearch-phase2-presentation-replay-v1', 'dataset_sha256': recorded['dataset_sha256'],
            'split': 'dev', 'seed': seed, 'bootstrap_samples': samples, 'renderer': renderer,
            'recorded_engine_fingerprint': recorded['engine_fingerprint'],
            'summary': summary, 'per_query': rows, 'changes': changes,
            'quality': {'strict_p@5': None, 'ndcg@10': None, 'reason': 'Relevance pools are unjudged; no Phase 1 baseline exists.'},
            'limitations': ['Uses only captured result metadata and evidence passages; it does not replay retrieval, enrichment or ranking.',
                            'Preserved result identities and scores are a rendering invariant, not independently measured relevance accuracy.',
                            'Mid-word ends are confirmed against captured passage text; passage-start defects and upstream passage truncation are unmeasured.',
                            'Query-token counts are lexical diagnostics, not independent relevance grades.',
                            'Renderer timing is observational local work, not cold or warm live-search latency.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded', type=Path, default=ROOT / 'eval/runs/baseline-dev.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap-samples', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=20261021)
    parser.add_argument('--renderer', choices=('recorded', 'sentence-only', 'current'), default='current',
                        help='Ablate recorded fixed-width rendering, sentence-only clipping, or current query-aware clipping.')
    args = parser.parse_args()
    if args.bootstrap_samples < 100:
        parser.error('Use at least 100 bootstrap samples.')
    data = args.recorded.read_bytes()
    result = replay(json.loads(data), args.bootstrap_samples, args.seed, args.renderer)
    result['recorded_sha256'] = hashlib.sha256(data).hexdigest()
    result['code_git_hash'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    result['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                             for name in ('ownsearch/snippet.py', 'ownsearch/webmodels.py', 'ownsearch/coordinator.py', 'scripts/eval_phase2_snippets.py')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
