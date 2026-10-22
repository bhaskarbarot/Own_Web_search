"""Fetched-page evidence shared by the independent crawler, cache and ranker."""
import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from .snippet import sentence_excerpt


def web_url(value, allow_private=False):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return None
    try:
        p = urlsplit(value.strip())
        host = (p.hostname or '').lower().rstrip('.')
        if p.scheme.lower() not in ('http', 'https') or not host or p.username or p.password:
            return None
        if not allow_private:
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
        return urlunsplit((p.scheme.lower(), authority, p.path or '/', p.query, ''))
    except (ValueError, UnicodeError):
        return None

@dataclass
class WebCandidate:
    title: str
    url: str
    snippet: str = ''
    provider: str = 'ownsearch_crawler'
    source_type: str = 'fetched_page'
    published_at: str = None
    publication_source: str = None
    publication_conflict: bool = False
    fetched_at: str = None
    content_type: str = None
    detected_kind: str = None
    http_status: int = None
    language: str = None
    content: str = ''
    markdown: str = ''
    code_blocks: list = field(default_factory=list)
    headings: list = field(default_factory=list)
    links: list = field(default_factory=list)
    feeds: list = field(default_factory=list)
    fetch_status: str = 'fetched'
    provenance: list = field(default_factory=list)
    images: list = field(default_factory=list)
    canonical: str = None
    kind: str = 'web'
    features: dict = field(default_factory=dict)
    score: float = 0.0
    evidence: list = field(default_factory=list)
    injection_risk: bool = False
    cached: bool = False
    video: bool = False

    def result(self, rank, explain=False, query_terms=()):
        result = {'rank': rank, 'title': self.title, 'url': self.url, 'display_url': self.url,
                  'host': urlsplit(self.url).hostname,
                  'snippet': sentence_excerpt(self.evidence[0]['text'], query_terms=query_terms) if self.evidence else (sentence_excerpt(self.content, query_terms=query_terms) if self.content else self.snippet),
                  'markdown': self.markdown,
                  'code_blocks': self.code_blocks,
                  'score': round(self.score, 6), 'source_provider': self.provider,
                  'source_type': self.source_type, 'published_at': self.published_at,
                  'fetched_at': self.fetched_at, 'lang': self.language,
                  'content_type': self.content_type, 'filetype': self.detected_kind,
                  'publication_source': self.publication_source,
                  'fetch_status': self.fetch_status, 'cached': self.cached,
                  'provenance': self.provenance, 'images': self.images,
                  'injection_risk': self.injection_risk, 'kind': self.kind}
        if explain:
            result['features'] = self.features
        return result
