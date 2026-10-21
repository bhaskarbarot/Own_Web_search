"""Optional bounded SQLite TTL cache of already-fetched pages and source memory.

This stores no web-wide index and requires no service or account. URL memory
contains only actually fetched URLs, never generated article addresses.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import zlib
from .sourceplan import Source, plan_sources
from .webfetch import CrawledPage
from .webmodels import WebCandidate

class PersistentPageCache:
    def __init__(self, settings):
        self.settings=settings
        self.path=Path(settings.data_dir)/'query_cache.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.errors=0
        self.db=sqlite3.connect(str(self.path),timeout=.1,check_same_thread=False)
        self.db.execute('PRAGMA auto_vacuum=INCREMENTAL')
        self.db.execute('PRAGMA journal_mode=DELETE')
        page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
        pages=max(128,(settings.cache_max_bytes+2*1024*1024)//page_size)
        self.db.execute('PRAGMA max_page_count='+str(pages))
        self.db.execute('CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY,payload BLOB NOT NULL,size INTEGER NOT NULL,expires REAL NOT NULL,touched REAL NOT NULL,sha256 TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS memory(url TEXT PRIMARY KEY,description TEXT NOT NULL,seen REAL NOT NULL,expires REAL NOT NULL)')
        self.db.commit()

    def _prune(self):
        now=time.time()
        self.db.execute('DELETE FROM pages WHERE expires<=?',(now,))
        self.db.execute('DELETE FROM memory WHERE expires<=?',(now,))

    def put(self,url,page,ttl=None):
        raw=json.dumps(asdict(page),ensure_ascii=False,separators=(',',':')).encode()
        size=len(raw)
        if size>self.settings.cache_max_bytes:return False
        if ttl is None:
            ttl={'feed':self.settings.cache_ttl_feed,'sitemap':self.settings.cache_ttl_docs,
                 'pdf':self.settings.cache_ttl_docs,'office':self.settings.cache_ttl_docs}.get(page.kind,self.settings.cache_ttl)
        if ttl<=0:return False
        now=time.time()
        with self.lock:
            try:
                with self.db:
                    self._prune()
                    self.db.execute('DELETE FROM pages WHERE url=?',(url,))
                    while True:
                        count,total=self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM pages').fetchone()
                        if count<self.settings.cache_entries and total+size<=self.settings.cache_max_bytes:break
                        self.db.execute('DELETE FROM pages WHERE url=(SELECT url FROM pages ORDER BY touched LIMIT 1)')
                    self.db.execute('INSERT INTO pages VALUES(?,?,?,?,?,?)',(url,zlib.compress(raw),size,now+ttl,now,hashlib.sha256(raw).hexdigest()))
                self.db.execute('PRAGMA incremental_vacuum(16)')
                return True
            except sqlite3.Error:
                self.errors+=1
                return False

    def snapshot(self,max_age=None):
        pages=[]
        with self.lock:
            with self.db:self._prune()
            rows=self.db.execute('SELECT payload,sha256,touched FROM pages ORDER BY touched').fetchall()
        for payload,fingerprint,touched in rows:
            if max_age is not None and time.time()-touched>max_age:continue
            try:
                decoder=zlib.decompressobj()
                raw=decoder.decompress(payload,self.settings.cache_max_bytes+1)
                if len(raw)>self.settings.cache_max_bytes or not decoder.eof or decoder.unconsumed_tail:raise ValueError('Cache payload exceeds bounds')
                if hashlib.sha256(raw).hexdigest()!=fingerprint:raise ValueError('Cache payload changed')
                row=json.loads(raw)
                if row.get('item'):row['item']=WebCandidate(**row['item'])
                pages.append(CrawledPage(**row))
            except (ValueError,TypeError,zlib.error):
                self.errors+=1
        return pages

    def remember(self,items):
        now=time.time()
        with self.lock:
            with self.db:
                self._prune()
                for item in items[:3]:
                    if not item.evidence or item.injection_risk or item.fetch_status!='fetched':continue
                    description=(item.title+' '+item.evidence[0]['text'])[:1000]
                    self.db.execute('INSERT OR REPLACE INTO memory VALUES(?,?,?,?)',
                                    (item.url,description,now,now+self.settings.source_memory_ttl))
                self.db.execute('DELETE FROM memory WHERE url NOT IN (SELECT url FROM memory ORDER BY seen DESC LIMIT ?)',
                                (self.settings.source_memory_entries,))

    def memory_sources(self,query):
        with self.lock:
            with self.db:self._prune()
            sources=[Source(url,description) for url,description in self.db.execute('SELECT url,description FROM memory ORDER BY seen DESC').fetchall()]
        # Similarity is only a revisit hint; previous lexical usefulness is not
        # a human relevance grade, proof of authority or fresh fetched evidence.
        rows=plan_sources(query,sources)
        return [row['url'] for row in rows if row['lexical_similarity']>0][:8]

    def clear(self):
        with self.lock:
            with self.db:
                self.db.execute('DELETE FROM pages');self.db.execute('DELETE FROM memory')
            self.db.execute('PRAGMA incremental_vacuum')

    def stats(self):
        with self.lock:
            with self.db:self._prune()
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM pages').fetchone()
            memory=self.db.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
            return {'pages':count,'bytes':size,'persistent':True,'ttl_seconds':self.settings.cache_ttl,
                    'source_memory_entries':memory,'write_or_read_errors':self.errors,'database_bytes':self.path.stat().st_size}

    def close(self):
        with self.lock:self.db.close()
