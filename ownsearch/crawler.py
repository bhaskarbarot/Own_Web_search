"""Batch and continuous background crawler for OwnSearch.

Discovers, parses, and indexes sitemaps, RSS feeds, and follow-links into the persistent
cache and in-memory BM25F index. Enables offline and background web ingestion so live
searches execute in milliseconds.
"""
from collections import deque
from dataclasses import dataclass, field
import logging
import queue
import re
import threading
import time
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from .config import Settings
from .persistent_cache import PersistentPageCache
from .sourceplan import load_registry
from .util import origin_of
from .webfetch import WebFetchSession, OriginState

logger = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    pages_attempted: int = 0
    pages_indexed: int = 0
    pages_skipped: int = 0
    errors: int = 0
    bytes_downloaded: int = 0
    start_time: float = field(default_factory=time.monotonic)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def summary(self) -> str:
        elapsed = max(0.1, self.elapsed_seconds())
        rate = self.pages_indexed / elapsed
        return (
            f"Crawled: {self.pages_indexed} indexed, {self.pages_skipped} skipped, "
            f"{self.errors} errors in {elapsed:.1f}s ({rate:.1f} pages/sec)"
        )


def parse_sitemap_urls(xml_data: bytes, base_url: str, max_urls: int = 500) -> List[str]:
    """Parse XML sitemap and extract page/sub-sitemap URLs safely."""
    urls = []
    # Strip DOCTYPE/ENTITY declarations for safety
    if re.search(rb'<!\s*(DOCTYPE|ENTITY)\b', xml_data, re.I):
        return []
    try:
        root = ET.fromstring(xml_data)
        # Sitemaps use xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        for elem in root.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == 'loc' and elem.text:
                loc = elem.text.strip()
                if loc.startswith(('http://', 'https://')):
                    urls.append(loc)
                else:
                    urls.append(urljoin(base_url, loc))
                if len(urls) >= max_urls:
                    break
    except ET.ParseError:
        pass
    return urls


class BackgroundCrawler:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        cache: Optional[PersistentPageCache] = None,
        max_workers: int = 4,
    ):
        self.settings = settings or Settings()
        self.cache = cache or PersistentPageCache(self.settings)
        self.max_workers = max_workers
        self.origins = OriginState(limit=500)
        self.stats = CrawlStats()
        self.visited: Set[str] = set()
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def crawl_site(
        self,
        seed_url: str,
        max_pages: int = 100,
        max_depth: int = 1,
        sitemap_url: Optional[str] = None,
        on_progress: Optional[Callable[[str, CrawlStats], None]] = None,
    ) -> CrawlStats:
        """Crawl a specific site or documentation root up to max_depth/max_pages."""
        return self.crawl_seeds(
            seeds=[seed_url],
            max_pages=max_pages,
            max_depth=max_depth,
            sitemaps=[sitemap_url] if sitemap_url else [],
            site_restriction=origin_of(seed_url),
            on_progress=on_progress,
        )

    def crawl_seeds(
        self,
        seeds: List[str],
        max_pages: int = 500,
        max_depth: int = 1,
        sitemaps: Optional[List[str]] = None,
        site_restriction: Optional[str] = None,
        on_progress: Optional[Callable[[str, CrawlStats], None]] = None,
    ) -> CrawlStats:
        """Crawl a list of seeds and sitemaps concurrently with polite per-host rate limits."""
        work_queue: queue.Queue = queue.Queue()
        active_origins: Set[str] = set()

        for s in sitemaps or []:
            work_queue.put((s, 0, True))  # (url, depth, is_sitemap)

        for seed in seeds:
            work_queue.put((seed, 0, False))

        fetcher = WebFetchSession(self.settings, self.stopped, self.origins)

        def worker():
            while not self.stopped.is_set():
                if self.stats.pages_indexed >= max_pages:
                    break
                try:
                    url, depth, is_sitemap = work_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                with self.lock:
                    if url in self.visited:
                        work_queue.task_done()
                        continue
                    self.visited.add(url)
                    origin = origin_of(url)
                    if origin in active_origins:
                        # Re-queue to avoid hammering the same host simultaneously
                        work_queue.put((url, depth, is_sitemap))
                        work_queue.task_done()
                        time.sleep(0.05)
                        continue
                    active_origins.add(origin)

                try:
                    deadline = time.monotonic() + 15.0
                    if is_sitemap:
                        try:
                            resp = fetcher.page(url, deadline=deadline)
                            if resp and resp.status == 200:
                                discovered = parse_sitemap_urls(resp.body, url, max_urls=200)
                                for disc_url in discovered:
                                    if disc_url.endswith('.xml') or 'sitemap' in disc_url:
                                        work_queue.put((disc_url, depth, True))
                                    else:
                                        work_queue.put((disc_url, depth + 1, False))
                                if on_progress:
                                    on_progress(f"Discovered {len(discovered)} URLs from sitemap {url}", self.stats)
                        except Exception as e:
                            logger.debug("Sitemap fetch failed for %s: %s", url, e)
                    else:
                        page = fetcher.crawl(url, deadline=deadline)
                        if page and page.item:
                            self.cache.put(page.url, page)
                            with self.lock:
                                self.stats.pages_indexed += 1
                            if on_progress:
                                on_progress(f"Indexed: {page.url} ({page.item.title[:40]})", self.stats)

                        # Follow outgoing links if depth allows
                        if page and depth < max_depth:
                            for link_url, _, link_type in getattr(page, 'links', []):
                                if site_restriction and origin_of(link_url) != site_restriction:
                                    continue
                                with self.lock:
                                    if link_url not in self.visited and work_queue.qsize() < max_pages * 2:
                                        work_queue.put((link_url, depth + 1, False))
                except Exception as exc:
                    with self.lock:
                        self.stats.errors += 1
                finally:
                    with self.lock:
                        active_origins.discard(origin)
                    work_queue.task_done()

        threads = []
        for _ in range(min(self.max_workers, 8)):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            threads.append(t)

        while any(t.is_alive() for t in threads):
            if self.stats.pages_indexed >= max_pages or (work_queue.empty() and not active_origins):
                self.stopped.set()
                break
            time.sleep(0.2)

        for t in threads:
            t.join(timeout=1.0)

        return self.stats
