"""Request-scoped web evidence. No persistence or corpus dependencies."""
import ipaddress
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from .dates import parse_date
from .util import utc_now


def web_url(value):
    """Validate public link syntax without resolving/fetching it. Fetcher checks DNS."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return None
    try:
        p = urlsplit(value.strip())
        host = (p.hostname or '').lower().rstrip('.')
        if p.scheme.lower() not in ('http', 'https') or not host or p.username or p.password:
            return None
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home.arpa')):
            return None
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global or address.is_multicast:
                return None
        except ValueError:
            if '.' not in host:
                return None
        port = p.port
        authority = '[' + host + ']' if ':' in host else host.encode('idna').decode('ascii')
        if port and (p.scheme.lower(), port) not in (('http', 80), ('https', 443)):
            authority += ':' + str(port)
        # Query string ordering, duplicate keys and values may be meaningful.
        return urlunsplit((p.scheme.lower(), authority, p.path or '/', p.query, ''))
    except (ValueError, UnicodeError):
        return None


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain(value, limit=1200):
    if not isinstance(value, str):
        return ''
    parser = _Plain()
    parser.feed(value[:limit * 4])
    text = unescape(' '.join(parser.parts))
    return ' '.join(''.join(c for c in text if c.isprintable() or c.isspace()).split())[:limit]


@dataclass
class WebRequest:
    query: str
    parsed: object
    cancel: object
    search_type: str = 'web'


@dataclass
class WebCandidate:
    title: str
    url: str
    snippet: str = ''
    provider: str = ''
    source_type: str = 'provider_snippet'
    published_at: str = None
    publication_source: str = None
    publication_conflict: bool = False
    fetched_at: str = None
    content_type: str = None
    detected_kind: str = None
    http_status: int = None
    language: str = None
    content: str = ''
    headings: list = field(default_factory=list)
    links: list = field(default_factory=list)
    fetch_status: str = 'not_fetched'
    provenance: list = field(default_factory=list)
    images: list = field(default_factory=list)
    canonical: str = None
    original_url: str = None
    kind: str = 'web'
    features: dict = field(default_factory=dict)
    score: float = 0.0
    evidence: list = field(default_factory=list)
    injection_risk: bool = False

    @classmethod
    def from_row(cls, row, provider, rank):
        if not isinstance(row, dict) or not (url := web_url(row.get('url'))):
            return None
        title = plain(row.get('title'), 300)
        snippet = plain(row.get('snippet', row.get('content', '')))
        if not title and not snippet:
            return None
        source_type = row.get('source_type') if provider in ('market', 'news_feeds', 'local_index') else 'provider_snippet'
        item = cls(title or urlsplit(url).hostname, url, snippet, provider,
                   source_type if isinstance(source_type, str) else 'provider_snippet')
        item.original_url = url
        item.published_at = parse_date(row.get('published_at', row.get('publishedDate')))
        item.publication_source = provider if item.published_at else None
        item.language = row.get('lang') if isinstance(row.get('lang'), str) else None
        item.provenance = [{'provider': provider, 'rank': rank, 'url': url,
                            'evidence_level': item.source_type, 'retrieved_at': utc_now(),
                            'snippet': snippet, 'published_at': item.published_at}]
        if isinstance(row.get('source_query'), str):
            item.provenance[0]['query'] = row['source_query'][:1000]
        if isinstance(row.get('upstream_engines'), list):
            item.provenance[0]['upstream_engines'] = [v[:80] for v in row['upstream_engines'] if isinstance(v, str)][:20]
        image = row.get('image_url')
        thumb = row.get('thumbnail_url')
        if isinstance(thumb, dict):
            thumb = thumb.get('src')
        image = web_url(image)
        thumb = web_url(thumb)
        if image or thumb:
            item.images = [{'image_url': image, 'thumbnail_url': thumb, 'page_url': url,
                            'caption': title, 'provider': provider, 'attribution': 'provider metadata',
                            'relevance_verified': False}]
        item.kind = 'image' if row.get('kind') == 'image' else 'web'
        from .evidence import injection_flags
        item.injection_risk = bool(injection_flags(title+' '+snippet))
        return item

    def result(self, rank, explain=False):
        host = urlsplit(self.url).hostname
        result = {'rank': rank, 'id': None, 'title': self.title, 'url': self.url,
                  'display_url': self.url, 'host': host,
                  'snippet': self.evidence[0]['text'][:600] if self.evidence else self.snippet,
                  'score': round(self.score, 6), 'provider': self.provider,
                  'source_provider': self.provider,
                  'providers': sorted({p['provider'] for p in self.provenance}),
                  'source_type': self.source_type, 'published_at': self.published_at,
                  'fetched_at': self.fetched_at, 'lang': self.language,
                  'content_type': self.content_type,
                  'date_source': 'published' if self.published_at else None,
                  'publication_source': self.publication_source,
                  'publication_conflict': self.publication_conflict,
                  'fetch_status': self.fetch_status, 'crawl_status': self.fetch_status,
                  'provenance': self.provenance, 'images': self.images,
                  'injection_risk': self.injection_risk, 'kind': self.kind}
        if explain:
            result['features'] = self.features
        return result
