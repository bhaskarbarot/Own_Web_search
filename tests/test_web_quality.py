"""Regressions from real-query failures; source fixtures never call public services."""
import hashlib
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ownsearch.coordinator import LiveSearch
from ownsearch.query import parse_query
from ownsearch.webmodels import WebCandidate, WebRequest
from ownsearch.webproviders import SourceBatch, provider_query
from ownsearch.webquery import conservative_intent, documentation_affinity
from ownsearch.webfocus import links
from ownsearch.webranking import rank
from scripts.eval_live_web import assess, release_gate
from scripts.benchmark_query_md import cases_from_markdown
from tests.test_live_web import Source, settings, row


def item(title, snippet, url):
    return WebCandidate.from_row({'title': title, 'snippet': snippet, 'url': url}, 'fixture', 1)


class QueryQualityTests(unittest.TestCase):
    def test_uncertain_intent_does_not_activate_finance_or_recent_news_filters(self):
        q = parse_query('Orion research')
        q.intent = 'news'
        q.intent_scores = {'news': .24, 'tech_docs': .23}
        q.intent_confidence = {'status': 'uncalibrated', 'margin': .01}
        q.after, q.before, q.freshness = 100, 200, 'week'
        q.explicit_date_filter = False
        conservative_intent(q)
        self.assertEqual(q.intent, 'general')
        self.assertIsNone(q.after)
        self.assertIsNone(q.before)

    def test_explicit_dates_survive_uncertain_intent(self):
        q = parse_query('Orion after:2026-01-01')
        after = q.after
        q.intent, q.intent_scores = 'financial', {'finance_quote': .2, 'general': .19}
        q.intent_confidence = {'status': 'uncalibrated', 'margin': .01}
        conservative_intent(q)
        self.assertEqual(q.after, after)
        self.assertTrue(q.explicit_date_filter)

    def test_latest_without_a_duration_does_not_impose_an_arbitrary_week(self):
        q = conservative_intent(parse_query('latest Orion headlines'))
        self.assertIsNone(q.after)
        self.assertFalse(q.explicit_date_filter)

    def test_explicit_month_and_rolling_days_are_calendar_grammar(self):
        from ownsearch.webquery import live_dates
        fixed = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        q = parse_query('events this month')
        live_dates(q, fixed)
        self.assertEqual(datetime.fromtimestamp(q.after, timezone.utc).day, 1)
        self.assertEqual(datetime.fromtimestamp(q.after, timezone.utc).month, 10)
        q = parse_query('advisories in the last 30 days.')
        q.intent = 'general'  # isolate calendar grammar from the classifier
        live_dates(q, fixed)
        self.assertAlmostEqual(fixed.timestamp()-q.after, 30*86400)

    def test_unknown_identifier_requires_literal_evidence(self):
        unrelated = item('Programming library errors', 'Diagnose a nonexistent programming library and missing modules.', 'https://example.org/libraries')
        self.assertEqual(rank([unrelated], parse_query('Find programming library QuasarVector9000')), [])
        actual = item('QuasarVector9000 documentation', 'QuasarVector9000 programming library reference.', 'https://example.org/quasar')
        self.assertEqual(rank([actual], parse_query('Find programming library QuasarVector9000'))[0].url, actual.url)

    def test_incidental_person_mention_cannot_replace_complete_name_in_title(self):
        bad = item('Other Leader biography', 'Samrat Orion birthplace and life are mentioned in passing.', 'https://example.org/leader')
        self.assertEqual(rank([bad], parse_query('Samrat Orion birthplace')), [])

    def test_acronym_omitted_from_snippet_can_be_checked_on_actual_page(self):
        q = parse_query('Compare mini PCs for CPU inference')
        doc = item('Mini PCs for local inference', 'Compare mini PCs and local inference hardware.', 'https://example.org/mini')
        self.assertTrue(rank([doc], q, final=False))
        self.assertFalse(rank([doc], q, final=True))
        doc.fetch_status = 'fetched'
        doc.content = 'Mini PCs support CPU inference. Compare CPU configurations for local inference.'
        self.assertTrue(rank([doc], q, final=True))

    def test_namesake_page_without_requested_fact_focus_is_rejected(self):
        doc = item('Samrat Orion', 'A feature film with a cast and production credits.', 'https://screen.example/orion')
        doc.fetch_status = 'fetched'
        doc.content = 'Samrat Orion cast and production. An actor profile on this page lists a birthplace.'
        self.assertFalse(rank([doc], parse_query('Samrat Orion birthplace'), final=True))

    def test_docs_structure_improves_relevant_docs_without_boosting_unrelated_docs(self):
        q = parse_query('Nebula timeout documentation')
        guide = item('Nebula timeout', 'Nebula timeout parameter documentation and configuration.', 'https://docs.nebula.example/timeouts')
        blog = item('Nebula timeout', guide.snippet, 'https://blog.example/nebula-timeout')
        bad = item('Other software', 'An unrelated article briefly mentions Nebula timeout.', 'https://docs.nebula.example/other')
        results = rank([blog, guide, bad], q)
        self.assertEqual(results[0].url, guide.url)
        self.assertEqual(bad.features.get('documentation_structure', 0), 0)
        self.assertGreater(documentation_affinity('docs'), .5)

    def test_ranking_preserves_original_snippet_and_is_repeatable(self):
        doc = item('Nebula timeout', 'Nebula timeout configuration. A longer source snippet remains unchanged.', 'https://example.org/nebula')
        original = doc.snippet
        score = rank([doc], parse_query('Nebula timeout'))[0].score
        self.assertEqual(doc.snippet, original)
        self.assertEqual(rank([doc], parse_query('Nebula timeout'))[0].score, score)

    def test_discovery_keeps_filters_and_quoted_error_without_leading_request_grammar(self):
        raw = 'Find official documentation for Nebula timeouts'
        q = parse_query(raw)
        sent = provider_query(WebRequest(raw, q, threading.Event()))
        self.assertTrue(sent.startswith('Nebula'))
        raw = 'Find the exact phrase "unable to acquire lock" site:docs.example.org'
        q = parse_query(raw)
        sent = provider_query(WebRequest(raw, q, threading.Event()))
        self.assertTrue(sent.startswith('"unable to acquire lock"'))
        self.assertIn('site:docs.example.org', sent)

    def test_missing_identifier_gets_one_bounded_focused_search_with_provenance(self):
        from ownsearch.webproviders import SearxWebProvider
        from urllib.parse import parse_qs, urlsplit
        cfg = settings(searxng_url='https://search.example')
        provider = SearxWebProvider(cfg)
        query = 'Find Nebula nebulaEffect cleanup documentation'
        request = WebRequest(query, parse_query(query), threading.Event())
        first = {'results': [{'url': 'https://nebula.example/', 'title': 'Nebula home', 'content': 'Nebula project'}]}
        second = {'results': [{'url': 'https://nebula.example/effect', 'title': 'nebulaEffect cleanup', 'content': 'Nebula nebulaEffect cleanup guide'}]}
        with patch.object(provider, 'request', side_effect=[first, second]) as fetch:
            batch = provider.search(request, time.monotonic()+1)
        self.assertEqual(fetch.call_count, 2)
        sent = parse_qs(urlsplit(fetch.call_args_list[1].args[1]).query)['q'][0]
        self.assertTrue(sent.startswith('nebulaeffect'))
        self.assertNotEqual(batch.rows[0]['source_query'], batch.rows[-1]['source_query'])
        self.assertEqual(batch.rows[0]['url'], 'https://nebula.example/effect')

    def test_discovery_does_not_drop_free_open_source_or_official_qualifiers(self):
        raw = 'Find free open-source Quasar software with official documentation'
        q = parse_query(raw)
        sent = provider_query(WebRequest(raw, q, threading.Event()))
        self.assertIn(raw, sent)
        self.assertIn('free open-source', sent)
        self.assertIn('official documentation', sent)

    def test_link_cannot_borrow_parent_title_and_cannot_escape_origin(self):
        doc = item('Nebula timeout manual', 'Nebula timeout configuration.', 'https://docs.nebula.example/')
        doc.links = [('https://docs.nebula.example/uninstall', 'Uninstall Nebula', False),
                     ('https://elsewhere.example/timeouts', 'Nebula timeout', False),
                     ('https://docs.nebula.example/timeout', 'Timeout parameter', False)]
        children = links(doc, parse_query('Nebula timeout parameter documentation'))
        self.assertTrue(children)
        self.assertTrue(all('elsewhere' not in c.url for c in children))
        uninstall = next((c for c in children if c.url.endswith('/uninstall')), None)
        if uninstall:
            self.assertNotIn('timeout', uninstall.title.lower())

    def test_focus_uses_a_declared_sitemap_and_rejects_external_entries(self):
        from ownsearch.webfocus import sitemap_links
        from ownsearch.fetcher import FetchResult
        from types import SimpleNamespace
        from ownsearch.robots import RobotsPolicy
        doc = item('Nebula docs', 'Nebula reference.', 'https://docs.nebula.example/')
        xml = b'<urlset><url><loc>https://docs.nebula.example/nebula/timeout</loc></url><url><loc>https://other.example/nebula/timeout</loc></url></urlset>'
        class Session:
            settings = globals()['settings']()
            def policy(self, url, deadline):
                return RobotsPolicy(sitemaps=['https://docs.nebula.example/published-map.xml'])
            def page(self, url, deadline):
                if url != 'https://docs.nebula.example/published-map.xml':
                    raise AssertionError('Only a declared sitemap may be fetched.')
                return FetchResult(url, url, 200, {'content-type': 'application/xml'}, xml)
        rows = sitemap_links(Session(), doc, parse_query('Nebula timeout documentation'), time.monotonic()+1)
        self.assertEqual([row.url for row in rows], ['https://docs.nebula.example/nebula/timeout'])
        self.assertEqual(rows[0].provenance[-1]['evidence_level'], 'url_in_declared_sitemap')

    def test_short_specific_doc_link_is_available_for_content_verification(self):
        doc = item('Nebula HTTP library', 'Nebula documentation.', 'https://docs.nebula.example/')
        doc.links = [('https://docs.nebula.example/quickstart', 'Timeouts', False),
                     ('https://docs.nebula.example/uninstall', 'Uninstall Nebula', False)]
        children = links(doc, parse_query('Nebula timeout parameter documentation'))
        self.assertEqual([c.url for c in children], ['https://docs.nebula.example/quickstart'])
        self.assertEqual(children[0].title, 'Timeouts')

    def test_relation_question_abstains_when_only_biography_evidence_exists(self):
        provider = Source(rows=[row('https://history.example/orion', 'Samrat Orion biography',
                                    'Samrat Orion achievements and many stories about Samrat Orion.')])
        result = LiveSearch(settings(), [provider]).search('Samrat Orion birthplace', fetch_pages=False, answer_mode=True)
        self.assertIsNone(result['answer'])
        self.assertEqual(result['answer_status'], 'insufficient_evidence')

    def test_relation_mentioned_for_another_subject_is_not_a_fact_answer(self):
        provider = Source(rows=[row('https://history.example/orion', 'Samrat Orion birthplace and travels',
                    "Samrat Orion visited Vega's birthplace and erected a memorial there.")])
        result = LiveSearch(settings(), [provider]).search('Samrat Orion birthplace', fetch_pages=False, answer_mode=True)
        self.assertIsNone(result['answer'])
        self.assertEqual(result['answer_status'], 'insufficient_evidence')

    def test_news_answer_uses_dated_titles_instead_of_an_arbitrary_paragraph(self):
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        provider = Source(rows=[{'url': 'https://news.example/orion', 'title': 'Orion announces a launch',
                                 'snippet': 'Orion announces a launch today.', 'published_at': now}])
        result = LiveSearch(settings(), [provider]).search("today's Orion headlines", fetch_pages=False, answer_mode=True)
        self.assertEqual(result['answer']['type'], 'headlines')
        self.assertEqual(result['answer']['headlines'][0]['published_at'], now)

    def test_market_answer_is_not_cancelled_by_fast_general_results(self):
        class Market:
            name, general_web = 'market', False
            def search(self, request, deadline):
                time.sleep(.2)
                return SourceBatch(answer={'type': 'stock_quote', 'text': 'Source quote',
                    'as_of': datetime.now(timezone.utc).isoformat(),
                    'source': {'name': 'Fixture', 'url': 'https://quote.example/QSR'}})
        cfg = settings(market_lookup_url='https://lookup.example/{q}', market_chart_url='https://chart.example/{symbol}',
                       discovery_provider_timeout=.5, live_early_results=1, live_provider_grace_ms=0)
        general = Source(rows=[row('https://quote.example/qsr', 'Quasar stock price', 'Quasar latest live stock price quote.')])
        with patch('ownsearch.coordinator.MarketWebProvider', return_value=Market()):
            result = LiveSearch(cfg, [general]).search('Quasar live price', fetch_pages=False)
        self.assertEqual(result['answer']['type'], 'stock_quote')


class EvaluationGuardTests(unittest.TestCase):
    def run_case(self, grades, rows, **extra):
        answer = None
        run = {'id': 'q', 'response': {'results': rows, 'answer': answer}}
        case = {'review_status': 'reviewed', 'judgments': grades, **extra}
        return assess([run], {'q': case})

    def test_all_irrelevant_review_is_counted_as_failure_not_silently_dropped(self):
        report = self.run_case({'https://bad.example/': 0}, [{'url': 'https://bad.example/'}])
        self.assertEqual(report['reviewed_queries'], 1)
        self.assertEqual(report['metrics']['precision@5']['value'], 0)
        self.assertEqual(report['metrics']['mrr@10']['value'], 0)
        self.assertEqual(report['metrics']['ndcg@10']['queries'], 0)

    def test_nonexistent_topic_abstention_is_measured_separately(self):
        correct = self.run_case({}, [], expected_empty=True)
        self.assertEqual(correct['abstention_correctness']['value'], 1)
        failed = self.run_case({}, [{'url': 'https://bad.example/'}], expected_empty=True)
        self.assertEqual(failed['abstention_correctness']['value'], 0)

    def test_unreviewed_rows_cannot_create_accuracy_scores(self):
        report = self.run_case({'https://good.example/': 3}, [{'url': 'https://good.example/'}], review_status='unreviewed')
        self.assertEqual(report['reviewed_queries'], 0)

    def test_release_gate_cannot_turn_returned_counts_or_self_review_into_accuracy(self):
        report = {'runs': [{'id': 'q'}], 'evaluation': {'task_success': {'value': 1}}, 'latency': {'p95_ms': 100}}
        cases = {'q': {'review_status': 'reviewed', 'task_success': True, 'independent_review': False}}
        self.assertFalse(release_gate(report, cases, minimum_reviewed=1)['passed'])
        cases['q']['independent_review'] = True
        self.assertTrue(release_gate(report, cases, minimum_reviewed=1)['passed'])
        report['latency']['p95_ms'] = 2000
        self.assertFalse(release_gate(report, cases, minimum_reviewed=1)['passed'])

    def test_markdown_cases_preserve_exact_text_and_workflow_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'queries.md'
            path.write_text('## Coding\n| C01 | Find `Quasar` docs. | Official source |\n## Workflows\n| M01 | Investigate a bug. | Search → verify |\n')
            rows = cases_from_markdown(path)
        self.assertEqual(rows[0]['query'], 'Find Quasar docs.')
        self.assertEqual(rows[1]['scope'], 'workflow_retrieval_only')
