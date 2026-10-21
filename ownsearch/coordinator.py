"""Live-web-first coordinator shared by CLI/API; no corpus or database is required."""
import copy
import json
import math
import threading
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .engine import Busy, QueryCache, UNTRUSTED_NOTICE, _answer_allowed
from .providers import Calls
from .query import parse_query
from .snippet import highlights
from .util import utc_now
from .textproc import analyze
from .webquery import relation_terms
from .webfetch import WebFetchSession, EnrichmentJob
from .fetcher import FetchError
from .webmodels import WebCandidate, WebRequest, web_url
from .webproviders import configured, SourceBatch, FeedWebProvider, MarketWebProvider
from .webranking import merge, rank, constraints


def _validated(settings):
    integer_limits = {'live_fetch_pages': (0, 10), 'live_fetch_concurrency': (1, 8),
                      'live_workers': (2, 32), 'live_max_candidates': (1, 100),
                      'live_max_requests': (1, 100), 'live_cache_entries': (1, 256),
                      'live_early_results': (1, 50), 'live_provider_grace_ms': (0, 2000),
                      'live_max_page_bytes': (1024, 4_000_000),
                      'live_max_total_bytes': (1024, 16_000_000), 'live_max_text_chars': (100, 100_000)}
    integer_limits.update(provider_request_budget=(1, 10000), provider_failure_threshold=(1, 20))
    for key, (lo, hi) in integer_limits.items():
        value = getattr(settings, key)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(key+' must be between '+str(lo)+' and '+str(hi))
    for key in ('discovery_timeout', 'live_fetch_timeout', 'discovery_provider_timeout',
                'searxng_timeout', 'brave_timeout', 'financial_timeout'):
        value = getattr(settings, key)
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 120:
            raise ValueError(key+' must be finite and between 0 and 120 seconds')
    for key in ('live_cache_ttl', 'provider_min_interval', 'provider_cooldown', 'default_delay'):
        value = getattr(settings, key)
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 3600:
            raise ValueError(key+' must be finite and between 0 and 3600 seconds')
    if not isinstance(settings.provider_budget_window, (int, float)) or not math.isfinite(settings.provider_budget_window) or not 1 <= settings.provider_budget_window <= 86400:
        raise ValueError('provider_budget_window must be finite and between 1 and 86400 seconds')
    return settings


class _LocalSource:
    name = 'local_index'
    general_web = False
    def __init__(self, engine):
        self.engine = engine
    def search(self, request, deadline):
        q = request.parsed
        result = self.engine.search(request.query, limit=20, fetch_evidence=False, live=False,
                                    freshness=q.freshness, site=q.sites[0] if len(q.sites) == 1 else None, lang=q.lang,
                                    preferred_language=q.language_info.get('language'),
                                    timeout_ms=max(1, int((deadline-time.monotonic())*1000)))
        return SourceBatch([{**r, 'source_type': 'local_index'} for r in result['results']])


class LiveSearch:
    live_web_first = True
    persistent_storage = False

    def __init__(self, settings=None, providers=None, local_engine=None):
        self.settings = _validated(settings or Settings.load())
        self.root = self.settings.data_dir
        self.providers = configured(self.settings) if providers is None else providers
        self.calls = Calls(self.settings.live_workers)
        self.cache = QueryCache(self.settings.live_cache_entries, self.settings.live_cache_ttl)
        self.local_engine = local_engine
        self._local_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(self.settings.max_concurrent_searches or 8)
        self._metrics_lock = threading.Lock()
        self._metrics = {'requests': 0, 'empty_results': 0, 'provider_attempts': 0,
                         'provider_failures': 0, 'pages_fetched': 0, 'page_failures': 0,
                         'low_evidence_results': 0}

    def _local(self):
        if not self.settings.live_local_enabled:
            return None
        with self._local_lock:
            if self.local_engine is None and self.settings.db_path.is_file() and (self.settings.index_dir/'manifest.json').exists():
                from .engine import SearchEngine
                self.local_engine = SearchEngine(settings=self.settings)
        return self.local_engine

    def _start(self, provider, request, deadline):
        job = self.calls.start(provider, request, deadline)
        job['cancel'] = getattr(request, 'cancel', threading.Event())
        job['general_web'] = getattr(provider, 'general_web', False)
        job['health_provider'] = provider
        return job

    def _collect(self, jobs, deadline, useful=None):
        pending, finished, statuses = list(jobs), [], []
        early = None
        while pending and time.monotonic() < deadline:
            for job in list(pending):
                if job['event'].is_set():
                    pending.remove(job)
                    response = job['response']
                    finished.append(response)
                    statuses.append({'provider': response.provider, 'status': response.status,
                                     'elapsed_ms': response.elapsed_ms,
                                     'result_count': len(response.results.rows) if isinstance(response.results, SourceBatch)
                                     else len(response.results) if isinstance(response.results, list) else int(response.results is not None),
                                     **({'error': response.error} if response.error else {})})
                    snapshot = getattr(job['health_provider'], 'health_snapshot', None)
                    if callable(snapshot):
                        statuses[-1]['health'] = snapshot()
                elif time.monotonic() >= job['deadline']:
                    pending.remove(job)
                    job['cancel'].set()
                    statuses.append({'provider': job['name'], 'status': 'timeout', 'result_count': 0,
                                     'error': 'Source did not finish within its deadline; late results are ignored.'})
            if useful and early is None and useful(finished) >= self.settings.live_early_results:
                early = time.monotonic()+self.settings.live_provider_grace_ms/1000
            if early is not None and time.monotonic() >= early:
                break
            if pending:
                # Observe every completion; a slow first provider never hides a fast second one.
                pending[0]['event'].wait(min(.01, max(0, deadline-time.monotonic())))
        for job in pending:
            job['cancel'].set()
            expired = time.monotonic() >= min(deadline, job['deadline'])
            statuses.append({'provider': job['name'], 'status': 'timeout' if expired else 'unfinished',
                             'result_count': 0, 'error': 'Source unfinished at response cutoff; cancellation requested and late results ignored.'})
        return finished, statuses

    @staticmethod
    def _rows(response):
        if response.status != 'ok':
            return SourceBatch()
        if isinstance(response.results, SourceBatch):
            return response.results
        return SourceBatch(response.results if isinstance(response.results, list) else [])

    def search(self, query, limit=10, fetch_evidence=True, offset=0, freshness=None, site=None,
               filetype=None, lang=None, timeout_ms=None, explain=False, agent=None, use_cache=True,
               live=True, preferred_language=None, timezone_name=None, discovery_mode=None,
               fetch_pages=True, search_type='web', answer_mode=False, **unused):
        started = time.perf_counter()
        timeout_ms = max(1, min(int(timeout_ms or self.settings.search_timeout_ms), 120000))
        deadline = time.monotonic()+min(timeout_ms/1000, self.settings.discovery_timeout)
        if not self._slots.acquire(timeout=max(0, deadline-time.monotonic())):
            raise Busy('Too many concurrent live searches')
        try:
            return self._search(query, limit, fetch_evidence, offset, freshness, site, filetype, lang,
                                explain, use_cache, live, preferred_language, timezone_name,
                                fetch_pages, search_type, answer_mode, started, deadline)
        finally:
            self._slots.release()

    def _search(self, query, limit, fetch_evidence, offset, freshness, site, filetype, lang,
                explain, use_cache, live, preferred_language, timezone_name, fetch_pages,
                search_type, answer_mode, started, deadline):
        query = ' '.join(str(query or '').split())[:1000]
        limit, offset = max(1, min(int(limit), 50)), max(0, min(int(offset), 500))
        if search_type not in ('web', 'images'):
            raise ValueError('search_type must be web or images')
        key = repr((query, limit, offset, fetch_evidence, freshness, site, filetype, lang,
                    preferred_language, timezone_name, fetch_pages, search_type, answer_mode, live, explain))
        if use_cache and self.settings.live_cache_ttl > 0 and (cached := self.cache.get(key)):
            result = copy.deepcopy(cached)
            result['cached'] = True
            result['cached_trace'] = result['trace']
            result['cached_provider_status'] = result['provider_status']
            result['provider_status'] = []
            result['fetch_status'] = []
            result['trace'] = {'cache_hit': True, 'page_requests': 0, 'pages_fetched': 0,
                               'persistent_pages_written': 0, 'returned_results': len(result['results'])}
            result['served_at'] = utc_now()
            result['timing'] = {'total_ms': round((time.perf_counter()-started)*1000, 2),
                                'cached_response_original_ms': cached['took_ms']}
            result['took_ms'] = result['timing']['total_ms']
            return result
        parse_started = time.perf_counter()
        # Bundled language/intent resources; do not open/create entities.db or a corpus.
        q = parse_query(query, freshness=freshness, site=site, filetype=filetype, lang=lang,
                        preferred_language=preferred_language, timezone_name=timezone_name or self.settings.timezone,
                        holiday_country=self.settings.holiday_country)
        from .webquery import conservative_intent
        q = conservative_intent(q)
        parse_ms = (time.perf_counter()-parse_started)*1000
        sources = list(self.providers) if live and query else []
        if live and search_type == 'web' and query:
            if q.intent == 'financial' and self.settings.market_chart_url and self.settings.market_lookup_url:
                sources.append(MarketWebProvider(self.settings))
            elif q.intent == 'news' and (self.settings.news_feeds_file or self.settings.news_feeds):
                sources.append(FeedWebProvider(self.settings))
        # Local initialization is also independent work, never a prerequisite to discovery.
        if self.settings.live_local_enabled and query and search_type == 'web':
            owner = self
            class Local:
                name = 'local_index'
                general_web = False
                def search(self, request, source_deadline):
                    engine = owner._local()
                    return _LocalSource(engine).search(request, source_deadline) if engine else SourceBatch()
            sources.append(Local())
        provider_started = time.perf_counter()
        jobs = []
        general_names = {p.name for p in self.providers if getattr(p, 'general_web', True)}
        for source in sources:
            source_deadline = min(deadline, time.monotonic()+self.settings.discovery_provider_timeout)
            request = WebRequest(query, q, threading.Event(), search_type)
            job = self._start(source, request, source_deadline)
            job['general_web'] = source.name in general_names
            jobs.append(job)
        def useful(responses):
            items = []
            for response in responses:
                if response.provider not in general_names:
                    continue
                for index, row in enumerate(self._rows(response).rows, 1):
                    if item := WebCandidate.from_row(row, response.provider, index):
                        items.append(item)
            # Direct financial evidence must get its own bounded opportunity.
            if q.intent == 'financial' and any(job['name'] == 'market' for job in jobs) and not any(r.provider == 'market' for r in responses):
                return 0
            return len(rank(items, q, final=not fetch_pages))
        responses, provider_status = self._collect(jobs, deadline, useful)
        provider_ms = (time.perf_counter()-provider_started)*1000
        errors = [s['provider']+': '+s['error'] for s in provider_status if s.get('error')]
        candidates, answer = [], None
        raw_count = 0
        for response in responses:
            batch = self._rows(response)
            errors.extend(response.provider+': '+str(e)[:300] for e in batch.warnings)
            if batch.answer and _answer_allowed(batch.answer, q):
                answer = batch.answer
            raw_count += len(batch.rows)
            for index, row in enumerate(batch.rows[:self.settings.live_max_candidates], 1):
                if item := WebCandidate.from_row(row, response.provider, index):
                    candidates.append(item)
        candidates = merge(candidates)
        structured_market = bool(answer and answer.get('type') in ('stock_quote', 'stock_history'))
        fetch_pages = fetch_pages and not structured_market
        normalized_count = len(candidates)
        selection_started = time.perf_counter()
        from .webfocus import seeds, links, sitemap_links
        focus_seeds = seeds(candidates, q) if fetch_pages and search_type == 'web' else []
        candidates = rank(candidates, q, final=False)[:self.settings.live_max_candidates]
        candidates.extend(item for item in focus_seeds if item.url not in {c.url for c in candidates})
        selection_ms = (time.perf_counter()-selection_started)*1000
        fetch_started = time.perf_counter()
        session = WebFetchSession(self.settings, threading.Event())
        fetch_status = []
        if live and fetch_pages and search_type == 'web' and time.monotonic() < deadline:
            available = [i for i in candidates if i.source_type not in ('market_data', 'local_index')]
            selected = (focus_seeds + [i for i in available if i not in focus_seeds])[:self.settings.live_fetch_pages]
            page_deadline = min(deadline, time.monotonic()+self.settings.live_fetch_timeout)
            # Finite waves cap per-query parallelism independently of the global worker pool.
            for begin in range(0, len(selected), self.settings.live_fetch_concurrency):
                if time.monotonic() >= page_deadline:
                    break
                wave = selected[begin:begin+self.settings.live_fetch_concurrency]
                page_jobs = [self._start(EnrichmentJob(session, 'page:'+str(begin+i)), item, page_deadline)
                             for i, item in enumerate(wave)]
                pages, states = self._collect(page_jobs, page_deadline)
                fetch_status.extend(states)
                replacements = {s.provider: s.results for s in pages if s.status == 'ok' and isinstance(s.results, WebCandidate)}
                for index, item in enumerate(wave):
                    name = 'page:'+str(begin+index)
                    if name in replacements:
                        candidates[candidates.index(item)] = replacements[name]
                    else:
                        state = next((s for s in states if s['provider'] == name), {})
                        item.fetch_status = state.get('status', 'not_fetched')
                        if state.get('error'):
                            errors.append('Page enrichment failed for '+urlsplit(item.url).hostname+': '+state['error'][:200])
            # One focused link wave shares the same deadline, robots policy and byte/request budget.
            known_urls = {item.url for item in candidates}
            focused = []
            if q.intent == 'tech_docs':
                for item in list(candidates):
                    if item.fetch_status == 'fetched':
                        for linked in links(item, q):
                            if linked.url not in known_urls:
                                known_urls.add(linked.url)
                                focused.append(linked)
            focus_deadline = page_deadline
            sufficient_doc = any(item.fetch_status == 'fetched' and item.features.get('documentation_structure', 0) >= .5
                                 and item.features.get('coverage', 0) >= .8 for item in candidates)
            if q.intent == 'tech_docs' and focus_seeds and not focused and not sufficient_doc:
                # The bounded direct-fetch window has ended; focused discovery can use
                # the remaining global budget, sharing the same request/byte limits.
                focus_deadline = deadline
                seed = next((item for item in candidates if item.url in {seed.url for seed in focus_seeds}
                             and item.fetch_status == 'fetched'), None)
                if seed is not None and time.monotonic() < focus_deadline:
                    try:
                        focused = sitemap_links(session, seed, q, focus_deadline)
                    except (FetchError, ValueError) as exc:
                        errors.append('Focused sitemap unavailable: '+str(exc)[:160])
            # Link labels are often short; inspect a bounded specific link before
            # applying the final page-content coverage threshold.
            focused = [item for item in focused if constraints(item, q, final=False)][:2]
            if focused and q.intent == 'tech_docs':
                focus_deadline = deadline
            if focused:
                candidates.extend(focused)
                link_jobs = [self._start(EnrichmentJob(session, 'link:'+str(i)), item, focus_deadline)
                             for i, item in enumerate(focused) if time.monotonic() < focus_deadline]
                pages, states = self._collect(link_jobs, focus_deadline)
                fetch_status.extend(states)
                for response in pages:
                    if response.status == 'ok' and isinstance(response.results, WebCandidate):
                        replacement = response.results
                        original = next((item for item in focused if item.original_url == replacement.original_url), None)
                        if original is not None:
                            candidates[candidates.index(original)] = replacement
            session.cancel.set()
        fetch_ms = (time.perf_counter()-fetch_started)*1000
        ranking_started = time.perf_counter()
        ranked = rank(candidates, q, final=True)
        chosen = ranked[offset:offset+limit]
        snippet_terms = analyze(query)
        result_rows = [item.result(index, explain, query_terms=snippet_terms) for index, item in enumerate(chosen, offset+1)]
        for row in result_rows:
            row['highlights'] = highlights(row['snippet'], query)
        evidence = []
        if fetch_evidence not in (False, 'false', '0', 0, 'no'):
            evidence = [{'document_id': None, 'url': i.url, 'title': i.title,
                         'retrieved_at': i.fetched_at, 'published_at': i.published_at,
                         'evidence_level': 'fetched_page' if i.fetch_status == 'fetched' else i.source_type,
                         'passages': i.evidence, 'text': ' … '.join(p['text'] for p in i.evidence)[:1800],
                         'injection_risk': i.injection_risk} for i in chosen]
        answer_status = 'available' if answer else 'not_requested'
        if answer_mode and not answer and q.intent == 'news':
            headlines = [{'title': item.title, 'url': item.url, 'published_at': item.published_at}
                         for item in chosen[:5] if item.published_at and not item.injection_risk]
            if headlines:
                answer = {'type': 'headlines', 'text': '\n'.join('- '+row['title'] for row in headlines),
                          'headlines': headlines, 'citations': [{'url': row['url'], 'title': row['title']} for row in headlines],
                          'verification': 'publisher_dated_headlines', 'inference': False}
                answer_status = 'source_headlines'
        if answer_mode and not answer:
            relations = set(relation_terms(q)) if q.intent == 'reference' else set()
            # Property questions need a validated claim, not an arbitrary passage
            # that mentions the same relation for a different person or subject.
            source = None if relations else next((i for i in chosen if i.evidence and not i.injection_risk
                                                 and i.features.get('coverage', 0) >= .8), None)
            if source:
                passage = next((p['text'] for p in source.evidence if not relations or relations & set(analyze(p['text']))), source.evidence[0]['text'])[:500]
                answer = {'type': 'extractive', 'text': passage,
                          'source': {'name': source.title, 'url': source.url},
                          'citations': [{'url': source.url, 'title': source.title, 'passage': passage}],
                          'evidence_level': 'fetched_page' if source.fetch_status == 'fetched' else source.source_type,
                          'verification': 'source_excerpt', 'inference': False}
                answer_status = 'source_excerpt'
            else:
                answer_status = 'insufficient_evidence'
        limitations = ['Results are a bounded search of available sources; coverage is not exhaustive.']
        configured_general = bool(general_names)
        if not configured_general:
            limitations.append('General live web discovery is unavailable: configure OWNSEARCH_SEARXNG_URL or OWNSEARCH_BRAVE_API_KEY. No general web provider was searched.')
        elif not live:
            limitations.append('Live discovery is disabled for this request.')
        elif not any(s['status'] == 'ok' and s['provider'] in general_names for s in provider_status):
            limitations.append('No general web provider completed successfully within the response budget.')
        if not query:
            limitations.append('Empty query; no sources were requested.')
        if not result_rows and not answer:
            limitations.append('No sufficiently relevant evidence was returned by the available sources.')
        if any(s['status'] in ('unfinished', 'timeout') for s in provider_status+fetch_status):
            limitations.append('Some work was unfinished at cutoff; its results were not included.')
        local_count = self.local_engine.index.doc_count if self.local_engine else 0
        ranking_ms = (time.perf_counter()-ranking_started)*1000
        took_ms = round((time.perf_counter()-started)*1000, 2)
        result = {'query': query, 'results': result_rows, 'evidence': evidence,
                  'provider': 'ownsearch', 'answer': answer, 'answer_status': answer_status,
                  'provider_errors': errors, 'provider_status': provider_status,
                  'providers_configured': {'local_index': self.settings.live_local_enabled,
                                           'searxng': bool(self.settings.searxng_url),
                                           'brave': bool(self.settings.brave_api_key), 'general_web': configured_general},
                  'coverage': {'index_documents': local_count, 'matched_documents': len(ranked),
                               'mode': 'live_web', 'intent': q.intent,
                               'low_confidence': not bool(result_rows or answer),
                               'message': ' '.join(limitations), 'local_index_required': False},
                  'query_understanding': q.normalized(), 'limitations': limitations,
                  'total_candidates': raw_count, 'offset': offset, 'limit': limit,
                  'has_more': len(ranked) > offset+limit, 'took_ms': took_ms,
                  'timed_out': time.monotonic() >= deadline or any(s['status'] == 'timeout' for s in provider_status+fetch_status),
                  'retrieved_at': utc_now(), 'notice': UNTRUSTED_NOTICE,
                  'images': [image for i in chosen for image in i.images] if search_type == 'images' else [],
                  'fetch_status': fetch_status, 'discovery_status': {
                      'state': 'partial' if any(s['status'] in ('timeout', 'unfinished') for s in provider_status+fetch_status) else 'finished',
                      'unfinished_sources': sum(s['status'] in ('timeout', 'unfinished') for s in provider_status),
                      'background_enrichment': False},
                  'trace': {'candidate_rows': raw_count, 'unique_urls': normalized_count,
                            'selected_candidates': len(candidates), 'returned_results': len(result_rows),
                            'pages_fetched': sum(i.fetch_status == 'fetched' for i in candidates),
                            'pages_failed': sum(s['status'] in ('error', 'timeout', 'busy') for s in fetch_status),
                            'pages_skipped': sum(i.fetch_status == 'not_fetched' for i in candidates),
                            'local_results': sum(i.provider == 'local_index' for i in chosen),
                            'page_requests': session.requests, 'decoded_bytes': session.decoded_bytes,
                            'persistent_pages_written': 0, 'cache_hit': False,
                            'structured_market_answer': structured_market},
                  'timing': {'total_ms': took_ms, 'parse_ms': round(parse_ms, 2),
                             'providers_ms': round(provider_ms, 2), 'fetch_wall_ms': round(fetch_ms, 2),
                             'fetch_worker_ms': round(session.network_ms, 2), 'extraction_worker_ms': round(session.extraction_ms, 2),
                             'candidate_ranking_ms': round(selection_ms, 2), 'final_ranking_ms': round(ranking_ms, 2)}}
        with self._metrics_lock:
            self._metrics['requests'] += 1
            self._metrics['empty_results'] += int(not result_rows and not answer)
            self._metrics['provider_attempts'] += len(provider_status)
            self._metrics['provider_failures'] += sum(s['status'] != 'ok' for s in provider_status)
            self._metrics['pages_fetched'] += result['trace']['pages_fetched']
            self._metrics['page_failures'] += result['trace']['pages_failed']
            self._metrics['low_evidence_results'] += sum(i.fetch_status != 'fetched' for i in chosen)
        # Do not cache transient failures, unfinished work, or financial data.
        if use_cache and self.settings.live_cache_ttl > 0 and not errors and not result['timed_out'] and q.intent != 'financial':
            self.cache.put(key, copy.deepcopy(result))
        return result

    def stats(self):
        with self._metrics_lock:
            metrics = dict(self._metrics)
        return {'mode': 'live', 'persistent_document_storage': False,
                'documents': self.local_engine.index.doc_count if self.local_engine else 0,
                'generation': self.local_engine.index.generation if self.local_engine else 0,
                'general_providers': [p.name for p in self.providers], 'live_metrics': metrics,
                'cache': {'enabled': self.settings.live_cache_ttl > 0, 'entries': len(self.cache.data)}}

    def document(self, **kwargs):
        return self.local_engine.document(**kwargs) if self.local_engine else None

    def fetch_url(self, url):
        """Legacy /fetch shape, now request-only in live mode; no implicit indexing."""
        safe = web_url(url)
        if not safe:
            raise ValueError('Provide an absolute public HTTP(S) URL without credentials.')
        deadline = time.monotonic()+min(self.settings.live_fetch_timeout, self.settings.discovery_timeout)
        if not self._slots.acquire(timeout=max(0, deadline-time.monotonic())):
            raise Busy('Too many concurrent live requests')
        session = WebFetchSession(self.settings, threading.Event())
        try:
            candidate = WebCandidate.from_row({'url': safe, 'title': safe}, 'direct_url', 1)
            job = self._start(EnrichmentJob(session, 'page:direct'), candidate, deadline)
            job['cancel'] = session.cancel
            responses, statuses = self._collect([job], deadline)
            page = next((r.results for r in responses if r.status == 'ok' and isinstance(r.results, WebCandidate)), None)
            if page is None:
                return 502, {'url': safe, 'error': 'Page unavailable within live fetch policy/budget.',
                             'fetch_status': statuses, 'persistent_storage': False}
            return 200, {'url': safe, 'final_url': page.url, 'status': page.http_status, 'result': 'ok',
                         'kind': page.detected_kind, 'extraction_status': 'ok', 'persistent_storage': False,
                         'note': 'Live mode returns transient content; no indexing or page persistence occurred.',
                         'document': {'id': None, 'url': page.url, 'title': page.title,
                                      'text': page.content, 'fetched_at': page.fetched_at,
                                      'published_at': page.published_at, 'lang': page.language,
                                      'images': page.images, 'provenance': page.provenance}}
        finally:
            session.cancel.set()
            self._slots.release()

    def search_json(self, query, limit=10, fetch_evidence=True, **kwargs):
        return json.dumps(self.search(query, limit, fetch_evidence, **kwargs), ensure_ascii=False)

    def diagnostics(self, check=False):
        report = {'mode': 'live', 'local_index_required': False, 'persistent_document_storage': False,
                  'general_discovery_configured': bool(self.providers),
                  'providers': [{'name': p.name, 'configured': True} for p in self.providers],
                  'checked': False, 'note': 'For the bundled source run discovery setup then discovery serve. Alternatively configure OWNSEARCH_SEARXNG_URL or OWNSEARCH_BRAVE_API_KEY; no paid service is enabled automatically.'}
        if check and self.providers:
            result = self.search('web search', fetch_evidence=False, fetch_pages=False, use_cache=False)
            report.update(checked=True, provider_status=result['provider_status'],
                          result_count=len(result['results']), errors=result['provider_errors'])
        return report


def search_engine(settings=None):
    """Default entry point; legacy SearchEngine remains available explicitly."""
    settings = settings or Settings.load()
    if settings.search_mode == 'live':
        return LiveSearch(settings)
    if settings.search_mode != 'local':
        raise ValueError('search_mode must be live or local')
    from .engine import SearchEngine
    return SearchEngine(settings=settings)
