"""Structured feed registry validation; no network at import or configuration load."""
from dataclasses import dataclass
from urllib.parse import urlparse
from .language import tag

CATEGORIES={'general','news','business','science','technology','sports','culture','health'}
@dataclass(frozen=True)
class Feed:
    url:str
    lang:str='und'
    region:str='ZZ'
    category:str='general'

def registry(lines):
    feeds=[]; errors=[];seen=set()
    for number,line in enumerate(lines,1):
        if not line.strip() or line.lstrip().startswith('#'):continue
        parts=line.strip().split('\t')
        if len(parts)==1:parts += ['und','ZZ','general']  # legacy URL file migration
        if len(parts)!=4:
            errors.append(f'line {number}: expected four tab-separated columns');continue
        url,lang,region,category=parts
        if urlparse(url).scheme not in ('http','https') or not urlparse(url).hostname or ',' in lang or ';' in lang or not tag(lang) or not (len(region)==2 and region.isalpha()) or category not in CATEGORIES:
            errors.append(f'line {number}: invalid URL or metadata');continue
        if url not in seen:feeds.append(Feed(url,lang,region.upper(),category));seen.add(url)
    return feeds,errors


def check_updates(feed, client, now=None):
    """Explicit health check: distinguish unavailable, empty, stale and usable feeds."""
    import time
    from .util import iso_to_ts
    response=client.fetch(feed.url,max_bytes=2_000_000)
    if response.status!=200:return {'url':feed.url,'status':'unavailable','http_status':response.status}
    # Shared extractor understands RSS, Atom and JSON feeds.
    from .extract import extract
    entries=extract(response.body,feed.url,response.headers.get('content-type','')).entries
    dates=[iso_to_ts(e.get('published_at')) for e in entries];dates=[d for d in dates if d is not None and d <= (now or time.time())+300]
    age=(now or time.time())-max(dates) if dates else None
    return {'url':feed.url,'status':'empty' if not entries else 'stale' if age and age>7*86400 else 'ok',
            'entries':len(entries),'latest_age_seconds':age,'dated_entries':len(dates)}
