"""TTL cache and source-memory correctness; no public network or bulk crawling."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from ownsearch.persistent_cache import PersistentPageCache
from ownsearch.webfetch import CrawledPage
from ownsearch.webmodels import WebCandidate
from tests.test_independent import settings

class PersistentCacheTests(unittest.TestCase):
    def cache(self,tmp,**kw):return PersistentPageCache(settings(data_dir=Path(tmp),**kw))
    def page(self,url='https://fixture.example/article'):
        item=WebCandidate('Orbital guidance',url,content='Orbital guidance explains trajectory measurements.')
        item.evidence=[{'text':item.content,'score':2,'matched_terms':2}]
        return CrawledPage(url,item=item,kind='html')
    def test_survives_restart_without_refreshing_original_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);page=self.page();page.item.fetched_at='2026-01-01T00:00:00Z'
            cache.put(page.url,page);cache.close()
            cache=self.cache(tmp)
            self.assertEqual(cache.snapshot()[0].item.fetched_at,page.item.fetched_at)
            cache.close()
    def test_expired_evidence_is_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);page=self.page();cache.put(page.url,page,ttl=.01)
            time.sleep(.02);self.assertEqual(cache.snapshot(),[]);cache.close()
    def test_fresh_query_age_is_stricter_than_document_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);page=self.page();cache.put(page.url,page,ttl=100)
            time.sleep(.01)
            self.assertEqual(cache.snapshot(max_age=0),[])
            self.assertEqual(len(cache.snapshot()),1);cache.close()
    def test_size_and_entry_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp,cache_entries=1,cache_max_bytes=5000)
            for suffix in ('a','b'):
                page=self.page('https://fixture.example/'+suffix);cache.put(page.url,page)
            self.assertEqual(len(cache.snapshot()),1)
            self.assertLessEqual(cache.stats()['bytes'],5000);cache.close()
    def test_zero_ttl_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);page=self.page();self.assertFalse(cache.put(page.url,page,ttl=0))
            self.assertEqual(cache.snapshot(),[]);cache.close()
    def test_source_memory_has_only_observed_useful_urls_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp,source_memory_ttl=.01)
            cache.remember([self.page().item])
            self.assertEqual(cache.memory_sources('orbital guidance'),[self.page().url])
            self.assertEqual(cache.memory_sources('unseenidentifier'),[])
            time.sleep(.02);self.assertEqual(cache.memory_sources('orbital guidance'),[]);cache.close()
    def test_risky_or_unfetched_content_not_remembered(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);item=self.page().item;item.injection_risk=True
            cache.remember([item]);self.assertEqual(cache.memory_sources('orbital guidance'),[]);cache.close()
    def test_modified_cache_payload_is_not_fetched_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp);page=self.page();cache.put(page.url,page)
            with cache.db:cache.db.execute('UPDATE pages SET payload=?',(b'bad',))
            self.assertEqual(cache.snapshot(),[]);self.assertGreater(cache.stats()['write_or_read_errors'],0);cache.close()
    def test_source_memory_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=self.cache(tmp,source_memory_entries=1)
            for suffix in ('a','b'):cache.remember([self.page('https://fixture.example/'+suffix).item])
            self.assertEqual(cache.stats()['source_memory_entries'],1);cache.close()
