"""Regression checks for honest independent evaluation, not runtime relevance rules."""
import unittest
from scripts.eval_independent import ci, evidence, judged_metrics, load_dev, pool_rows

class EvaluationTests(unittest.TestCase):
    def rows(self, grades):
        items=[{'url':'https://fixture.example/'+str(i),'title':'Captured page','content':'actual fixture evidence'} for i in range(len(grades))]
        record={'id':'fixture','query':'fixture query','category':'fixture','cold':{'results':[{'url':item['url']} for item in items]},
                'pages':[{'item':item} for item in items]}
        pool=pool_rows([record])
        labels={(record['id'],item['url'],evidence(item)):g for item,g in zip(items,grades) if g is not None}
        return record,pool,labels
    def test_all_zero_judged_pool_is_a_failure(self):
        row,pool,grades=self.rows([0,0])
        out=judged_metrics([row],pool,grades)
        for key in ('strict_p_at_5','ndcg_at_10','mrr_at_10'):
            self.assertEqual(out[key]['value'],0)
        self.assertIsNone(out['recall_at_10'])
        self.assertEqual(out['coverage_ceiling']['value'],0)
    def test_unjudged_rows_are_not_counted_as_irrelevant(self):
        row,pool,grades=self.rows([3,None])
        out=judged_metrics([row],pool,grades)
        self.assertIsNone(out['strict_p_at_5'])
        self.assertEqual(out['coverage_ceiling_bounds'],[1,1])
        self.assertEqual(out['coverage_ceiling']['value'],1)
    def test_missing_positions_count_against_strict_precision(self):
        row,pool,grades=self.rows([3,1])
        out=judged_metrics([row],pool,grades)
        self.assertEqual(out['strict_p_at_5']['value'],.2)
        self.assertEqual(out['recall_at_10']['value'],1)
        self.assertEqual(out['mrr_at_10']['value'],1)
    def test_no_pool_does_not_claim_zero_coverage_ceiling(self):
        row,pool,grades=self.rows([])
        out=judged_metrics([row],pool,grades)
        self.assertIsNone(out['coverage_ceiling'])
        self.assertEqual(out['coverage_ceiling_bounds'],[0,1])
    def test_duplicate_url_cannot_earn_twice(self):
        row,pool,grades=self.rows([3])
        row['cold']['results']*=2
        self.assertEqual(judged_metrics([row],pool,grades)['strict_p_at_5']['value'],.2)
    def test_other_capture_cannot_lend_relevance_to_wrong_snapshot(self):
        row,pool,grades=self.rows([0])
        other={'url':row['pages'][0]['item']['url'],'title':'Captured page','content':'different relevant evidence'}
        key=('fixture',other['url'],evidence(other))
        pool[key]={'id':'fixture','url':other['url']};grades[key]=3
        out=judged_metrics([row],pool,grades)
        self.assertEqual(out['strict_p_at_5']['value'],0)
        self.assertEqual(out['recall_at_10']['value'],0)
        self.assertEqual(out['coverage_ceiling']['value'],0)
    def test_ci_and_loader_are_deterministic(self):
        self.assertEqual(ci([0,1,1]),ci([0,1,1]))
        self.assertEqual(len(load_dev()),300)

if __name__=='__main__':unittest.main()
