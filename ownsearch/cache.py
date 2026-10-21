"""Bounded, expiring memory cache. No persistence, index files or database."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
import json
import threading
import time

class PageCache:
    def __init__(self, entries, max_bytes, ttl):
        self.entries, self.max_bytes, self.ttl = entries, max_bytes, ttl
        self.lock = threading.Lock()
        self.rows = OrderedDict()
        self.bytes = 0

    def _prune(self):
        now = time.monotonic()
        for key, (expires, size, _) in list(self.rows.items()):
            if expires <= now:
                self.bytes -= size
                del self.rows[key]

    def put(self, url, page):
        size = len(json.dumps(asdict(page), ensure_ascii=False).encode('utf-8'))
        if size > self.max_bytes or self.ttl <= 0:
            return
        with self.lock:
            self._prune()
            if url in self.rows:
                self.bytes -= self.rows.pop(url)[1]
            self.rows[url] = (time.monotonic() + self.ttl, size, deepcopy(page))
            self.bytes += size
            while len(self.rows) > self.entries or self.bytes > self.max_bytes:
                _, (_, oldsize, _) = self.rows.popitem(last=False)
                self.bytes -= oldsize

    def snapshot(self):
        with self.lock:
            self._prune()
            return [deepcopy(row[2]) for row in self.rows.values()]

    def clear(self):
        with self.lock:
            self.rows.clear()
            self.bytes = 0

    def stats(self):
        with self.lock:
            self._prune()
            return {'pages': len(self.rows), 'bytes': self.bytes, 'ttl_seconds': self.ttl,
                    'persistent': False}
