"""Automated Search Quality Evaluation and Benchmark Suite.

Evaluates 50 representative queries covering:
- News (with and without freshness)
- Financial queries (with and without freshness)
- Technical documentation (entity-specific, parameters, guides)
- Reference / Encyclopedic queries
- Navigational queries
- Exact phrase queries
- Scoped site queries
- Partial match and unindexed edge queries

Measures:
- NDCG@10, P@5, P@10, Recall@10, Recall@100, MRR@10
- Zero-result rate
- Latency percentiles (p50, p95, p99)
"""
import os
import unittest
from ownsearch.engine import SearchEngine
from ownsearch.evaluation import evaluate, load_qrels


class BenchmarkEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = SearchEngine()
        cls.eval_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eval_50_queries.json")

    def test_50_query_quality_metrics(self):
        self.assertTrue(os.path.exists(self.eval_path), "Benchmark dataset eval_50_queries.json must exist")
        qrels = load_qrels(self.eval_path)
        self.assertGreaterEqual(len(qrels), 50, "Evaluation dataset must contain at least 50 queries")

        report = evaluate(self.engine, qrels)
        summary = report["summary"]

        # Quality assertions
        self.assertGreaterEqual(summary["ndcg@10"], 0.70, f"NDCG@10 {summary['ndcg@10']} below threshold 0.70")
        self.assertGreaterEqual(summary["mrr@10"], 0.70, f"MRR@10 {summary['mrr@10']} below threshold 0.70")
        self.assertGreaterEqual(summary["recall@10"], 0.75, f"Recall@10 {summary['recall@10']} below threshold 0.75")

        # Latency assertions (local search p50 must be under 200ms)
        self.assertLess(summary["latency_p50_ms"], 200.0, f"Latency p50 {summary['latency_p50_ms']}ms exceeds 200ms")


if __name__ == "__main__":
    unittest.main()
