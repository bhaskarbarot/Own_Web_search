"""Independent runtime settings. Configuration is JSON; documents live only in memory."""
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_DATA_DIR = 'data'

def _default_sources_file() -> str:
    repo_file = Path(__file__).resolve().parent.parent / 'sources.txt'
    if repo_file.is_file():
        return str(repo_file)
    pkg_file = Path(__file__).resolve().parent / 'resources' / 'sources.txt'
    return str(pkg_file)

@dataclass
class Settings:
    data_dir: Path = Path(DEFAULT_DATA_DIR)
    user_agent: str = 'OwnSearchBot/2.0 (+https://github.com/bhaskarbarot/Own_Web_search; independent bounded crawler)'
    robots_token: str = 'ownsearchbot'
    max_page_bytes: int = 2_000_000
    max_decompressed_bytes: int = 6_000_000
    max_text_chars: int = 60_000
    fetch_timeout: float = 5.0
    fetch_retries: int = 0
    max_redirects: int = 5
    allow_private_hosts: bool = False
    default_delay: float = 0.25
    robots_ttl: float = 3600.0
    origin_cache_entries: int = 256
    crawl_threads: int = 4
    max_depth: int = 3
    max_links_per_page: int = 300
    max_frontier_urls: int = 2000
    max_sitemap_urls: int = 500
    max_sitemap_depth: int = 2
    max_pages_per_query: int = 20
    max_requests_per_query: int = 32
    max_bytes_per_query: int = 8_000_000
    max_concurrent_searches: int = 4
    search_timeout_ms: int = 12000
    max_search_timeout_ms: int = 20000
    source_planning_enabled: bool = False  # experiment; activate only after ablation
    focused_links_enabled: bool = False
    native_search_enabled: bool = False
    persistent_cache_enabled: bool = False
    source_memory_enabled: bool = False
    cdx_discovery_enabled: bool = True
    cache_ttl_docs: float = 3600.0
    cache_ttl_feed: float = 60.0
    cache_ttl_news: float = 30.0
    source_memory_ttl: float = 604800.0
    source_memory_entries: int = 256
    cache_ttl: float = 900.0
    cache_entries: int = 128
    cache_max_bytes: int = 16_000_000
    seeds: str = ''
    sources_file: str = _default_sources_file()
    timezone: str = 'UTC'
    holiday_country: str = ''
    default_language: str = 'en'
    ocr: str = 'off'
    tesseract_cmd: str = 'tesseract'
    ocr_lang: str = 'eng'
    ocr_timeout: float = 2.0
    ocr_max_pages: int = 1
    document_timeout: float = 2.0

    @classmethod
    def load(cls, data_dir=None, **overrides):
        root = Path(data_dir or os.environ.get('OWNSEARCH_DATA_DIR', DEFAULT_DATA_DIR)).resolve()
        # Old provider settings are intentionally ignored; never launch or contact them.
        values = {}
        try:
            raw = json.loads((root / 'ownsearch.json').read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                values.update(raw)
        except (OSError, ValueError):
            pass
        for f in fields(cls):
            if f.name != 'data_dir' and 'OWNSEARCH_' + f.name.upper() in os.environ:
                values[f.name] = os.environ['OWNSEARCH_' + f.name.upper()]
        values.update({k: v for k, v in overrides.items() if v is not None})
        result = cls(data_dir=root)
        for f in fields(cls):
            if f.name != 'data_dir' and f.name in values:
                value = values[f.name]
                kind = type(getattr(result, f.name))
                if kind is bool:
                    value = value.strip().lower() in ('true', 'yes', '1', 'on') if isinstance(value, str) else bool(value)
                else:
                    value = kind(value)
                setattr(result, f.name, value)
        for name in ('crawl_threads', 'max_pages_per_query', 'max_requests_per_query',
                     'max_bytes_per_query', 'max_concurrent_searches', 'max_page_bytes',
                     'cache_entries', 'cache_max_bytes', 'origin_cache_entries', 'max_frontier_urls'):
            if getattr(result, name) <= 0:
                raise ValueError(name + ' must be positive')
        if result.default_delay < 0 or result.fetch_timeout <= 0 or result.cache_ttl < 0:
            raise ValueError('Invalid delay, timeout or cache TTL')
        return result

    @property
    def keys_path(self):
        return self.data_dir / 'api_keys.json'

    def starting_urls(self):
        import re
        urls = re.split(r'[\s,]+', self.seeds.strip()) if self.seeds.strip() else []
        if self.sources_file:
            path = Path(self.sources_file).expanduser()
            if not path.is_absolute():
                repo_file = Path(__file__).resolve().parent.parent / path
                path = repo_file if repo_file.is_file() else (self.data_dir / path)
            if path.is_file():
                for line in path.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        urls.append(line.split()[0])
        return list(dict.fromkeys(urls))[:self.max_frontier_urls]
