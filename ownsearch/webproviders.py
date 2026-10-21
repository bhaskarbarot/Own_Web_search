"""Configured public search APIs and intent-specific sources; no mandatory database."""
import json
import threading
import time
from dataclasses import dataclass, field, replace
from urllib.parse import urlencode, urlsplit

from .fetcher import Fetcher, FetchError, _retry_after
from .provider_health import ProviderHealth, ProviderUnavailable
from .webmodels import WebRequest


@dataclass
class SourceBatch:
    rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    answer: dict = None


class ProviderError(ProviderUnavailable):
    def __init__(self, message, status='error', retry_after=None, http_status=None):
        super().__init__(message, status, retry_after, http_status)


def provider_query(request):
    """Forward separately supplied CLI/API filters as search syntax, too."""
    from .webquery import discovery_text
    text, q = discovery_text(request), request.parsed
    if len(q.sites) == 1 and 'site:' not in text.lower() and 'domain:' not in text.lower():
        text += ' site:'+q.sites[0]
    if len(q.filetypes) == 1 and q.filetypes[0] not in ('web', 'text', 'image') and 'filetype:' not in text.lower():
        text += ' filetype:'+q.filetypes[0]
    return text


class JsonProvider:
    """No automatic retries/charges. Rate limits and failures activate a cooldown."""
    general_web = True

    def __init__(self, settings):
        self.settings = settings
        self.health = ProviderHealth(settings)

    def health_snapshot(self):
        return self.health.snapshot()

    def request(self, request, url, deadline, headers=None, allow_private=False, decoder=None, accept='application/json'):
        if headers and urlsplit(url).scheme != 'https':
            raise ProviderError('Credentialed provider endpoints require HTTPS.')
        try:
            generation = self.health.reserve(request, deadline, getattr(self, 'minimum_interval', 0))
        except ProviderUnavailable as exc:
            raise ProviderError(str(exc), exc.status, exc.retry_after) from None
        try:
            cfg = replace(self.settings, allow_private_hosts=allow_private or self.settings.allow_private_hosts)
            if allow_private and not self.settings.allow_private_hosts:
                endpoint = urlsplit(url)
                trusted = (endpoint.hostname.lower().rstrip('.'), endpoint.port or (443 if endpoint.scheme == 'https' else 80))
                public_fetcher = Fetcher(replace(cfg, allow_private_hosts=False))
                class InstanceFetcher(Fetcher):
                    def resolve(self, host, port):
                        if (host.lower().rstrip('.'), port) == trusted:
                            return super().resolve(host, port)
                        return public_fetcher.resolve(host, port)
                fetcher = InstanceFetcher(cfg)
            else:
                fetcher = Fetcher(cfg)
            fetcher.check_url(url)
            result = fetcher.fetch(url, accept=accept, extra_headers=headers,
                                   max_bytes=2_000_000, max_decompressed_bytes=2_000_000,
                                   retries=0, deadline=deadline, preserve_query=True)
            if result.status != 200:
                if result.status == 404 and getattr(self, 'missing_is_empty', False):
                    self.health.success(404, generation)
                else:
                    self.health.failure(result.status, _retry_after(result.headers.get('retry-after') or result.headers.get('x-retry-after')))
                raise ProviderError('HTTP ' + str(result.status) + ('; enable JSON format on the configured SearXNG instance if disabled.' if result.status == 403 and self.name == 'searxng' else ''),
                                    'rate_limited' if result.status == 429 else 'error', http_status=result.status)
            if result.truncated:
                raise ValueError('Provider response exceeds size limit.')
            payload = decoder(result.body) if decoder else json.loads(result.body.decode('utf-8'))
            if not decoder and not isinstance(payload, dict):
                raise ValueError('Provider returned an invalid JSON schema.')
            self.health.success(generation=generation)
            return payload
        except (FetchError, ValueError, UnicodeError) as exc:
            # Avoid copying URLs, headers or credentials into errors/logs.
            self.health.failure()
            raise ProviderError('Provider request failed: ' + getattr(exc, 'kind', type(exc).__name__)) from None


class SearxWebProvider(JsonProvider):
    name = 'searxng'

    def search(self, request, deadline):
        q = request.parsed
        params = {'q': provider_query(request), 'format': 'json',
                  'categories': 'images' if request.search_type == 'images' else (','.join(dict.fromkeys(['general', 'news']+self.settings.searxng_categories.split(','))) if q.intent == 'news' or (q.fresh_intent and q.explicit_date_filter) else self.settings.searxng_categories),
                  'safesearch': 1}
        if q.lang or q.language_info.get('language') not in (None, 'und'):
            params['language'] = q.lang or q.language_info['language']
        if q.freshness in ('day', 'week', 'month', 'year'):
            params['time_range'] = 'month' if q.freshness == 'week' else q.freshness
        base = self.settings.searxng_url.rstrip('/')
        # The configured URL denotes an instance root, not an arbitrary query URL.
        if urlsplit(base).query or urlsplit(base).fragment:
            raise ProviderError('SearXNG URL must be an instance root without query or fragment.')
        data = self.request(request, base + '/search?' + urlencode(params),
                            min(deadline, time.monotonic() + self.settings.searxng_timeout),
                            allow_private=self.settings.searxng_allow_private)
        results = data.get('results')
        if not isinstance(results, list):
            raise ProviderError('SearXNG response has no results array.')
        results = [dict(row, _ownsearch_source_query=params['q']) for row in results if isinstance(row, dict)]
        # A source can ignore a distinctive API/product identifier in a verbose query.
        # Retry at most once, inside the original deadline, emphasizing missing literal evidence.
        retry_warning = None
        if request.search_type == 'web' and time.monotonic()+.25 < deadline and not request.cancel.is_set():
            from .webquery import literal_identifiers
            from .textproc import analyze
            seen = set(analyze(' '.join(str(row.get('title', ''))+' '+str(row.get('content', ''))+' '+str(row.get('url', '')) for row in results)))
            missing = [identifier for identifier in literal_identifiers(q) if not set(analyze(' '.join(identifier))) <= seen]
            if missing:
                prefix = ' '.join(max(missing, key=lambda group: sum(len(word) for word in group)))
                if not params['q'].lower().startswith(prefix.lower()):
                    params['q'] = prefix+' '+params['q']
                    try:
                        focused = self.request(request, base+'/search?'+urlencode(params), deadline,
                                               allow_private=self.settings.searxng_allow_private)
                        if not isinstance(focused.get('results'), list):
                            raise ProviderError('Focused response has no results array.')
                        results = [dict(row, _ownsearch_source_query=params['q']) for row in focused['results'] if isinstance(row, dict)]+results
                        data['unresponsive_engines'] = data.get('unresponsive_engines', [])+focused.get('unresponsive_engines', [])
                    except ProviderError as exc:
                        retry_warning = 'Focused retry unavailable: '+str(exc)
        rows = []
        for row in results[:self.settings.live_max_candidates]:
            if not isinstance(row, dict):
                continue
            rows.append({'url': row.get('url'), 'title': row.get('title'), 'snippet': row.get('content'),
                         'published_at': row.get('publishedDate'), 'lang': row.get('language'),
                         'image_url': row.get('img_src') if request.search_type == 'images' else None,
                         'thumbnail_url': row.get('thumbnail_src') or row.get('thumbnail'),
                         'kind': 'image' if request.search_type == 'images' else 'web',
                         'source_query': row['_ownsearch_source_query'], 'upstream_engines': row.get('engines') or [row.get('engine')],
                         'upstream_score': row.get('score')})
        warnings = ['Upstream '+str(error[0])[:80]+': '+str(error[1])[:160]
                    for error in data.get('unresponsive_engines', [])
                    if isinstance(error, (list, tuple)) and len(error) >= 2]
        if retry_warning:
            warnings.append(retry_warning)
        return SourceBatch(rows, list(dict.fromkeys(warnings)))


class BraveWebProvider(JsonProvider):
    name = 'brave'

    def search(self, request, deadline):
        q = request.parsed
        image = request.search_type == 'images'
        params = {'q': provider_query(request), 'count': min(20, self.settings.live_max_candidates), 'safesearch': 'strict' if image else 'moderate'}
        if q.freshness in ('day', 'week', 'month', 'year'):
            params['freshness'] = {'day': 'pd', 'week': 'pw', 'month': 'pm', 'year': 'py'}[q.freshness]
        if q.lang:
            params['search_lang'] = q.lang.split('-')[0]
        endpoint = self.settings.brave_images_url if image else self.settings.brave_search_url
        data = self.request(request, endpoint + '?' + urlencode(params),
                            min(deadline, time.monotonic() + self.settings.brave_timeout),
                            {'X-Subscription-Token': self.settings.brave_api_key})
        group = data if image else data.get('web', {})
        if not isinstance(group, dict) or not isinstance(group.get('results'), list):
            raise ProviderError('Brave response has no valid results array.')
        rows = []
        for row in group['results'][:self.settings.live_max_candidates]:
            if not isinstance(row, dict):
                continue
            properties = row.get('properties') if isinstance(row.get('properties'), dict) else {}
            rows.append({'url': row.get('url'), 'title': row.get('title'), 'snippet': row.get('description'),
                         'published_at': row.get('page_age'), 'lang': row.get('language'),
                         'image_url': properties.get('url') if image else None,
                         'thumbnail_url': row.get('thumbnail'), 'kind': 'image' if image else 'web'})
        return SourceBatch(rows)


class FeedWebProvider:
    name = 'news_feeds'
    general_web = False
    def __init__(self, settings):
        self.settings = settings
    def search(self, request, deadline):
        from .discover import NewsFeedProvider
        items, errors = NewsFeedProvider().discover(request.query, request.parsed, self.settings,
                                                   timeout=max(0, deadline-time.monotonic()))
        return SourceBatch([{'url': i.url, 'title': i.title, 'snippet': i.snippet,
                             'published_at': i.published_at, 'source_type': 'news_feed'} for i in items], errors)


class MarketWebProvider:
    name = 'market'
    general_web = False
    def __init__(self, settings):
        self.settings = settings
    def search(self, request, deadline):
        from .market import Market
        market = Market(self.settings, deadline=deadline, persistent=False)
        q = request.parsed
        answer = (market.history(q.entity, q.intent_details.get('days') or 183)
                  if q.intent_details.get('wants_history') else market.quote(q.entity))
        rows = []
        if answer:
            rows = [{'url': answer['source']['url'], 'title': answer.get('name') or 'Market data',
                     'snippet': answer['text'], 'source_type': 'market_data'}]
        return SourceBatch(rows, market.errors, answer)


def configured(settings):
    sources = []
    if settings.searxng_url.strip():
        sources.append(SearxWebProvider(settings))
    if settings.brave_api_key.strip():
        sources.append(BraveWebProvider(settings))
    return sources
