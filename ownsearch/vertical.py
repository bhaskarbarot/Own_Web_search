"""Independent official-API adapters; URLs and descriptions come from responses."""
import re
from dataclasses import replace
from urllib.parse import urlencode

from .webmodels import plain, web_url
from .webproviders import JsonProvider, ProviderError, SourceBatch
from .provider_health import ProviderHealth


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


class GitHubApiProvider(ApiProvider):
    name = 'github'
    minimum_interval = 6.1  # unauthenticated search <=10/min, plus <=60/hour budget

    def __init__(self, settings):
        super().__init__(settings)
        self.health = ProviderHealth(replace(settings,provider_request_budget=min(60,settings.provider_request_budget),
                                             provider_budget_window=max(3600,settings.provider_budget_window)))

    def accepts(self, request):
        return super().accepts(request) and bool(re.search(r'\b(?:github|repos?|repositories|repository)\b|open[- ]source',request.query,re.I))

    def search(self, request, deadline):
        issue=bool(re.search(r'\b(?:bugs?|issues?)\b',request.query,re.I))
        query=re.sub(r'\b(?:github|repositories|repository|repos?|projects?)\b','',api_query(request),flags=re.I)
        query=' '.join(query.split())[:230].rsplit(' ',1)[0] if len(query)>230 else ' '.join(query.split())
        if issue:
            query+=' is:issue'
            if re.search(r'\bopen\s+(?:bugs?|issues?)\b',request.query,re.I):query+=' is:open'
        endpoint=self.settings.github_api_url.rstrip('/')+'/search/'+('issues' if issue else 'repositories')
        headers={'Accept':'application/vnd.github+json'}
        if self.settings.github_api_token:headers['Authorization']='Bearer '+self.settings.github_api_token
        data=self.request(request,endpoint+'?'+urlencode({'q':query,'per_page':10}),deadline,headers=headers)
        items=data.get('items')
        if not isinstance(items,list):raise ProviderError('GitHub API returned an invalid items array.')
        rows=[]
        for item in items[:10]:
            if not isinstance(item,dict):continue
            row=self.row(request,item.get('html_url'),item.get('title') if issue else item.get('full_name'),
                         item.get('body','') if issue else item.get('description',''),
                         published=item.get('created_at') if issue else None)
            if row:row['source_query']=query;rows.append(row)
        return SourceBatch(rows,['GitHub search reports incomplete results.'] if data.get('incomplete_results') else [])


ADAPTERS={'wikipedia':WikipediaApiProvider,'wikidata':WikidataApiProvider,'github':GitHubApiProvider}


def configured_verticals(settings):
    names=list(dict.fromkeys(n.strip() for n in settings.vertical_providers.split(',') if n.strip()))
    unknown=set(names)-set(ADAPTERS)
    if unknown: raise ValueError('Unknown vertical providers: '+', '.join(sorted(unknown)))
    return [ADAPTERS[name](settings) for name in names]
