"""Independent official-API adapters; URLs and descriptions come from responses."""
import re
from urllib.parse import urlencode

from .webmodels import plain, web_url
from .webproviders import JsonProvider, ProviderError, SourceBatch


def api_query(request):
    q = request.parsed
    return ' '.join(dict.fromkeys(q.entity + q.context))[:500] or request.query[:500]


class ApiProvider(JsonProvider):
    general_web = False
    minimum_interval = 1.0

    def accepts(self, request):
        return request.search_type == 'web'

    def get(self, request, endpoint, parameters, deadline):
        if not endpoint.startswith('https://'):
            raise ProviderError('Official API endpoints require HTTPS.')
        data = self.request(request, endpoint + ('&' if '?' in endpoint else '?') + urlencode(parameters), deadline)
        if isinstance(data.get('error'), dict):
            self.health.failure(503)
            raise ProviderError('Official API reported an error.')
        return data

    def row(self, request, url, title, snippet='', published=None, language=None):
        url = web_url(url)
        if not url or not isinstance(title, str) or not title.strip():
            return None
        return {'url': url, 'title': plain(title, 300), 'snippet': plain(snippet, 1200),
                'published_at': published, 'lang': language, 'source_query': api_query(request)}


class WikipediaApiProvider(ApiProvider):
    name = 'wikipedia'

    def accepts(self, request):
        return super().accepts(request) and request.parsed.intent not in ('news', 'financial', 'tech_docs')

    def search(self, request, deadline):
        language = (request.parsed.lang or request.parsed.language_info.get('language') or 'en').split('-')[0]
        if not re.fullmatch('[a-z]{2,3}', language):
            language = 'en'
        data = self.get(request, self.settings.wikipedia_api_url.format(language=language),
                        {'action': 'query', 'format': 'json', 'formatversion': 2, 'generator': 'search',
                         'gsrsearch': api_query(request), 'gsrlimit': 10, 'prop': 'info|extracts',
                         'inprop': 'url', 'explaintext': 1, 'exintro': 1, 'exsentences': 3, 'maxlag': 5}, deadline)
        pages = data.get('query', {}).get('pages', []) if isinstance(data.get('query', {}), dict) else None
        if not isinstance(pages, list):
            raise ProviderError('Wikipedia API returned an invalid pages array.')
        rows=[]
        for item in sorted((p for p in pages if isinstance(p, dict)), key=lambda p:p.get('index', 1000))[:10]:
            row = self.row(request, item.get('fullurl'), item.get('title'), item.get('extract', ''), language=language)
            if row: rows.append(row)
        return SourceBatch(rows)


class WikidataApiProvider(ApiProvider):
    name = 'wikidata'

    def accepts(self, request):
        return super().accepts(request) and request.parsed.intent == 'reference'

    def search(self, request, deadline):
        lang = (request.parsed.language_info.get('language') or 'en').split('-')[0]
        if not re.fullmatch('[a-z]{2,3}', lang): lang='en'
        data = self.get(request, self.settings.wikidata_api_url,
                        {'action':'wbsearchentities','format':'json','language':lang,
                         'search':api_query(request),'limit':10,'maxlag':5},deadline)
        items=data.get('search')
        if not isinstance(items,list): raise ProviderError('Wikidata API returned an invalid search array.')
        rows=[]
        for item in items[:10]:
            if not isinstance(item,dict): continue
            row=self.row(request,item.get('concepturi'),item.get('label'),item.get('description',''),language=lang)
            if row: rows.append(row)
        return SourceBatch(rows)


ADAPTERS={'wikipedia':WikipediaApiProvider,'wikidata':WikidataApiProvider}


def configured_verticals(settings):
    names=list(dict.fromkeys(n.strip() for n in settings.vertical_providers.split(',') if n.strip()))
    unknown=set(names)-set(ADAPTERS)
    if unknown: raise ValueError('Unknown vertical providers: '+', '.join(sorted(unknown)))
    return [ADAPTERS[name](settings) for name in names]
