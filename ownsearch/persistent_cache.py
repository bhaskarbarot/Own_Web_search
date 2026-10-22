"""Optional bounded SQLite TTL cache of already-fetched pages and source memory.

This stores no web-wide index and requires no service or account. URL memory
contains only actually fetched URLs, never generated article addresses.
"""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import zlib
from .index import InvertedIndex
from .sourceplan import Source, plan_sources
from .webfetch import CrawledPage
from .webmodels import WebCandidate

class PersistentPageCache:
    def __init__(self, settings):
        self.settings = settings
        self.path = Path(settings.data_dir) / 'query_cache.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.errors = 0
        self.db = sqlite3.connect(str(self.path), timeout=1.0, check_same_thread=False)
        self.db.execute('PRAGMA auto_vacuum=INCREMENTAL')
        self.db.execute('PRAGMA journal_mode=DELETE')
        page_size = self.db.execute('PRAGMA page_size').fetchone()[0]
        pages = max(128, (settings.cache_max_bytes + 2 * 1024 * 1024) // page_size)
        self.db.execute('PRAGMA max_page_count=' + str(pages))
        self.db.execute('CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, payload BLOB NOT NULL, size INTEGER NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL, sha256 TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS memory(url TEXT PRIMARY KEY, description TEXT NOT NULL, seen REAL NOT NULL, expires REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS query_cache(cache_key TEXT PRIMARY KEY, payload BLOB NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS aliases(alias_url TEXT PRIMARY KEY, target_url TEXT NOT NULL, expires REAL NOT NULL)')
        self.db.commit()
        self.index = InvertedIndex()
        self.query_cache = OrderedDict()
        self.max_query_cache_entries = 256
        self._load_index()

    def _load_index(self):
        try:
            pages = self.snapshot()
            for page in pages:
                if page.item:
                    self.index.add_page(page)
        except Exception:
            pass

    def _prune(self):
        now = time.time()
        self.db.execute('DELETE FROM pages WHERE expires<=?', (now,))
        self.db.execute('DELETE FROM memory WHERE expires<=?', (now,))
        self.db.execute('DELETE FROM query_cache WHERE expires<=?', (now,))
        self.db.execute('DELETE FROM aliases WHERE expires<=?', (now,))

    def put(self, url, page, ttl=None):
        raw = json.dumps(asdict(page), ensure_ascii=False, separators=(',', ':')).encode()
        size = len(raw)
        if size > self.settings.cache_max_bytes:
            return False
        if ttl is None:
            ttl = {'feed': self.settings.cache_ttl_feed, 'sitemap': self.settings.cache_ttl_docs,
                   'pdf': self.settings.cache_ttl_docs, 'office': self.settings.cache_ttl_docs}.get(page.kind, self.settings.cache_ttl)
        if ttl <= 0:
            return False
        now = time.time()
        with self.lock:
            try:
                with self.db:
                    self._prune()
                    self.db.execute('DELETE FROM pages WHERE url=?', (url,))
                    while True:
                        count, total = self.db.execute('SELECT COUNT(*), COALESCE(SUM(size), 0) FROM pages').fetchone()
                        if count < self.settings.cache_entries and total + size <= self.settings.cache_max_bytes:
                            break
                        row = self.db.execute('SELECT url FROM pages ORDER BY touched LIMIT 1').fetchone()
                        if not row:
                            break
                        self.db.execute('DELETE FROM pages WHERE url=?', (row[0],))
                        self.index.remove_url(row[0])
                    self.db.execute('INSERT INTO pages VALUES(?,?,?,?,?,?)',
                                    (url, zlib.compress(raw), size, now + ttl, now, hashlib.sha256(raw).hexdigest()))
                self.db.execute('PRAGMA incremental_vacuum(16)')
                self.index.add_page(page, expires_at=time.monotonic() + ttl)
                self.query_cache.clear()
                return True
            except sqlite3.Error:
                self.errors += 1
                return False

    def snapshot(self, max_age=None):
        pages = []
        with self.lock:
            with self.db:
                self._prune()
            rows = self.db.execute('SELECT payload, sha256, touched FROM pages ORDER BY touched').fetchall()
        for payload, fingerprint, touched in rows:
            if max_age is not None and time.time() - touched > max_age:
                continue
            try:
                decoder = zlib.decompressobj()
                raw = decoder.decompress(payload, self.settings.cache_max_bytes + 1)
                if len(raw) > self.settings.cache_max_bytes or not decoder.eof or decoder.unconsumed_tail:
                    raise ValueError('Cache payload exceeds bounds')
                if hashlib.sha256(raw).hexdigest() != fingerprint:
                    raise ValueError('Cache payload changed')
                row = json.loads(raw)
                if row.get('item'):
                    valid_keys = WebCandidate.__dataclass_fields__.keys()
                    filtered = {k: v for k, v in row['item'].items() if k in valid_keys}
                    row['item'] = WebCandidate(**filtered)
                crawled_keys = CrawledPage.__dataclass_fields__.keys()
                filtered_page = {k: v for k, v in row.items() if k in crawled_keys}
                pages.append(CrawledPage(**filtered_page))
            except (ValueError, TypeError, zlib.error):
                self.errors += 1
        return pages

    def search_index(self, q, limit=10, search_type='web'):
        """Fast index-based candidate retrieval without full table scan."""
        with self.lock:
            self._prune()
            return self.index.search(q, limit=limit, search_type=search_type)

    def search_images(self, q, limit=20):
        with self.lock:
            self._prune()
            return self.index.search_images(q, limit=limit)

    def _serialize_cache_key(self, cache_key):
        if isinstance(cache_key, str):
            return cache_key
        try:
            return json.dumps(cache_key, ensure_ascii=False)
        except Exception:
            return str(cache_key)

    def get_query_result(self, cache_key):
        key_str = self._serialize_cache_key(cache_key)
        with self.lock:
            now_mono = time.monotonic()
            if key_str in self.query_cache:
                expires, result = self.query_cache[key_str]
                if expires > now_mono:
                    self.query_cache.move_to_end(key_str)
                    return deepcopy(result)
                del self.query_cache[key_str]
            now_wall = time.time()
            try:
                row = self.db.execute('SELECT payload, expires FROM query_cache WHERE cache_key=? AND expires>?',
                                      (key_str, now_wall)).fetchone()
                if row:
                    payload, expires_wall = row
                    raw = zlib.decompress(payload)
                    res = json.loads(raw.decode('utf-8'))
                    ttl_remaining = max(1.0, expires_wall - now_wall)
                    self.query_cache[key_str] = (now_mono + ttl_remaining, res)
                    return deepcopy(res)
            except Exception:
                self.errors += 1
        return None

    def put_query_result(self, cache_key, result, ttl=60.0):
        if ttl <= 0:
            return
        key_str = self._serialize_cache_key(cache_key)
        now_mono = time.monotonic()
        now_wall = time.time()
        with self.lock:
            if key_str in self.query_cache:
                del self.query_cache[key_str]
            self.query_cache[key_str] = (now_mono + ttl, deepcopy(result))
            while len(self.query_cache) > self.max_query_cache_entries:
                self.query_cache.popitem(last=False)
            try:
                raw = json.dumps(result, ensure_ascii=False).encode('utf-8')
                compressed = zlib.compress(raw)
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO query_cache VALUES (?, ?, ?, ?)',
                                    (key_str, compressed, now_wall + ttl, now_wall))
                    count = self.db.execute('SELECT COUNT(*) FROM query_cache').fetchone()[0]
                    if count > 512:
                        self.db.execute('DELETE FROM query_cache WHERE cache_key NOT IN (SELECT cache_key FROM query_cache ORDER BY touched DESC LIMIT 512)')
            except sqlite3.Error:
                self.errors += 1

    def put_alias(self, alias_url, target_url, ttl=None):
        if not alias_url or not target_url or alias_url == target_url:
            return
        effective_ttl = self.settings.cache_ttl if ttl is None else ttl
        if effective_ttl <= 0:
            return
        now = time.time()
        with self.lock:
            try:
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO aliases VALUES (?, ?, ?)',
                                    (alias_url, target_url, now + effective_ttl))
            except sqlite3.Error:
                self.errors += 1

    def get_alias(self, alias_url):
        if not alias_url:
            return None
        now = time.time()
        with self.lock:
            try:
                row = self.db.execute('SELECT target_url FROM aliases WHERE alias_url=? AND expires>?',
                                      (alias_url, now)).fetchone()
                return row[0] if row else None
            except sqlite3.Error:
                return None

    def remember(self, items):
        now = time.time()
        with self.lock:
            with self.db:
                self._prune()
                for item in items[:3]:
                    if not item.evidence or item.injection_risk or item.fetch_status != 'fetched':
                        continue
                    description = (item.title + ' ' + item.evidence[0]['text'])[:1000]
                    self.db.execute('INSERT OR REPLACE INTO memory VALUES(?,?,?,?)',
                                    (item.url, description, now, now + self.settings.source_memory_ttl))
                self.db.execute('DELETE FROM memory WHERE url NOT IN (SELECT url FROM memory ORDER BY seen DESC LIMIT ?)',
                                (self.settings.source_memory_entries,))

    def memory_sources(self, query):
        with self.lock:
            with self.db:
                self._prune()
            sources = [Source(url, description) for url, description in self.db.execute('SELECT url, description FROM memory ORDER BY seen DESC').fetchall()]
        rows = plan_sources(query, sources)
        return [row['url'] for row in rows if row['lexical_similarity'] > 0][:8]

    def clear(self):
        with self.lock:
            with self.db:
                self.db.execute('DELETE FROM pages')
                self.db.execute('DELETE FROM memory')
                self.db.execute('DELETE FROM query_cache')
                self.db.execute('DELETE FROM aliases')
            self.db.execute('PRAGMA incremental_vacuum')
            self.index.clear()
            self.query_cache.clear()

    def stats(self):
        with self.lock:
            with self.db:
                self._prune()
            count, size = self.db.execute('SELECT COUNT(*), COALESCE(SUM(size), 0) FROM pages').fetchone()
            memory = self.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
            istats = self.index.stats()
            return {
                'pages': count,
                'bytes': size,
                'persistent': True,
                'ttl_seconds': self.settings.cache_ttl,
                'source_memory_entries': memory,
                'write_or_read_errors': self.errors,
                'database_bytes': self.path.stat().st_size if self.path.exists() else 0,
                'query_cache_entries': len(self.query_cache),
                **istats
            }

    def close(self):
        with self.lock:
            self.db.close()
