"""Source-backed spelling and list discovery on unseen subjects, without live services."""
import contextlib
import io
import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from ownsearch.cli import _pretty
from ownsearch.fetcher import FetchResult
from ownsearch.knowledge import Entity, Knowledge
from ownsearch.query import parse_query
from tests.helpers import make_engine


def record(label, description, title):
    return {'labels': {'en': {'value': label}}, 'descriptions': {'en': {'value': description}},
            'aliases': {}, 'sitelinks': {'enwiki': {'title': title}}, 'claims': {}}


class SpellingAndDiscoveryTests(unittest.TestCase):
    def test_polite_list_requests_are_not_news_or_date_filtered(self):
        for raw in ['give me doremon cartoon character names', 'give me nebla museum exhibit names',
                    'show me Quasar names', 'give me a list of Umbra']:
            with self.subTest(query=raw):
                q = parse_query(raw)
                self.assertEqual(q.intent, 'general')
                self.assertEqual(q.result_format, 'list')
                self.assertFalse(q.fresh_intent)
                self.assertIsNone(q.after)
                self.assertNotIn('give', q.entity)
                self.assertNotIn('names', q.entity)
        self.assertEqual(parse_query('give me news on Umbra').intent, 'news')

    def test_source_correction_prefers_subject_to_related_list(self):
        engine, _ = make_engine()
        k = Knowledge(engine.settings)
        payload = {'query': {'searchinfo': {'suggestion': 'nebula museum exhibit names'}, 'pages': {
            '1': {'title': 'Nebula museum', 'index': 1, 'pageprops': {'wikibase_item': 'Q99'}},
            '2': {'title': 'List of Nebula opening dates', 'index': 2, 'pageprops': {'wikibase_item': 'Q100'}}}}}
        records = {'Q99': record('Nebula', 'science museum', 'Nebula museum'),
                   'Q100': record('list of Nebula opening dates', 'Wikimedia list article', 'List of Nebula opening dates')}
        def labels(text):
            return [{'id': 'Q99', 'match': {'text': 'Nebula', 'type': 'label'}}] if text == 'nebula' else []
        with patch.object(k, '_json', return_value=payload), patch.object(k, 'entities', return_value=records), \
                patch.object(k, '_wd_search', side_effect=labels):
            entities = k.link(['nebla', 'museum', 'exhibit'], ['names'], load_claims=False, load_urls=False)
        self.assertEqual([e.qid for e in entities], ['Q99'])
        self.assertEqual(entities[0].span, 'nebla')
        self.assertEqual(k.spelling_corrections, {'nebla': 'nebula'})
        self.assertNotIn('nebla', entities[0].names)

    def test_arbitrary_source_rewrites_are_not_spelling_corrections(self):
        engine, _ = make_engine()
        for original, suggestion in [('cat names', 'dog names'), ('nebla museum', 'nebula airport'),
                                     ('nebla exhibits', 'nebula new exhibits')]:
            with self.subTest(original=original):
                k = Knowledge(engine.settings)
                with patch.object(k, '_json', return_value={'query': {'searchinfo': {'suggestion': suggestion}}}):
                    k._wp_search(original)
                self.assertEqual(k.spelling_corrections, {})

    def test_search_pageterms_avoid_second_entity_api_dependency(self):
        engine, _ = make_engine()
        k = Knowledge(engine.settings)
        payload = {'query': {'searchinfo': {'suggestion': 'nebula museum exhibits'}, 'pages': {
            '1': {'title': 'Nebula museum', 'index': 1, 'pageprops': {'wikibase_item': 'Q99'},
                  'terms': {'label': ['Nebula'], 'description': ['science museum'], 'alias': ['Nebula Center']}}}}}
        with patch('ownsearch.knowledge._get_json', return_value=payload) as source, \
                patch.object(k, 'entities', side_effect=AssertionError('Second entity API should not be needed')):
            entities = k.link(['nebla', 'museum', 'exhibit'], load_claims=False, load_urls=False)
        self.assertEqual([e.label for e in entities], ['Nebula'])
        self.assertIn('Nebula Center', entities[0].aliases)
        self.assertEqual(source.call_count, 1)

    def test_list_format_boost_requires_topic_and_preserves_exact_phrase(self):
        engine, _ = make_engine(knowledge_enabled=True)
        text = 'Nebula museum exhibits include a prism and a pendulum. Nebula museum exhibits teach physics.'
        engine.add_document('Nebula museum', text, 'https://museum.example/about')
        engine.add_document('List of Nebula exhibits', text, 'https://museum.example/list')
        engine.add_document('List of other museum exhibits', 'Other museums have exhibits about unrelated topics.',
                            'https://other.example/list')
        with patch.object(Knowledge, 'link', return_value=[Entity('Q99', 'Nebula', span='Nebula')]), \
                patch('ownsearch.discover.discover', return_value=[]):
            res = engine.search('give me Nebula museum exhibit names', live=True, use_cache=False)
        self.assertEqual(res['results'][0]['title'], 'List of Nebula exhibits')
        self.assertNotIn('https://other.example/list', [r['url'] for r in res['results']])
        # Quoted misspellings keep literal phrase semantics even when a linked
        # source supplies a correctly spelled entity name.
        with patch.object(Knowledge, 'link', return_value=[Entity('Q99', 'Nebula', span='nebla')]), \
                patch('ownsearch.discover.discover', return_value=[]):
            self.assertEqual(engine.search('"nebla museum" names', live=True, use_cache=False)['results'], [])

    def test_live_pipeline_follows_source_list_link_and_indexes_names(self):
        engine, _ = make_engine(knowledge_enabled=True)
        records = {'Q99': record('Nebula', 'science museum', 'Nebula museum')}
        requested = []

        def fetch(url, **kwargs):
            requested.append(url)
            p = urlparse(url)
            params = parse_qs(p.query)
            content_type = 'application/json'
            if p.path == '/w/api.php' and 'gsrsearch' in params:
                body = {'query': {'searchinfo': {'suggestion': 'nebula museum exhibit names'}, 'pages': {
                    '1': {'title': 'Nebula museum', 'index': 1, 'pageprops': {'wikibase_item': 'Q99'}}}}}
            elif p.path == '/w/api.php' and params.get('action') == ['wbgetentities']:
                body = {'entities': records}
            elif p.path == '/w/api.php' and params.get('action') == ['wbsearchentities']:
                body = {'search': []}
            elif p.path == '/wiki/Special:EntityData/Q99.json':
                body = {'entities': records}
            elif p.path == '/robots.txt':
                body, content_type = 'User-agent: *\nAllow: /', 'text/plain'
            elif p.path == '/wiki/Nebula_museum':
                body, content_type = ('<html><title>Nebula museum</title><main><p>Nebula is a science museum. '
                    'Nebula has many exhibits. Visitors can learn about them.</p>'
                    '<a href="/wiki/Nebula_(exhibit)">Nebula exhibit</a>'
                    '<a href="/wiki/List_of_Nebula_exhibits">List of Nebula exhibits</a>'
                    '<a href="https://unrelated.example/list">List of Nebula exhibits</a>'
                    '</main></html>'), 'text/html'
            elif p.path == '/wiki/List_of_Nebula_exhibits':
                body, content_type = ('<html><title>List of Nebula exhibits</title><main>'
                    '<p>Nebula museum exhibits include the following displays. These Nebula exhibits teach science.</p>'
                    '<h2>Lunar prism</h2><p>The Lunar prism demonstrates optics in the museum.</p>'
                    '<h2>Solar pendulum</h2><p>The Solar pendulum demonstrates motion.</p></main></html>'), 'text/html'
            else:
                raise AssertionError('Unexpected external request: ' + url)
            raw = json.dumps(body) if isinstance(body, dict) else body
            return FetchResult(url, url, 200, {'content-type': content_type}, raw.encode())

        with patch('ownsearch.fetcher.Fetcher.fetch', side_effect=fetch):
            res = engine.search('give me nebla museum exhibit names', live=True, use_cache=False)
        self.assertEqual([r['title'] for r in res['results']], ['List of Nebula exhibits'])
        self.assertEqual(res['query_understanding']['spelling_corrections'], {'nebla': 'nebula'})
        self.assertFalse(res['provider_errors'])
        self.assertNotIn('/wiki/Nebula_(exhibit)', [urlparse(u).path for u in requested])
        self.assertFalse(any('rss' in u or 'unrelated.example' in u for u in requested))
        doc = engine.store.get_by_url('https://en.wikipedia.org/wiki/List_of_Nebula_exhibits')
        self.assertIn('Lunar prism', doc['text'])
        self.assertIn('Solar pendulum', doc['text'])
        self.assertIn('Lunar prism', res['results'][0]['snippet'])
        self.assertIn('Solar pendulum', res['results'][0]['snippet'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _pretty(res)
        self.assertIn('nebla → nebula', output.getvalue())


if __name__ == '__main__':
    unittest.main()
