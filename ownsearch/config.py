"""Runtime settings.

Values come from (lowest to highest priority): defaults below, ``<data_dir>/ownsearch.json``,
``OWNSEARCH_<NAME>`` environment variables, and explicit keyword overrides.
"""
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_DATA_DIR = "data"


def _coerce(value, kind):
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind in (int, float, str):
        return kind(value)
    return value


@dataclass
class Settings:
    data_dir: Path = Path(DEFAULT_DATA_DIR)

    # Identity used when crawling. Put a real contact address in ownsearch.json.
    user_agent: str = "OwnSearchBot/1.0 (+self-hosted search engine; contact: owner)"
    robots_token: str = "ownsearchbot"

    # Fetching
    max_page_bytes: int = 8 * 1024 * 1024
    max_decompressed_bytes: int = 32 * 1024 * 1024
    max_text_chars: int = 2_000_000
    fetch_timeout: float = 20.0
    fetch_retries: int = 2
    max_redirects: int = 5
    allow_private_hosts: bool = False   # only for tests / intranet crawling you control

    # Crawling and politeness
    default_delay: float = 2.0
    max_crawl_delay: float = 60.0
    crawl_threads: int = 8
    max_pages_per_host: int = 20000
    max_depth: int = 10
    max_attempts: int = 5
    max_links_per_page: int = 400
    min_recrawl: float = 3600.0
    default_recrawl: float = 3 * 86400.0
    max_recrawl: float = 45 * 86400.0
    robots_ttl: float = 86400.0

    # Content processing
    ocr: str = "auto"                   # auto | tesseract | off
    tesseract_cmd: str = "tesseract"
    ocr_lang: str = "eng"
    ocr_timeout: float = 120.0
    ocr_max_pages: int = 30
    max_index_tokens: int = 60000       # body tokens indexed per document

    # Index
    index_flush_docs: int = 2000
    merge_factor: int = 8
    postings_cache_mb: int = 256

    # Serving
    cache_ttl: float = 120.0
    cache_entries: int = 4096
    max_concurrent_searches: int = 0    # 0 = 2 x CPU count
    search_timeout_ms: int = 8000
    log_queries: bool = True

    # Live Discovery and External Providers
    searxng_url: str = ""               # self-hosted SearXNG endpoint, e.g. "http://localhost:8080"
    searxng_timeout: float = 3.0
    searxng_categories: str = "general,news"
    brave_api_key: str = ""             # optional Brave Search API key
    brave_timeout: float = 3.0
    news_feeds: str = ""                # comma/newline-separated list of RSS/Atom feed URLs
    discovery_timeout: float = 5.0      # max seconds spent on live discovery
    discovery_max_urls: int = 6
    financial_provider_url: str = ""    # optional live financial quote endpoint
    financial_timeout: float = 3.0

    @classmethod
    def load(cls, data_dir=None, **overrides):
        root = Path(data_dir or os.environ.get("OWNSEARCH_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
        values = {}
        cfg = root / "ownsearch.json"
        if cfg.exists():
            try:
                values.update(json.loads(cfg.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        for f in fields(cls):
            env = os.environ.get("OWNSEARCH_" + f.name.upper())
            if env is not None and f.name != "data_dir":
                values[f.name] = env
        values.update({k: v for k, v in overrides.items() if v is not None})
        settings = cls(data_dir=root)
        for f in fields(cls):
            if f.name != "data_dir" and f.name in values:
                setattr(settings, f.name, _coerce(values[f.name], type(getattr(settings, f.name))))
        return settings

    @property
    def db_path(self): return self.data_dir / "ownsearch.db"

    @property
    def frontier_path(self): return self.data_dir / "frontier.db"

    @property
    def index_dir(self): return self.data_dir / "segments"

    @property
    def keys_path(self): return self.data_dir / "api_keys.json"

    @property
    def ranker_path(self): return self.data_dir / "ranker.json"

    def ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
