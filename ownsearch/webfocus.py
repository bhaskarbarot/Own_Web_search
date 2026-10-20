"""Bounded documentation links discovered from actual source pages, never guessed URLs."""
from urllib.parse import unquote, urlsplit
from collections import Counter
from .webquery import documentation_affinity
from .textproc import analyze
from .webmodels import WebCandidate


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
    """Use one robots-declared sitemap on the fetched origin; never invent a target."""
    from .extract import extract, sniff
    wanted = set(q.required or q.entity_terms)
    host = urlsplit(page.url).hostname
    maps = [url for url in session.policy(page.url, deadline).sitemaps if urlsplit(url).hostname == host]
    if not maps:
        return []
    response = session.page(maps[0], deadline)
    if response.status != 200 or sniff(response.body, response.content_type, response.final_url) not in ('sitemap', 'xml', 'text'):
        return []
    ext = extract(response.body, response.final_url, response.content_type, session.settings)
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
