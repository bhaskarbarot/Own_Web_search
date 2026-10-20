"""Independent metric checks and explicit-date contract regressions; no live services."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ownsearch.evaluation import precision
from ownsearch.query import parse_query
from tests.helpers import make_engine

SPEC = importlib.util.spec_from_file_location('baseline_runner', Path(__file__).resolve().parents[1] / 'eval/run_eval.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BaselineToolsTests(unittest.TestCase):
    def test_precision_keeps_the_standard_denominator(self):
        self.assertEqual(precision(['correct'], {'correct': 3}, 5), .2)
        self.assertEqual(precision(['wrong', 'correct'], {'correct': 3}, 5), .2)

    def test_bootstrap_is_seeded_and_does_not_invent_missing_measurements(self):
        a = runner.bootstrap([0, 1, 1, 0], samples=200, seed=7)
        self.assertEqual(a, runner.bootstrap([0, 1, 1, 0], samples=200, seed=7))
        self.assertEqual(a['value'], .5)
        self.assertLessEqual(a['ci95'][0], a['value'])
        self.assertGreaterEqual(a['ci95'][1], a['value'])
        self.assertEqual(runner.bootstrap([None]), {'value': None, 'ci95': None, 'queries': 0})

    def test_fixture_queries_are_valid_and_languages_are_explicit(self):
        root = Path(__file__).resolve().parents[1]
        corpus = json.loads((root / 'eval/corpus.json').read_text())
        cases = runner.load_queries(root / 'eval/queries.jsonl', {d['url'] for d in corpus['documents']})
        self.assertGreaterEqual(len(cases), 50)
        self.assertTrue({'en', 'hi', 'gu', 'hi-Latn'} <= {q['language'] for q in cases})
        self.assertTrue(any(q['expected_empty'] for q in cases))
        categories = {c for q in cases for c in q['categories']}
        self.assertTrue({'coding', 'official_docs', 'factual', 'news', 'comparison',
                         'named_entity', 'list', 'misspelling', 'hinglish'} <= categories)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.jsonl'
            path.write_text(json.dumps({'id':'x', 'query':'example', 'language':'en',
                                       'judgments':{'https://missing.example/':3}, 'expected_empty':False}))
            with self.assertRaises(ValueError):
                runner.load_queries(path, set())


class ExplicitFreshnessTests(unittest.TestCase):
    def test_presets_have_explicit_date_filter_semantics(self):
        self.assertTrue(parse_query('Nebula museum', freshness='week').explicit_date_filter)
        self.assertTrue(parse_query('Nebula after:2026-01-01').explicit_date_filter)
        self.assertFalse(parse_query('Nebula museum').explicit_date_filter)

    def test_requested_week_rejects_old_undated_and_future_pages(self):
        now = datetime(2026, 1, 8, 12, tzinfo=timezone.utc)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(now.timestamp(), tz)

        engine, _ = make_engine()
        for name, age in [('recent', 1), ('boundary', 7), ('too-old', 8), ('future', -1), ('undated', None)]:
            engine.store.upsert('https://fixture.example/' + name, 'Nebula museum ' + name,
                'Nebula museum has science exhibits. Nebula museum welcomes visitors.',
                published_at=(now - timedelta(days=age)).isoformat() if age is not None else None)
        engine.rebuild_index()
        with patch('ownsearch.query.datetime', Clock), patch('ownsearch.engine.time.time', return_value=now.timestamp()):
            result = engine.search('Nebula museum', freshness='week', use_cache=False, site='fixture.example')
            ordinary = engine.search('Nebula museum', use_cache=False, site='fixture.example')
        self.assertEqual({r['url'] for r in result['results']},
                         {'https://fixture.example/recent', 'https://fixture.example/boundary'})
        self.assertTrue({'https://fixture.example/undated', 'https://fixture.example/too-old'} <=
                        {r['url'] for r in ordinary['results']})
