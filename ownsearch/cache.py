"""Bounded, expiring memory cache with integrated Inverted Index and query-result caching."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
import json
import threading
import time

from .index import InvertedIndex

class PageCache:
    def __init__(self, entries, max_bytes, ttl):
        self.entries, self.max_bytes, self.ttl = entries, max_bytes, ttl
        self.lock = threading.Lock()
        self.rows = OrderedDict()
        self.bytes = 0
        self.index = InvertedIndex()
        self.query_cache = OrderedDict()
        self.aliases = OrderedDict()
        self.max_query_cache_entries = 256

    def _prune(self):
        now = time.monotonic()
        for key, (expires, size, _) in list(self.rows.items()):
            if expires <= now:
                self.bytes -= size
                del self.rows[key]
                self.index.remove_url(key)
        self.index.prune(now)
        # Prune query cache
        for key, (expires, _) in list(self.query_cache.items()):
            if expires <= now:
                del self.query_cache[key]
        # Prune aliases
        for key, (expires, _) in list(self.aliases.items()):
            if expires <= now:
                del self.aliases[key]

    def put(self, url, page, ttl=None):
        effective_ttl = self.ttl if ttl is None else ttl
        size = len(json.dumps(asdict(page), ensure_ascii=False).encode('utf-8'))
        if size > self.max_bytes or effective_ttl <= 0:
            return
        now = time.monotonic()
        expires_at = now + effective_ttl
        with self.lock:
            self._prune()
            if url in self.rows:
                self.bytes -= self.rows.pop(url)[1]
                self.index.remove_url(url)
            self.rows[url] = (expires_at, size, deepcopy(page))
            self.bytes += size
            self.index.add_page(page, expires_at=expires_at)
            self.query_cache.clear()
            while len(self.rows) > self.entries or self.bytes > self.max_bytes:
                evicted_url, (_, oldsize, _) = self.rows.popitem(last=False)
                self.bytes -= oldsize
                self.index.remove_url(evicted_url)

    def snapshot(self):
        with self.lock:
            self._prune()
            return [deepcopy(row[2]) for row in self.rows.values()]

    def search_index(self, q, limit=10, search_type='web'):
        """Fast index-based candidate retrieval without full table scan."""
        with self.lock:
            self._prune()
            return self.index.search(q, limit=limit, search_type=search_type)

    def search_images(self, q, limit=20):
        with self.lock:
            self._prune()
            return self.index.search_images(q, limit=limit)

    def get_query_result(self, cache_key):
        """Retrieve cached query result if valid."""
        with self.lock:
            now = time.monotonic()
            if cache_key in self.query_cache:
                expires, result = self.query_cache[cache_key]
                if expires > now:
                    # Move to end (LRU)
                    self.query_cache.move_to_end(cache_key)
                    return deepcopy(result)
                del self.query_cache[cache_key]
        return None

    def put_query_result(self, cache_key, result, ttl=60.0):
        """Store query result with TTL."""
        if ttl <= 0:
            return
        with self.lock:
            now = time.monotonic()
            if cache_key in self.query_cache:
                del self.query_cache[cache_key]
            self.query_cache[cache_key] = (now + ttl, deepcopy(result))
            while len(self.query_cache) > self.max_query_cache_entries:
                self.query_cache.popitem(last=False)

    def put_alias(self, alias_url, target_url, ttl=None):
        if not alias_url or not target_url or alias_url == target_url:
            return
        now = time.monotonic()
        expires = now + (self.ttl if ttl is None else ttl)
        with self.lock:
            self.aliases[alias_url] = (expires, target_url)

    def get_alias(self, alias_url):
        if not alias_url:
            return None
        now = time.monotonic()
        with self.lock:
            if alias_url in self.aliases:
                expires, target = self.aliases[alias_url]
                if expires > now:
                    return target
                del self.aliases[alias_url]
        return None

    def clear(self):
        with self.lock:
            self.rows.clear()
            self.bytes = 0
            self.index.clear()
            self.query_cache.clear()
            self.aliases.clear()

    def stats(self):
        with self.lock:
            self._prune()
            istats = self.index.stats()
            return {
                'pages': len(self.rows),
                'bytes': self.bytes,
                'ttl_seconds': self.ttl,
                'persistent': False,
                'query_cache_entries': len(self.query_cache),
                **istats
            }
