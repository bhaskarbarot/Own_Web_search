"""Evaluation regressions; never call public providers or read sealed query bodies."""
import argparse
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval import live_eval as evaluation
from scripts.benchmark_query_md import cases_from_markdown


class LiveEvalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.split = evaluation.load_dev()
        self.case = self.cases[0]

    def report(self, results=None, batches=None):
        return {'dataset_sha256': self.split['dataset_sha256'], 'engine_fingerprint': 'fixture',
                'protocol': {}, 'expected_queries': 300,
                'runs': [{'id': self.case['id'], 'query': self.case['text'], 'category': self.case['category'],
                          'checked_at': '2026-10-21T06:00:00Z', 'cold_wall_ms': 100,
                          'response': {'results': results or [], 'provider_status': []},
                          'source_batches': batches or []}]}

    def test_split_is_exact_disjoint_and_original_dev_text_is_preserved(self):
        self.assertEqual(self.split['counts'], {'all': 500, 'dev': 300, 'sealed': 200})
        self.assertFalse(set(self.split['dev_ids']) & set(self.split['sealed_ids']))
        original = {c['id']: c for c in cases_from_markdown(evaluation.ROOT / 'query.md')}
        for case in self.cases:
            if case['origin'].startswith('query.md:'):
                self.assertEqual(case['text'], original[case['origin'].split(':')[1]]['query'])
        self.assertTrue({'programming', 'documentation', 'news', 'research', 'business', 'finance',
                         'general_knowledge', 'local', 'ambiguous', 'adversarial', 'nonexistent_entity',
                         'verbose', 'exact_phrase', 'operators', 'multilingual'} <= {c['category'] for c in self.cases})

    def test_dev_hash_tamper_and_sealed_run_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'splits.json').write_text(json.dumps(self.split))
            (root / 'dev.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                evaluation.load_dev(root)
        report = self.report()
        report['runs'][0]['id'] = self.split['sealed_ids'][0]
        with self.assertRaisesRegex(ValueError, 'development'):
            evaluation.validate_report(report)

    def test_hand_calculated_metrics_and_missing_position_denominator(self):
        grades = {'https://a/': 3, 'https://b/': 1, 'https://c/': 2, 'https://x/': 0}
        scores = evaluation.relevance(['https://x/', 'https://a/', 'https://b/'], grades)
        self.assertEqual(scores['p@5'], .4)
        self.assertEqual(scores['strict_p@5'], .2)
        self.assertEqual(scores['mrr@10'], .5)
        self.assertAlmostEqual(scores['recall@10'], 2 / 3)
        import math
        self.assertAlmostEqual(scores['ndcg@10'], (7 / math.log2(3) + 1 / math.log2(4)) /
                               (7 + 3 / math.log2(3) + 1 / math.log2(4)))

    def test_unjudged_and_all_zero_pools_are_distinct(self):
        self.assertIsNone(evaluation.relevance(['https://a/'], {}))
        scores = evaluation.relevance(['https://a/'], {'https://a/': 0})
        self.assertEqual(scores['ndcg@10'], 0)
        self.assertEqual(scores['mrr@10'], 0)
        self.assertIsNone(scores['recall@10'])

    def test_pool_collects_both_sources_without_fabricating_fetches(self):
        report = self.report([{'url': 'https://one.example/', 'title': 'one'}],
                             [{'source': 'fixture', 'rows': [{'url': 'https://two.example/', 'title': 'two'}]}])
        pool = evaluation.pool_runs(report)
        self.assertEqual(len(pool), 2)
        self.assertNotIn('fetch_status', pool[0]['observations'][0])
        blind = evaluation.blinded(pool)
        self.assertNotIn('source', blind[0]['evidence'][0])
        self.assertNotIn('rank', blind[0]['evidence'][0])
        self.assertFalse(pool[0]['independent_review'])

    def test_no_labels_mean_null_quality_and_null_fabrication_count(self):
        report = self.report([{'url': 'https://one.example/', 'title': 'one'}])
        pool = evaluation.pool_runs(report)
        metrics = evaluation.assess(report, pool, {}, samples=100)
        self.assertIsNone(metrics['quality']['p@5']['value'])
        self.assertIsNone(metrics['fabricated_url_count'])
        self.assertEqual(metrics['url_provenance_gap_count'], 1)
        self.assertIsNone(metrics['latency']['warm']['p50_ms']['value'])
        self.assertEqual(metrics['zero_result_rate']['value'], 0)

    def test_partial_pool_is_not_used_as_complete_reference(self):
        report = self.report([{'url': 'https://one.example/'}],
                             [{'source': 'fixture', 'rows': [{'url': 'https://two.example/'}]}])
        pool = evaluation.pool_runs(report)
        labels = {(self.case['id'], 'https://one.example/'): {'grade': 3, 'independent_review': False}}
        metrics = evaluation.assess(report, pool, labels, samples=100)
        self.assertEqual(metrics['judgment_coverage']['fully_judged_queries'], 0)
        self.assertIsNone(metrics['quality']['p@5']['value'])

    def test_zero_result_cases_are_included_and_warm_is_separate(self):
        report = self.report()
        report['runs'][0].update(warm_wall_ms=2, warm_response={'cached': True})
        metrics = evaluation.assess(report, [], {}, samples=100)
        self.assertEqual(metrics['zero_result_rate']['value'], 1)
        self.assertEqual(metrics['latency']['cold']['p50_ms']['value'], 100)
        self.assertEqual(metrics['latency']['warm']['p50_ms']['value'], 2)

    def test_stale_grade_and_false_llm_independence_are_rejected(self):
        pool = evaluation.pool_runs(self.report([{'url': 'https://one.example/'}]))
        row = {'id': self.case['id'], 'url': pool[0]['url'], 'evidence_sha256': pool[0]['evidence_sha256'],
               'grade': 2, 'judge_kind': 'llm', 'judge_id': 'fixture', 'rationale': 'fixture only', 'independent_review': False}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'grades.jsonl'
            path.write_text(json.dumps(row))
            self.assertEqual(len(evaluation.load_judgments(path, pool)), 1)
            for mutation in ({'evidence_sha256': 'stale'}, {'grade': True}, {'independent_review': True}, {'fabricated_url': False}):
                path.write_text(json.dumps({**row, **mutation}))
                with self.assertRaises(ValueError):
                    evaluation.load_judgments(path, pool)

    def test_sampling_is_seeded_and_unjudged_candidates_are_separate(self):
        pool = evaluation.pool_runs(self.report([{'url': f'https://example.org/{n}', 'title': str(n)} for n in range(10)]))
        labels = {(r['id'], r['url']): {'grade': 1, 'independent_review': False} for r in pool}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'review.csv'
            self.assertEqual(evaluation.review_csv(path, pool, labels), 1)
            content = path.read_bytes()
            evaluation.review_csv(path, pool, labels)
            self.assertEqual(content, path.read_bytes())
            self.assertEqual(evaluation.review_csv(path, pool, {}), 0)
            self.assertEqual(evaluation.review_csv(path, pool, {}, candidates=True), 1)
            self.assertEqual(evaluation.review_csv(path, pool, {}, candidates=True, fraction=1), 10)

    def test_duplicate_urls_cannot_shift_a_sixth_rank_into_precision_at_five(self):
        urls = ['https://x/', 'https://x/', 'https://a/', 'https://b/', 'https://c/', 'https://d/']
        grades = {url: (0 if url == 'https://x/' else 3) for url in urls}
        self.assertEqual(evaluation.relevance(urls, grades)['p@5'], .6)

    def test_review_csv_round_trip_and_blank_rows_are_not_grades(self):
        report = self.report([{'url': 'https://one.example/', 'title': '=UNTRUSTED()', 'snippet': '+untrusted'}])
        pool = evaluation.pool_runs(report)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorded, reviewed, output = root / 'run.json', root / 'review.csv', root / 'grades.jsonl'
            recorded.write_text(json.dumps(report))
            evaluation.review_csv(reviewed, pool, {}, candidates=True)
            with reviewed.open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['title'], "'=UNTRUSTED()")
            self.assertEqual(rows[0]['snippet'], "'+untrusted")
            self.assertEqual(rows[0]['independent_review'], 'False')
            args = argparse.Namespace(recorded=recorded, extra_source=[], existing_judgments=None,
                                      output=output, csv=reviewed, independent_review=False)
            with self.assertRaisesRegex(ValueError, 'No completed'):
                evaluation.import_review(args)
            rows[0].update(human_grade='2', human_rationale='Fixture evidence supports the requested facet.',
                           human_reviewer='fixture-reviewer', reviewed_at='2026-10-21T06:00:00Z')
            with reviewed.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, 'human edits'):
                evaluation.review_csv(reviewed, pool, {}, candidates=True)
            with patch('builtins.print'):
                evaluation.import_review(args)
            label = list(evaluation.load_judgments(output, pool).values())[0]
            self.assertEqual(label['grade'], 2)
            self.assertFalse(label['independent_review'])
            self.assertEqual(label['judge_id'], 'fixture-reviewer')


if __name__ == '__main__':
    unittest.main()
