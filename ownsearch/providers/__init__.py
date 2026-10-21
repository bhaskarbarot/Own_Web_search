"""Optional external retrieval. Results remain untrusted, attributed source snippets."""
import json
import threading
import time
from dataclasses import dataclass,field
from urllib.parse import urlencode
from ..fetcher import Fetcher
from ..textproc import analyze,exact_tokens
from ..util import normalize_url,host_of,iso_to_ts

@dataclass
class Response:
    provider:str
    results:object=field(default_factory=list)
    status:str='ok'
    error:str=None
    elapsed_ms:float=0

class SearxProvider:
    name='searxng'
    def __init__(self,settings):self.settings=settings
    def search(self,query,deadline):
        url=self.settings.searxng_url.rstrip('/')+'/search?'+urlencode({'q':query,'format':'json','categories':self.settings.searxng_categories})
        response=Fetcher(self.settings).fetch(url,accept='application/json',max_bytes=2_000_000,retries=0,deadline=deadline)
        if response.status!=200:raise ValueError('HTTP '+str(response.status))
        raw=json.loads(response.body.decode('utf-8'))
        return [{'url':v.get('url',''),'title':v.get('title',''),'snippet':v.get('content',''),
                 'published_at':v.get('publishedDate'),'provider':self.name,'providers':[self.name],
                 'source_type':'provider_snippet','fetched_at':None,'lang':None,'crawl_status':'not_crawled'}
                for v in raw.get('results',[])[:50] if v.get('url')]

class Calls:
    """Finite daemon workers. Timeout does not claim an uncooperative provider stopped."""
    def __init__(self,maximum=4):self.slots=threading.BoundedSemaphore(maximum)
    def start(self,provider,query,deadline):
        state={'event':threading.Event(),'response':None,'name':provider.name,'deadline':deadline}
        if not self.slots.acquire(False):
            state['response']=Response(provider.name,status='busy',error='Provider capacity reached');state['event'].set();return state
        def run():
            started=time.perf_counter()
            try:result=Response(provider.name,provider.search(query,deadline))
            except Exception as exc:result=Response(provider.name,status=getattr(exc,'status','error'),error=f'{type(exc).__name__}: {exc}')
            result.elapsed_ms=round((time.perf_counter()-started)*1000,2)
            state['response']=result;state['event'].set();self.slots.release()
        threading.Thread(target=run,name='provider-'+provider.name,daemon=True).start()
        return state


def eligible(item,q):
    url=normalize_url(item.get('url'))
    if not url or not url.startswith(('http://','https://')):return False
    host=host_of(url)
    if q.sites and not any(host==s or host.endswith('.'+s) for s in q.sites):return False
    if any(host==s or host.endswith('.'+s) for s in q.not_sites):return False
    if q.filetypes or q.lang:return False  # provider has not supplied verifiable metadata
    text=item.get('title','')+' '+item.get('snippet','')
    terms=set(analyze(text)); required=set(q.required)
    if any(t in terms for t in q.excluded):return False
    if required and not required<=terms:return False
    if not required and not q.entities and not (set(q.entity_terms)&terms):return False
    exact=' '+' '.join(exact_tokens(text))+' '
    if any(' '+' '.join(p)+' ' not in exact for p in q.exact_phrases):return False
    if any(' '+' '.join(p)+' ' in exact for p in q.exact_excluded_phrases):return False
    if q.entities and not all(any(' '+' '.join(exact_tokens(n))+' ' in exact for n in e.names) for e in q.entities):return False
    title_terms=set(analyze(item.get('title','')))
    if q.intitle and not set(q.intitle)<=title_terms:return False
    if q.inurl and not set(q.inurl)<=set(analyze(url)):return False
    if q.intent=='financial' and not set(q.entity_terms)<=title_terms:return False
    stamp=iso_to_ts(item.get('published_at'))
    if q.intent=='news' and (stamp is None or stamp>time.time()+300):return False
    if (q.explicit_date_filter or q.intent=='news') and (stamp is None or (q.after is not None and stamp<q.after) or (q.before is not None and stamp>q.before)):return False
    return True
