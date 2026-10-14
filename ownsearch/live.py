"""Bounded, safe and serial page fetching for query-time discovery."""
import time

from .fetcher import FetchError, Fetcher
from .robots import RobotsPolicy
from .util import origin_of


class PageClient:
    def __init__(self, settings, deadline):
        self.settings = settings
        self.deadline = deadline
        self.fetcher = Fetcher(settings)
        self.requests = 0
        self.policies = {}
        self.next_request = {}
        self.responses = {}
        self.failures = {}

    def raw(self, url, **kwargs):
        return self.fetcher.fetch(url, deadline=self.deadline, retries=0,
                                  before_request=self._reserve, **kwargs)

    def _reserve(self, url):
        if self.requests >= self.settings.discovery_max_requests or time.monotonic() >= self.deadline:
            raise FetchError("Discovery budget exhausted", "timeout")
        self.requests += 1

    def policy(self, url):
        origin = origin_of(url)
        if origin not in self.policies:
            try:
                r = self.raw(origin + "/robots.txt", max_bytes=512_000)
                if 200 <= r.status < 300:
                    policy = RobotsPolicy.parse(r.body.decode("utf-8", "replace"), self.settings.robots_token)
                elif 400 <= r.status < 500 and r.status != 429:
                    policy = RobotsPolicy.allow_all(r.status)
                else:
                    policy = RobotsPolicy.disallow_all(r.status)
            except FetchError:
                policy = RobotsPolicy.disallow_all()
            self.policies[origin] = policy
        return self.policies[origin]

    def allowed(self, url):
        return self.policy(url).allowed(url)

    def fetch(self, url, **kwargs):
        if url in self.failures:
            raise self.failures[url]
        if url in self.responses:
            return self.responses[url]
        policy = self.policy(url)
        if not policy.allowed(url):
            raise FetchError("Disallowed by robots.txt", "robots")
        origin = origin_of(url)
        delay = max(self.settings.default_delay, policy.crawl_delay or 0)
        wait = self.next_request.get(origin, 0) - time.monotonic()
        if wait > 0:
            if time.monotonic() + wait >= self.deadline:
                raise FetchError("Politeness delay exceeds discovery budget", "timeout")
            time.sleep(wait)
        try:
            r = self.raw(url, allow=self.allowed, **kwargs)
        except FetchError as exc:
            self.failures[url] = exc
            self.next_request[origin] = time.monotonic() + delay
            raise
        self.next_request[origin] = time.monotonic() + delay
        if r.status in (429, 503):
            try:
                backoff = float(r.headers.get("x-retry-after") or 60)
            except ValueError:
                backoff = 60
            self.next_request[origin] = time.monotonic() + max(delay, backoff)
        self.responses[url] = r
        return r
