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

    # Bot identity uses the public repository as contact; never a personal email.
    user_agent: str = "OwnSearchBot/1.0 (+https://github.com/bhaskarbarot/Own_Web_search; self-hosted search engine)"
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
    max_frontier_urls: int = 50000
    max_enqueue_batch: int = 1000
    max_sitemap_urls: int = 500
    max_sitemap_depth: int = 3
    max_crawl_bytes: int = 256 * 1024 * 1024
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
    max_index_chars: int = 500000 # bound analysis CPU independently of stored content
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
    vector_index: bool = False
    embedding_model_path: str = ""
    reranker_enabled: bool = False
    reranker_model_path: str = ""
    rerank_budget_ms: int = 40
    translation_enabled: bool = False
    translation_target: str = "en"
    ner_model_path: str = ""
    intent_embedding_enabled: bool = False
    intent_budget_ms: int = 25
    language_detector: str = "script"
    document_languages: str = "en,hi,gu"
    holiday_country: str = "" # explicit country; never inferred from browser language
    timezone: str = "UTC"
    default_language: str = "en"

    # Live Discovery and External Providers
    search_mode: str = "live"          # CLI/API default; explicit local mode keeps the existing index
    live_local_enabled: bool = False   # optional corpus accelerator; never mandatory for live search
    live_fetch_pages: int = 3
    live_fetch_concurrency: int = 3
    live_fetch_timeout: float = 4.0
    live_max_page_bytes: int = 2_000_000
    live_max_total_bytes: int = 6_000_000
    live_max_text_chars: int = 60_000
    live_max_requests: int = 16        # includes robots and redirects
    live_max_candidates: int = 40
    live_workers: int = 8
    live_early_results: int = 3
    live_provider_grace_ms: int = 150
    live_cache_ttl: float = 0.0        # opt-in, memory-only; never persists pages
    live_cache_entries: int = 32
    provider_cooldown: float = 30.0
    provider_min_interval: float = 1.0
    provider_request_budget: int = 60
    provider_budget_window: float = 60.0
    provider_failure_threshold: int = 3
    searxng_allow_private: bool = False # only the explicitly configured instance, not result-page fetching
    brave_search_url: str = "https://api.search.brave.com/res/v1/web/search"
    brave_images_url: str = "https://api.search.brave.com/res/v1/images/search"
    provider_wait_ms: int = 500 # only when no useful local results; background workers have separate deadlines
    searxng_url: str = ""               # self-hosted SearXNG endpoint, e.g. "http://localhost:8080"
    searxng_timeout: float = 3.0
    searxng_categories: str = "general"
    brave_api_key: str = ""             # optional Brave Search API key
    brave_timeout: float = 3.0
    news_feeds: str = ""                # comma/newline-separated list of RSS/Atom feed URLs
    discovery_mode: str = "background" # API never waits for page crawling; CLI opts into inline
    discovery_timeout: float = 8.0      # request budget shared with linking and local ranking
    discovery_provider_timeout: float = 3.0
    knowledge_timeout: float = 2.5
    discovery_min_results: int = 1     # one strong match is enough; do not fill a list with weak pages
    discovery_max_urls: int = 6
    discovery_max_requests: int = 24    # includes robots, sitemaps and focused links
    discovery_sitemap_limit: int = 500
    discovery_cache_ttl: float = 900.0
    relevance_score_ratio: float = 0.30
    knowledge_enabled: bool = True
    remote_knowledge_enabled: bool = False  # explicit opt-in for Wikimedia network queries
    package_lookup_url: str = "https://pypi.org/pypi/{name}/json" # maintainer-published docs URLs; empty disables
    financial_provider_url: str = ""    # optional live financial quote endpoint
    financial_timeout: float = 3.0
    # Market data source (free, public). Templates: {q} search text, {symbol}, {period1}/{period2} unix seconds,
    # {interval}. Set market_chart_url = "" to disable live market answers.
    market_lookup_url: str = "https://query2.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=6&newsCount=0"
    market_chart_url: str = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}"
                             "&period2={period2}&interval={interval}&includePrePost=false")
    market_quote_page: str = "https://finance.yahoo.com/quote/{symbol}"
    market_source_name: str = "Yahoo Finance public chart feed"
    # News feeds: file with one RSS/Atom URL per line (default: the bundled resources/news_feeds.txt)
    news_feeds_file: str = str(Path(__file__).with_name("resources") / "news_feeds.tsv")

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
