"""Direct safe fetching, with query budgets and shared cross-query origin policy."""
import json
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .evidence import injection_flags
from .extract import extract, sniff, Extracted, decode_text
from .native_search import discover_search_forms, independent_url
from .extract.feeds import parse_feed
from .fetcher import Fetcher, FetchError, decode_content
from .robots import RobotsPolicy
from .util import origin_of, utc_now
from .webmodels import WebCandidate, web_url

@dataclass
class OriginGate:
    lock: object = field(default_factory=threading.Lock)
    policy_lock: object = field(default_factory=threading.Lock)
    next_request: float = 0.0
    cooldown: float = 0.0
    policy: object = None
    policy_expires: float = 0.0
    users: int = 0

class OriginState:
    def __init__(self, limit):
        self.limit, self.lock, self.gates = limit, threading.Lock(), OrderedDict()
    def get(self, origin):
        with self.lock:
            if origin in self.gates:
                self.gates.move_to_end(origin)
                self.gates[origin].users += 1
                return self.gates[origin]
            # Never evict a live politeness clock or a denial to make room.
            now = time.monotonic()
            for key, gate in list(self.gates.items()):
                if (len(self.gates) >= self.limit and gate.next_request <= now and gate.cooldown <= now
                        and gate.policy_expires <= now and not gate.users and not gate.lock.locked() and not gate.policy_lock.locked()):
                    del self.gates[key]
            if len(self.gates) >= self.limit:
                raise FetchError('Origin capacity reached; wait for cache expiry', 'capacity')
            gate = self.gates[origin] = OriginGate(users=1)
            return gate

    def release(self, gate):
        with self.lock:
            gate.users -= 1

@dataclass
class CrawledPage:
    url: str
    item: object = None
    links: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    kind: str = ''
    search_forms: list = field(default_factory=list)
    search_result_links: list = field(default_factory=list)
    requested_url: str = ''

class WebFetchSession(Fetcher):
    def __init__(self, settings, cancel, origins=None):
        super().__init__(settings)
        self.cancel = cancel
        self.origins = origins or OriginState(settings.origin_cache_entries)
        self.guard = threading.Lock()
        self.requests = self.decoded_bytes = self.reserved_bytes = self.budget_bytes = 0
        self.allowed_origins = None
        self.native_targets = set()

    def _request_once(self, url, headers, max_bytes, method='GET', deadline=None):
        deadline = deadline or time.monotonic() + self.settings.fetch_timeout
        if not independent_url(url, self.settings.allow_private_hosts):
            raise FetchError('Search services or unsafe URLs are not crawl sources', 'blocked')
        origin = origin_of(url)
        if self.allowed_origins is not None and origin not in self.allowed_origins:
            raise FetchError('Redirect outside configured crawl origins', 'scope')
        gate = self.origins.get(origin)
        if not gate.lock.acquire(timeout=max(0, deadline-time.monotonic())):
            self.origins.release(gate)
            raise FetchError('Origin capacity deadline', 'timeout')
        capacity = charged = 0
        attempted = completed = False
        try:
            if gate.cooldown > time.monotonic():
                raise FetchError('Origin in cooldown after access denial or rate limit', 'cooldown')
            if self.cancel.is_set():
                raise FetchError('Crawl cancelled', 'timeout')
            wait = max(0, gate.next_request-time.monotonic())
            if time.monotonic()+wait >= deadline or self.cancel.wait(wait):
                raise FetchError('Crawl delay exceeds query deadline', 'timeout')
            with self.guard:
                if self.requests >= self.settings.max_requests_per_query:
                    raise FetchError('Query request limit reached', 'budget')
                capacity = max(0, min(max_bytes, self.settings.max_bytes_per_query-self.budget_bytes-self.reserved_bytes))
                if not capacity:
                    raise FetchError('Query byte limit reached', 'too_large')
                self.reserved_bytes += capacity
                self.requests += 1
            attempted = True
            status, response_headers, body, truncated = super()._request_once(url, headers, capacity, method, deadline)
            if status in (401, 403, 429, 503):
                seconds = 60.0
                retry = response_headers.get('retry-after', '')
                try:
                    seconds = max(seconds, float(retry))
                except ValueError:
                    try:
                        seconds = max(seconds, parsedate_to_datetime(retry).timestamp()-time.time())
                    except (TypeError, ValueError, OverflowError):
                        pass
                gate.cooldown = time.monotonic() + seconds
            if truncated:
                raise FetchError('Response exceeds page byte limit', 'too_large')
            wire_size = len(body)
            body = decode_content(body, response_headers.get('content-encoding'), capacity)
            charged = max(wire_size, len(body))
            completed = True
            response_headers = dict(response_headers)
            response_headers.pop('content-encoding', None)
            with self.guard:
                self.decoded_bytes += len(body)
            return status, response_headers, body, False
        finally:
            with self.guard:
                self.reserved_bytes -= capacity
                self.budget_bytes += charged if completed else capacity if attempted else 0
            if attempted:
                gate.next_request = time.monotonic() + max(self.settings.default_delay,
                                                          getattr(gate.policy, 'crawl_delay', 0) or 0)
            gate.lock.release()
            self.origins.release(gate)

    def policy(self, url, deadline):
        origin = origin_of(url)
        gate = self.origins.get(origin)
        if not gate.policy_lock.acquire(timeout=max(0, deadline-time.monotonic())):
            self.origins.release(gate)
            raise FetchError('Robots policy deadline', 'timeout')
        try:
            if gate.policy is None or gate.policy_expires <= time.monotonic():
                r = super().fetch(origin+'/robots.txt', retries=0, deadline=deadline,
                                  max_bytes=128_000, preserve_query=True)
                if r.status == 200:
                    policy = RobotsPolicy.parse(r.body.decode('utf-8', 'replace'), self.settings.robots_token)
                elif 400 <= r.status < 500 and r.status not in (401, 403, 429):
                    policy = RobotsPolicy.allow_all(r.status)
                else:
                    policy = RobotsPolicy.disallow_all(r.status)
                gate.policy = policy
                gate.policy_expires = time.monotonic() + self.settings.robots_ttl
            return gate.policy
        finally:
            gate.policy_lock.release()
            self.origins.release(gate)

    def page(self, url, deadline):
        if not self.policy(url, deadline).allowed(url):
            raise FetchError('Disallowed by robots.txt', 'robots')
        return super().fetch(url, retries=0, deadline=deadline, max_bytes=self.settings.max_page_bytes,
                             allow=lambda target: self.policy(target, deadline).allowed(target), preserve_query=True)

    def crawl(self, url, deadline):
        policy = self.policy(url, deadline)
        response = self.page(url, deadline)
        if not 200 <= response.status < 300:
            raise FetchError('HTTP ' + str(response.status), 'http')
        data = response.body
        if re.search(rb'<!\s*(DOCTYPE|ENTITY)\b', data, re.I) and sniff(data, response.content_type, response.final_url) in ('feed', 'sitemap', 'xml'):
            raise FetchError('DTD/entity XML is unsupported', 'content_type')
        kind = sniff(data, response.content_type, response.final_url)
        if kind in ('pdf', 'zip', 'gzip'):
            remaining = min(self.settings.document_timeout, deadline-time.monotonic())
            if remaining <= 0:
                raise FetchError('Document deadline', 'timeout')
            try:
                proc = subprocess.run([sys.executable, '-m', 'ownsearch.document_worker', response.final_url,
                                       response.content_type], input=data, capture_output=True,
                                      timeout=remaining, cwd=str(Path(__file__).resolve().parent.parent))
                if proc.returncode:
                    raise FetchError('Document extraction failed or exceeded resource limit', 'extraction')
                ext = Extracted(**json.loads(proc.stdout))
            except (subprocess.TimeoutExpired, ValueError):
                raise FetchError('Document extraction deadline or invalid output', 'extraction')
        elif kind == 'feed':
            feed = parse_feed(data, response.final_url, publication_only=True)
            ext = Extracted(kind='feed', entries=feed['entries'] if feed else [])
        else:
            ext = extract(data, response.final_url, response.content_type, self.settings)
        if self.cancel.is_set() or time.monotonic() >= deadline:
            raise FetchError('Crawl unfinished at deadline; content excluded', 'timeout')
        final_url = web_url(response.final_url, self.settings.allow_private_hosts)
        if not final_url:
            raise FetchError('Unsafe result URL', 'blocked')
        header_robots = response.headers.get('x-robots-tag', '').lower()
        nofollow = ext.nofollow or 'nofollow' in header_robots or 'none' in header_robots
        noindex = ext.noindex or 'noindex' in header_robots or 'none' in header_robots
        links = []
        if not nofollow:
            links.extend((link[0], link[1], 'page') for link in ext.links if not link[2])
            links.extend((link, '', 'feed') for link in ext.feeds)
            links.extend((row['url'], row.get('title', ''), 'page') for row in ext.entries)
            links.extend((row[0], '', 'page') for row in ext.sitemap_urls)
        maps = [] if nofollow else list(policy.sitemaps) + [row[0] for row in ext.sitemaps]
        page = CrawledPage(final_url, links=links[:self.settings.max_sitemap_urls],
                           sitemaps=maps[:self.settings.max_sitemap_urls], kind=ext.kind,
                           requested_url=url)
        if self.settings.native_search_enabled and ext.kind == 'html' and not nofollow:
            page.search_forms = discover_search_forms(decode_text(data, response.content_type), final_url, self.settings.allow_private_hosts)
            if url in self.native_targets:
                # DOM-derived heading text identifies result headings. It grants
                # crawl priority only, never relevance or entity identity.
                page.search_result_links = [(link, anchor) for link, anchor, nofollow in ext.links
                                            if not nofollow and anchor and any(anchor in h for h in ext.headings)][:10]
        if not ext.text or noindex or ext.kind in ('binary', 'empty', 'feed', 'sitemap'):
            return page
        item = WebCandidate(ext.title[:300] or urlsplit(final_url).path.rsplit('/', 1)[-1] or urlsplit(final_url).hostname,
                            final_url, content=ext.text[:self.settings.max_text_chars],
                            headings=ext.headings[:50], language=ext.lang, fetched_at=utc_now(),
                            content_type=response.content_type, http_status=response.status,
                            detected_kind=ext.source_type if ext.kind == 'office' else ext.kind,
                            markdown=ext.markdown, code_blocks=ext.code_blocks)
        canonical = web_url(ext.canonical, self.settings.allow_private_hosts)
        if canonical and origin_of(canonical) == origin_of(final_url):
            item.canonical = canonical
        if ext.metadata.get('publication_date_source') != 'url_inferred':
            item.published_at, item.publication_source = ext.published_at, 'page_metadata' if ext.published_at else None
        item.injection_risk = bool(injection_flags(item.title+' '+item.content))
        item.provenance = [{'provider': 'ownsearch_crawler', 'url': final_url,
                            'retrieved_at': item.fetched_at, 'evidence_level': 'fetched_page'}]
        images = list(ext.metadata.get('images', []))
        og = ext.metadata.get('og:image') or ext.metadata.get('twitter:image')
        if og:
            images.append({'src': og, 'alt': ''})
        for row in images[:20]:
            image_url = web_url(urljoin(final_url, row.get('src', '')), self.settings.allow_private_hosts)
            if image_url:
                item.images.append({'image_url': image_url, 'page_url': final_url,
                                    'caption': row.get('alt', '') or item.title,
                                    'provider': 'fetched_page', 'relevance_verified': False})
        item.video = str(ext.metadata.get('og:type', '')).startswith('video') or bool(ext.metadata.get('og:video'))
        page.item = item
        return page
