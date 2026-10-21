"""Bounded request-only enrichment using the existing pinned safe HTTP client."""
import threading
import time
from dataclasses import replace
from urllib.parse import urljoin, urlsplit

from .evidence import injection_flags
from .extract import extract, sniff
from .fetcher import Fetcher, FetchError, decode_content
from .robots import RobotsPolicy
from .util import origin_of, utc_now
from .webmodels import web_url


class WebFetchSession(Fetcher):
    """Shared per-query request/decoded-byte budgets and per-origin politeness."""
    def __init__(self, settings, cancel):
        super().__init__(replace(settings, ocr='off'))
        self.cancel = cancel
        self.guard = threading.Lock()
        self.host_locks = {}
        self.policy_locks = {}
        self.next_request = {}
        self.policies = {}
        self.requests = self.decoded_bytes = self.reserved_bytes = 0
        self.network_ms = self.extraction_ms = 0.0

    def _host_lock(self, table, host):
        with self.guard:
            return table.setdefault(host, threading.Lock())

    def _request_once(self, url, headers, max_bytes, method='GET', deadline=None):
        deadline = deadline or time.monotonic() + self.settings.live_fetch_timeout
        origin = origin_of(url)
        lock = self._host_lock(self.host_locks, origin)
        if not lock.acquire(timeout=max(0, deadline-time.monotonic())):
            raise FetchError('Per-host capacity deadline', 'timeout')
        capacity = 0
        started = time.perf_counter()
        try:
            if self.cancel.is_set():
                raise FetchError('Request cancelled', 'timeout')
            wait = max(0, self.next_request.get(origin, 0)-time.monotonic())
            if time.monotonic()+wait >= deadline or self.cancel.wait(wait):
                raise FetchError('Host delay exceeds request budget', 'timeout')
            with self.guard:
                if self.requests >= self.settings.live_max_requests:
                    raise FetchError('Page request limit reached', 'timeout')
                capacity = max(0, min(max_bytes, self.settings.live_max_total_bytes-self.decoded_bytes-self.reserved_bytes))
                if capacity <= 0:
                    raise FetchError('Total page byte limit reached', 'too_large')
                self.reserved_bytes += capacity
                self.requests += 1
            status, response_headers, body, truncated = super()._request_once(url, headers, capacity, method, deadline)
            if truncated:
                raise FetchError('Page exceeds response size limit', 'too_large')
            body = decode_content(body, response_headers.get('content-encoding'), capacity)
            response_headers = dict(response_headers)
            response_headers.pop('content-encoding', None)  # decoded once, before charging the shared budget
            with self.guard:
                self.decoded_bytes += len(body)
            return status, response_headers, body, False
        finally:
            with self.guard:
                self.reserved_bytes -= capacity
                self.network_ms += (time.perf_counter()-started)*1000
            delay = max(self.settings.default_delay, getattr(self.policies.get(origin), 'crawl_delay', 0) or 0)
            self.next_request[origin] = time.monotonic() + delay
            lock.release()

    def policy(self, url, deadline):
        origin = origin_of(url)
        lock = self._host_lock(self.policy_locks, origin)
        if not lock.acquire(timeout=max(0, deadline-time.monotonic())):
            raise FetchError('Robots policy deadline', 'timeout')
        try:
            if origin not in self.policies:
                r = super().fetch(origin+'/robots.txt', retries=0, deadline=deadline, max_bytes=128_000, preserve_query=True)
                if r.status == 200:
                    policy = RobotsPolicy.parse(r.body.decode('utf-8', 'replace'), self.settings.robots_token)
                elif 400 <= r.status < 500 and r.status != 429:
                    policy = RobotsPolicy.allow_all(r.status)
                else:
                    policy = RobotsPolicy.disallow_all(r.status)
                self.policies[origin] = policy
            return self.policies[origin]
        finally:
            lock.release()

    def page(self, url, deadline):
        if not self.policy(url, deadline).allowed(url):
            raise FetchError('Page disallowed by robots.txt', 'robots')
        return super().fetch(url, retries=0, deadline=deadline, max_bytes=self.settings.live_max_page_bytes,
                             allow=lambda target: self.policy(target, deadline).allowed(target), preserve_query=True)

    def enrich(self, candidate, deadline):
        if self.cancel.is_set() or time.monotonic() >= deadline:
            raise FetchError('Page deadline expired', 'timeout')
        response = self.page(candidate.url, deadline)
        if not 200 <= response.status < 300:
            raise FetchError('Page HTTP '+str(response.status), 'http')
        # Live path does not invoke OCR, JS, archive or document subprocesses.
        if sniff(response.body, response.content_type, response.final_url) not in ('html', 'text'):
            raise FetchError('Unsupported live content type', 'content_type')
        started = time.perf_counter()
        ext = extract(response.body, response.final_url, response.content_type, self.settings)
        with self.guard:
            self.extraction_ms += (time.perf_counter()-started)*1000
        if not ext.text or ext.noindex:
            raise FetchError('Page has no usable text or requests noindex', 'no_content')
        final_url = web_url(response.final_url)
        if not final_url:
            raise FetchError('Unsafe result URL', 'blocked')
        item = replace(candidate, provenance=list(candidate.provenance), images=list(candidate.images))
        item.url = final_url
        canonical = web_url(ext.canonical)
        # Cross-origin canonicals can be spoofed and must not collapse unrelated sources.
        if canonical and urlsplit(canonical).netloc == urlsplit(final_url).netloc:
            item.canonical = canonical
        item.title = ext.title[:300] or item.title
        item.content = ext.text[:self.settings.live_max_text_chars]
        item.headings = ext.headings[:50]
        item.links = ext.links[:self.settings.discovery_sitemap_limit]
        item.feeds = [] if ext.nofollow else [url for url in ext.feeds[:10] if web_url(url)]
        item.language = ext.lang or item.language
        if ext.published_at:
            inferred = ext.metadata.get('publication_date_source') == 'url_inferred'
            if inferred:
                item.provenance.append({'provider': 'url_date', 'url': final_url,
                                        'published_at': ext.published_at, 'evidence_level': 'inferred_url_date'})
            elif item.published_at and item.published_at != ext.published_at:
                item.provenance.append({'provider': 'page_metadata', 'url': final_url,
                                        'published_at': ext.published_at, 'evidence_level': 'conflicting_publication_metadata'})
                item.publication_conflict = True
                item.published_at = ext.published_at
                item.publication_source = 'page_metadata'
            elif not inferred:
                item.published_at = ext.published_at
                item.publication_source = 'page_metadata'
        item.fetched_at = utc_now()
        item.content_type = response.content_type
        item.detected_kind = ext.kind
        item.http_status = response.status
        item.fetch_status = 'fetched'
        item.source_type = 'web_page'
        item.provenance.append({'provider': 'page_fetch', 'url': final_url, 'evidence_level': 'fetched_page',
                                'retrieved_at': item.fetched_at})
        item.injection_risk = bool(injection_flags(item.content))
        metadata = ext.metadata
        # Open Graph/Twitter images are page metadata, never verified query-specific images.
        image = web_url(urljoin(final_url, metadata.get('og:image') or metadata.get('twitter:image') or '')) if metadata.get('og:image') or metadata.get('twitter:image') else None
        if image:
            item.images.append({'image_url': image, 'thumbnail_url': None, 'page_url': final_url,
                                'caption': '', 'provider': 'page_metadata', 'attribution': 'page metadata',
                                'relevance_verified': False})
        return item


class EnrichmentJob:
    def __init__(self, session, name):
        self.session, self.name = session, name
    def search(self, item, deadline):
        return self.session.enrich(item, deadline)
