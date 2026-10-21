"""Bounded documentation links discovered from actual source pages, never guessed URLs."""
from urllib.parse import unquote, urlsplit
from collections import Counter
from .webquery import documentation_affinity
from .textproc import analyze
from .webmodels import WebCandidate,web_url
from .util import origin_of,utc_now


def named_site_seed(candidates,q):
    """A user-named HTTPS origin is a bounded fetch target, never a guessed result."""
    if not q.has_text or len(q.sites)!=1:return []
    host=q.sites[0]
    if any((urlsplit(item.url).hostname or '')==host or (urlsplit(item.url).hostname or '').endswith('.'+host)
           for item in candidates):return []
    url=web_url('https://'+host+'/')
    if not url or urlsplit(url).hostname!=host:return []
    return [WebCandidate(host,url,provider='requested_site',source_type='origin_seed',fetch_status='discovery_seed',
                         original_url=url,provenance=[{'provider':'site_filter','url':url,'evidence_level':'requested_origin'}])]


def seeds(candidates, q):
    if q.intent != 'tech_docs':
        return []
    wanted = set(q.required or q.entity_terms)
    result = []
    for item in candidates:
        location = urlsplit(item.url)
        host_terms = set(analyze(location.hostname or ''))
        path = location.path.strip('/')
        root_like = not path or path.count('/') <= 1 or path.rsplit('/', 1)[-1].startswith('index.')
        documentation = any(documentation_affinity(piece) >= .5
                            for piece in (location.hostname or '').split('.')+path.split('/')[:2])
        if wanted & host_terms and (root_like or documentation):
            result.append(item)
    return result[:1]


def links(page, q, limit=2):
    wanted = set(q.required or q.entity_terms)
    parent_host = urlsplit(page.url).hostname
    project = wanted & set(analyze(parent_host or ''))
    ranked, seen = [], {page.url}
    frequencies = Counter(term for url, anchor, _ in page.links
                          for term in set(analyze(unquote(urlsplit(url).path)+' '+anchor)) & wanted)
    specific = {term for term in wanted if frequencies[term] <= max(1, len(page.links)//10)}
    for url, anchor, nofollow in page.links:
        if nofollow or url in seen or urlsplit(url).hostname != parent_host:
            continue
        seen.add(url)
        matched = wanted & set(analyze(unquote(urlsplit(url).path)+' '+anchor))
        if not (matched - project) & specific:
            continue
        row = {'url': url, 'title': anchor or unquote(urlsplit(url).path.rsplit('/', 1)[-1]),
               'snippet': anchor, 'lang': page.language}
        item = WebCandidate.from_row(row, 'page_links', 1)
        if item:
            item.provenance.append({'provider': 'page_link', 'url': page.url,
                                    'evidence_level': 'link_on_fetched_page', 'anchor': anchor})
            ranked.append((len(matched), item))
    ranked.sort(key=lambda row: (-row[0], row[1].url))
    return [item for _, item in ranked[:limit]]


def sitemap_links(session, page, q, deadline):
    """At most two maps: robots declaration and one actual same-origin index child."""
    from .extract import extract, sniff
    wanted = set(q.required or q.entity_terms)
    host = urlsplit(page.url).hostname
    maps = [url for url in session.policy(page.url, deadline).sitemaps if web_url(url) and origin_of(url)==origin_of(page.url)]
    if not maps:
        return []
    response = session.page(maps[0], deadline)
    if response.status != 200 or sniff(response.body, response.content_type, response.final_url) not in ('sitemap', 'xml', 'text'):
        return []
    if origin_of(response.final_url)!=origin_of(page.url):return []
    if b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():return []
    ext = extract(response.body, response.final_url, response.content_type, session.settings)
    children=[url for url,*_ in ext.sitemaps if web_url(url) and origin_of(url)==origin_of(page.url) and url!=maps[0]]
    if not ext.sitemap_urls and children:
        children.sort(key=lambda url:(-len(wanted & set(analyze(unquote(urlsplit(url).path)))),url))
        response=session.page(children[0],deadline)
        if response.status!=200 or origin_of(response.final_url)!=origin_of(page.url):return []
        if b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():return []
        ext=extract(response.body,response.final_url,response.content_type,session.settings)
    ranked = []
    for url, *_ in ext.sitemap_urls[:session.settings.discovery_sitemap_limit]:
        if urlsplit(url).hostname != host or url == page.url:
            continue
        title = unquote(urlsplit(url).path).strip('/').replace('/', ' ')
        matched = wanted & set(analyze(title))
        if not matched:
            continue
        item = WebCandidate.from_row({'url': url, 'title': title}, 'sitemap_links', 1)
        if item:
            item.provenance.append({'provider': 'robots_sitemap', 'url': response.final_url,
                                    'evidence_level': 'url_in_declared_sitemap', 'parent_url': page.url})
            ranked.append((len(matched), item))
    ranked.sort(key=lambda row: (-row[0], row[1].url))
    return [item for _, item in ranked[:2]]


def feed_links(session,page,q,deadline):
    """One actual HTML-declared feed, same origin, under the page session budgets."""
    from .extract.feeds import parse_feed
    if not (q.intent=='news' or q.fresh_intent):return []
    feeds=[url for url in page.feeds if web_url(url) and origin_of(url)==origin_of(page.url)]
    if not feeds:return []
    response=session.page(feeds[0],deadline)
    if response.status!=200 or origin_of(response.final_url)!=origin_of(page.url):return []
    if b'<!DOCTYPE' in response.body.upper() or b'<!ENTITY' in response.body.upper():return []
    parsed=parse_feed(response.body,response.final_url,publication_only=True)
    if not parsed:return []
    wanted=set(q.required or q.entity_terms);ranked=[];seen={page.url}
    for row in parsed['entries'][:100]:
        url=web_url(row.get('url'))
        if not url or url in seen or origin_of(url)!=origin_of(page.url):continue
        seen.add(url)
        matched=wanted & set(analyze(str(row.get('title',''))+' '+str(row.get('summary',''))))
        if not matched:continue
        item=WebCandidate.from_row({'url':url,'title':row.get('title'),'snippet':row.get('summary',''),
                                    'published_at':row.get('published_at')},'page_feed',1)
        if item:
            item.provenance.append({'provider':'html_declared_feed','url':response.final_url,'parent_url':page.url,
                                    'evidence_level':'entry_in_declared_feed','retrieved_at':utc_now()})
            ranked.append((len(matched),item))
    ranked.sort(key=lambda pair:(-pair[0],pair[1].url))
    return [item for _,item in ranked[:2]]
