"""Thread-safe per-provider request budgets and bounded circuit-breaker probes."""
from collections import deque
import math
import threading
import time


class ProviderUnavailable(Exception):
    def __init__(self, message, status='circuit_open', retry_after=None, http_status=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.http_status = http_status


class ProviderHealth:
    def __init__(self, settings, clock=None):
        self.settings = settings
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.reservations = deque()
        self.next_request = self.suspended_until = 0.0
        self.failures = self.openings = 0
        self.probing = False
        self.attempts = self.successes = self.errors = self.suppressed = 0
        self.last_status = None
        self.generation = 0

    def reserve(self, request, deadline, interval=None):
        now = self.clock()
        with self.lock:
            if now < self.suspended_until or self.probing:
                self.suppressed += 1
                raise ProviderUnavailable('Provider circuit open; request not sent.', retry_after=max(0, self.suspended_until-now))
            window = self.settings.provider_budget_window
            while self.reservations and self.reservations[0] <= now-window:
                self.reservations.popleft()
            if len(self.reservations) >= self.settings.provider_request_budget:
                self.suppressed += 1
                raise ProviderUnavailable('Provider request budget exhausted; request not sent.', 'rate_limited',
                                          max(0, self.reservations[0]+window-now))
            start = max(now, self.next_request)
            if start >= deadline:
                self.suppressed += 1
                raise ProviderUnavailable('Provider spacing exceeds deadline; request not sent.', 'rate_limited', start-now)
            self.next_request = start + max(self.settings.provider_min_interval, interval or 0)
            self.reservations.append(start)
            if self.failures:
                self.probing = True
            generation = self.generation
        if request.cancel.wait(max(0, start-now)) or self.clock() >= deadline:
            with self.lock:
                self.probing = False
            raise ProviderUnavailable('Provider request cancelled before sending.', 'cancelled')
        with self.lock:
            if generation != self.generation and self.clock() < self.suspended_until:
                self.suppressed += 1
                raise ProviderUnavailable('Provider suspended while request was waiting; request not sent.')
            self.attempts += 1
        return generation

    def success(self, status=200, generation=None):
        with self.lock:
            self.successes += 1
            if generation is not None and generation != self.generation:
                return  # a late success cannot erase a concurrent Retry-After
            self.failures = self.openings = 0
            self.probing = False
            self.suspended_until = 0.0
            self.last_status = status

    def failure(self, status=None, retry_after=None):
        with self.lock:
            self.errors += 1
            self.failures += 1
            self.probing = False
            self.last_status = status
            if status in (401, 403, 429, 503) or self.failures >= self.settings.provider_failure_threshold:
                self.openings += 1
                self.generation += 1
                delay = min(3600, max(1, self.settings.provider_cooldown) * 2 ** min(10, self.openings-1))
                if isinstance(retry_after, (int, float)) and math.isfinite(retry_after):
                    # A server's Retry-After is a floor, not capped by our own backoff.
                    delay = max(delay, retry_after)
                self.suspended_until = max(self.suspended_until, self.clock()+delay)

    def snapshot(self):
        now = self.clock()
        with self.lock:
            active = sum(stamp > now-self.settings.provider_budget_window for stamp in self.reservations)
            return {'circuit': 'half_open' if self.probing else 'open' if now < self.suspended_until else 'closed',
                    'consecutive_failures': self.failures, 'attempts': self.attempts,
                    'successes': self.successes, 'errors': self.errors, 'suppressed': self.suppressed,
                    'retry_after_seconds': round(max(0, self.suspended_until-now), 3),
                    'budget_remaining': max(0, self.settings.provider_request_budget-active),
                    'budget_window_seconds': self.settings.provider_budget_window,
                    'last_http_status': self.last_status}
