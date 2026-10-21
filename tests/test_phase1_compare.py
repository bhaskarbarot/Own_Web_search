"""Undefined recall and incomplete labels must never turn a phase gate green."""
import unittest
import csv
import tempfile
from pathlib import Path
from scripts.eval_phase1_compare import judgments_complete,paired_quality,csv_judgments


class PhaseOneComparisonTests(unittest.TestCase):
    def test_all_zero_pool_has_undefined_recall_without_fabricated_delta(self):
        rows={'q':{'metrics':{'recall@10':None,'strict_p@5':0.0}}}
        result=paired_quality(rows,rows,['q'],['recall@10','strict_p@5'])
        self.assertIsNone(result['recall@10']['value'])
        self.assertEqual(result['recall@10']['queries'],0)
        self.assertEqual(result['strict_p@5']['value'],0.0)
    def test_partial_labels_and_empty_reference_pool_block_completeness(self):
        rows=[{'category':'research','fully_judged_pool':True},
              {'category':'multilingual','fully_judged_pool':False}]
        self.assertFalse(judgments_complete(rows))
    def test_nonexistent_empty_pool_does_not_require_invented_reference_url(self):
        self.assertTrue(judgments_complete([{'category':'research','fully_judged_pool':True},
                                           {'category':'nonexistent_entity','fully_judged_pool':False}]))
    def test_union_csv_import_preserves_human_edits_and_accepts_explicit_zero(self):
        row={'id':'fixture','url':'https://example.org/a','evidence_sha256':'fixture-digest','human_grade':'0',
             'human_rationale':'About a different entity.','human_reviewer':'fixture-reviewer','reviewed_at':'2026-10-21'}
        pool=[{k:row[k] for k in ('id','url','evidence_sha256')}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'reviews.csv'
            with path.open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader();writer.writerow(row)
            before=path.read_bytes();labels=csv_judgments(path,pool)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(labels[('fixture',row['url'])]['grade'],0)
            self.assertFalse(labels[('fixture',row['url'])]['independent_review'])
            with self.assertRaisesRegex(ValueError,'stale'):
                csv_judgments(path,[dict(pool[0],evidence_sha256='changed')])
