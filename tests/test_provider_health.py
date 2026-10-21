"""Circuit and budget regressions with controlled clocks and no public HTTP."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import threading
import time
import unittest
from unittest.mock import patch

from ownsearch.provider_health import ProviderHealth, ProviderUnavailable
from ownsearch.webproviders import JsonProvider, ProviderError
from ownsearch.webmodels import WebRequest
from ownsearch.fetcher import Fetcher, FetchResult
from ownsearch.query import parse_query
from tests.test_live_web import settings


class ProviderHealthTests(unittest.TestCase):
    def request(self):
        return WebRequest('orbital sensor documentation', parse_query('orbital sensor documentation'), threading.Event())

    def test_access_denial_opens_immediately_and_returns_honest_state(self):
        p = JsonProvider(settings()); p.name = 'fixture'
        with patch.object(Fetcher, 'fetch', return_value=FetchResult('', '', 403, {}, b'')) as fetch:
            with self.assertRaises(ProviderError): p.request(self.request(), 'https://api.example.org/search', time.monotonic()+1)
            with self.assertRaises(ProviderError) as e: p.request(self.request(), 'https://api.example.org/search', time.monotonic()+1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(e.exception.status, 'circuit_open')
        self.assertEqual(p.health_snapshot()['last_http_status'], 403)
        self.assertEqual(p.health_snapshot()['suppressed'], 1)

    def test_retry_after_http_date_and_long_server_delay_are_respected(self):
        p = JsonProvider(settings(provider_cooldown=1)); p.name = 'fixture'
        date = format_datetime(datetime.now(timezone.utc)+timedelta(seconds=90), usegmt=True)
        with patch.object(Fetcher, 'fetch', return_value=FetchResult('', '', 429, {'retry-after': date}, b'')):
            with self.assertRaises(ProviderError): p.request(self.request(), 'https://api.example.org/search', time.monotonic()+1)
        self.assertGreater(p.health_snapshot()['retry_after_seconds'], 85)
        clock = [10.0]; h = ProviderHealth(settings(), clock=lambda: clock[0]); h.failure(429, 7200)
        self.assertEqual(h.snapshot()['retry_after_seconds'], 7200)

    def test_half_open_allows_only_one_probe_and_success_recovers(self):
        clock = [10.0]; h = ProviderHealth(settings(provider_cooldown=5), clock=lambda: clock[0])
        h.failure(503); clock[0] += 6
        generation = h.reserve(self.request(), 20)
        with self.assertRaises(ProviderUnavailable): h.reserve(self.request(), 20)
        self.assertEqual(h.snapshot()['circuit'], 'half_open')
        h.success(generation=generation)
        self.assertEqual(h.snapshot()['circuit'], 'closed')
        self.assertEqual(h.snapshot()['consecutive_failures'], 0)

    def test_late_inflight_success_cannot_erase_retry_after(self):
        clock = [10.0]; h = ProviderHealth(settings(), clock=lambda: clock[0])
        old = h.reserve(self.request(), 20)
        h.failure(429, 100)
        h.success(generation=old)
        self.assertEqual(h.snapshot()['circuit'], 'open')
        with self.assertRaises(ProviderUnavailable): h.reserve(self.request(), 20)

    def test_budget_and_request_spacing_fail_without_http(self):
        clock = [10.0]; h = ProviderHealth(settings(provider_request_budget=1, provider_budget_window=60), clock=lambda: clock[0])
        h.reserve(self.request(), 20)
        with self.assertRaises(ProviderUnavailable) as e: h.reserve(self.request(), 20)
        self.assertEqual(e.exception.status, 'rate_limited')
        clock[0] += 61
        h.reserve(self.request(), 80)
        self.assertEqual(h.snapshot()['attempts'], 2)

    def test_cancelled_request_does_not_make_a_network_attempt(self):
        h = ProviderHealth(settings()); req = self.request(); req.cancel.set()
        with self.assertRaises(ProviderUnavailable): h.reserve(req, time.monotonic()+1)
        self.assertEqual(h.snapshot()['attempts'], 0)

    def test_three_malformed_responses_open_circuit(self):
        p = JsonProvider(settings()); p.name = 'fixture'
        with patch.object(Fetcher, 'fetch', return_value=FetchResult('', '', 200, {}, b'not-json')) as fetch:
            for _ in range(4):
                with self.assertRaises(ProviderError): p.request(self.request(), 'https://api.example.org/search', time.monotonic()+1)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(p.health_snapshot()['errors'], 3)


if __name__ == '__main__': unittest.main()
