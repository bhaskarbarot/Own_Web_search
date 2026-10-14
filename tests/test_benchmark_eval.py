"""Reproducible offline ranking benchmark; never depends on the developer's index."""
import json
import unittest
from pathlib import Path

from ownsearch.evaluation import evaluate, load_qrels
from tests.helpers import make_engine


class BenchmarkEvaluationTests(unittest.TestCase):
    def test_quality_metrics_on_versioned_corpus(self):
        engine, _ = make_engine()
        corpus = json.loads(Path(__file__).with_name("fixtures").joinpath("relevance_corpus.json").read_text())
        for doc in corpus["documents"]:
            engine.store.upsert(**doc)
        engine.rebuild_index()
        qrels = load_qrels(Path(__file__).with_name("fixtures") / "relevance_qrels.json")
        report = evaluate(engine, qrels)
        self.assertGreaterEqual(report["summary"]["ndcg@10"], 0.90)
        self.assertGreaterEqual(report["summary"]["mrr@10"], 0.90)
        self.assertGreaterEqual(report["summary"]["recall@10"], 0.90)
        self.assertLess(report["summary"]["latency_p50_ms"], 200)


if __name__ == "__main__":
    unittest.main()
