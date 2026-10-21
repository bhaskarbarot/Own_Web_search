"""Independent official-API adapters; URLs and descriptions come from responses."""
import re
import copy
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from .webmodels import plain, web_url
from .webproviders import JsonProvider, ProviderError, SourceBatch
from .provider_health import ProviderHealth
from .util import utc_now


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


class PyPIApiProvider(ApiProvider):
    name='pypi'
    missing_is_empty=True

    def project_name(self,request):
        match=re.search(r'\b(?:pip\s+install|pypi(?:\s+package)?|python(?:\s+(?:package|library))?)\s+`?([A-Za-z0-9][A-Za-z0-9._-]*)',request.query,re.I)
        if not match:return None
        name=match.group(1).rstrip('.')
        if name.lower() in {'library','libraries','package','packages','program','programs','code','documentation','official','module','modules'}:return None
        return name

    def accepts(self,request):
        return super().accepts(request) and bool(self.project_name(request))

    def search(self,request,deadline):
        name=self.project_name(request)
        if not name:return SourceBatch()
        try:data=self.request(request,self.settings.pypi_api_url.format(name=quote(name,safe='')),deadline)
        except ProviderError as exc:
            if exc.http_status==404:return SourceBatch([],['Exact package name was not found; no package URL was invented.'])
            raise
        info=data.get('info')
        if not isinstance(info,dict) or not isinstance(info.get('name'),str):raise ProviderError('PyPI returned invalid project metadata.')
        norm=lambda text:re.sub('[-_.]+','-',text).lower()
        if norm(info['name'])!=norm(name):raise ProviderError('PyPI metadata does not match the requested project.')
        links=info.get('project_urls') if isinstance(info.get('project_urls'),dict) else {}
        links={**links,'Package':info.get('package_url'),'Project':info.get('project_url'),'Homepage':info.get('home_page')}
        rows=[];seen=set()
        description=plain(info.get('summary',''),300)+' '+plain(info.get('description',''),900)
        for label,url in links.items():
            if not isinstance(url,str) or url in seen:continue
            seen.add(url)
            row=self.row(request,url,info['name']+' '+str(label),description)
            if row:row['source_query']=name;rows.append(row)
            if len(rows)>=10:break
        return SourceBatch(rows)


class NpmApiProvider(ApiProvider):
    name='npm'

    def accepts(self,request):
        return super().accepts(request) and bool(re.search(r'\b(?:npm|javascript|typescript|node(?:\.js)?)\b',request.query,re.I))

    def search(self,request,deadline):
        data=self.get(request,self.settings.npm_api_url,{'text':api_query(request),'size':10},deadline)
        items=data.get('objects')
        if not isinstance(items,list):raise ProviderError('npm API returned an invalid objects array.')
        rows=[];seen=set()
        for obj in items[:10]:
            item=obj.get('package') if isinstance(obj,dict) else None
            if not isinstance(item,dict) or not isinstance(item.get('name'),str):continue
            links=item.get('links')
            if not isinstance(links,dict):continue
            for label in ('npm','homepage','repository'):
                url=links.get(label)
                if not isinstance(url,str) or url in seen:continue
                seen.add(url)
                row=self.row(request,url,item['name']+' '+label,item.get('description',''))
                if row:rows.append(row)
                if len(rows)>=10:return SourceBatch(rows)
        return SourceBatch(rows)


class CratesApiProvider(ApiProvider):
    name='crates'

    def accepts(self,request):
        return super().accepts(request) and bool(re.search(r'\b(?:rust|cargo|crates?)\b',request.query,re.I))

    def search(self,request,deadline):
        data=self.get(request,self.settings.crates_api_url,{'q':api_query(request),'per_page':10},deadline)
        items=data.get('crates')
        if not isinstance(items,list):raise ProviderError('crates.io API returned an invalid crates array.')
        rows=[];seen=set()
        for item in items[:10]:
            if not isinstance(item,dict) or not isinstance(item.get('name') or item.get('id'),str):continue
            for label in ('documentation','homepage','repository'):
                url=item.get(label)
                if not isinstance(url,str) or url in seen:continue
                seen.add(url)
                row=self.row(request,url,(item.get('name') or item['id'])+' '+label,item.get('description',''))
                if row:rows.append(row)
                if len(rows)>=10:return SourceBatch(rows)
        return SourceBatch(rows)


def research_request(request):
    return bool(re.search(r'\b(?:papers?|research|studies|study|preprints?|arxiv|meta[- ]analysis)\b',request.query,re.I))


def atom_document(body):
    text=body.decode('utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('XML declarations are forbidden.')
    try:return ElementTree.fromstring(text)
    except ElementTree.ParseError:raise ValueError('Malformed Atom response.') from None


class ArxivApiProvider(ApiProvider):
    name='arxiv'
    minimum_interval=3.0
    _connection=threading.Lock()
    _last_finished=0.0
    _cache=OrderedDict()

    def accepts(self,request):return super().accepts(request) and research_request(request)

    def search(self,request,deadline):
        key=(self.settings.arxiv_api_url,api_query(request))
        if not self._connection.acquire(timeout=max(0,deadline-time.monotonic())):
            raise ProviderError('arXiv single-connection budget unavailable.','rate_limited')
        sent=False
        try:
            cached=self._cache.get(key)
            if cached and time.monotonic()-cached[0]<86400:
                batch=copy.deepcopy(cached[1])
                for row in batch.rows:row['source_cached']=True
                batch.warnings.append('arXiv metadata cache hit; original source retrieval and publication timestamps retained.')
                return batch
            wait=max(0,type(self)._last_finished+3-time.monotonic())
            if time.monotonic()+wait>=deadline or request.cancel.wait(wait):
                raise ProviderError('arXiv pacing exceeds deadline; no request sent.','rate_limited')
            if not self.settings.arxiv_api_url.startswith('https://'):raise ProviderError('arXiv API requires HTTPS.')
            sent=True
            data=self.request(request,self.settings.arxiv_api_url+'?'+urlencode({'search_query':'all:'+api_query(request),
                              'start':0,'max_results':10}),deadline,decoder=atom_document,accept='application/atom+xml')
            ns='{http://www.w3.org/2005/Atom}';rows=[];stamp=utc_now()
            for entry in data.findall(ns+'entry')[:10]:
                links=[link.get('href') for link in entry.findall(ns+'link') if link.get('rel')=='alternate' and link.get('type') in (None,'text/html')]
                url=next((u for u in links if web_url(u)),None)
                if not url:continue
                row=self.row(request,url,entry.findtext(ns+'title'),entry.findtext(ns+'summary') or '',entry.findtext(ns+'published'))
                if row:row.update(source_retrieved_at=stamp,source_cached=False);rows.append(row)
            batch=SourceBatch(rows)
            self._cache[key]=(time.monotonic(),copy.deepcopy(batch));self._cache.move_to_end(key)
            while len(self._cache)>128:self._cache.popitem(last=False)
            return batch
        finally:
            if sent:type(self)._last_finished=time.monotonic()
            self._connection.release()


class OpenAlexApiProvider(ApiProvider):
    name='openalex'
    quota_reset_is_delay=True

    def accepts(self,request):return super().accepts(request) and research_request(request)

    def search(self,request,deadline):
        headers={'Authorization':'Bearer '+self.settings.openalex_api_key} if self.settings.openalex_api_key else None
        data=self.request(request,self.settings.openalex_api_url+'?'+urlencode({'search':api_query(request),'per_page':10}),deadline,headers=headers)
        items=data.get('results')
        if not isinstance(items,list):raise ProviderError('OpenAlex API returned an invalid results array.')
        rows=[]
        for item in items[:10]:
            if not isinstance(item,dict):continue
            location=item.get('primary_location') if isinstance(item.get('primary_location'),dict) else {}
            url=location.get('landing_page_url') or item.get('doi') or item.get('id')
            inverted=item.get('abstract_inverted_index');words={}
            if isinstance(inverted,dict):
                for word,positions in list(inverted.items())[:2000]:
                    if not isinstance(word,str) or not isinstance(positions,list):continue
                    for position in positions[:1000]:
                        if type(position) is int and 0<=position<300:words.setdefault(position,word)
            abstract=' '.join(words[pos] for pos in sorted(words))
            row=self.row(request,url,item.get('display_name') or item.get('title'),abstract,item.get('publication_date'),item.get('language'))
            if row:rows.append(row)
        return SourceBatch(rows)


ADAPTERS={'wikipedia':WikipediaApiProvider,'wikidata':WikidataApiProvider,'github':GitHubApiProvider,'pypi':PyPIApiProvider,'npm':NpmApiProvider,'crates':CratesApiProvider,'arxiv':ArxivApiProvider,'openalex':OpenAlexApiProvider}


def configured_verticals(settings):
    names=list(dict.fromkeys(n.strip() for n in settings.vertical_providers.split(',') if n.strip()))
    unknown=set(names)-set(ADAPTERS)
    if unknown: raise ValueError('Unknown vertical providers: '+', '.join(sorted(unknown)))
    return [ADAPTERS[name](settings) for name in names]
