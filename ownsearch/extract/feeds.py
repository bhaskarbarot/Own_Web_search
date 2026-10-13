"""RSS 2.0 / RSS 1.0 (RDF) / Atom / JSON Feed parsing and XML + text sitemaps."""
import html
import json
import re
import xml.etree.ElementTree as ET

from ..dates import parse_date
from ..util import normalize_text

MAX_XML_BYTES = 20 * 1024 * 1024
MAX_SITEMAP_URLS = 50_000


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _parse_xml(data):
    if len(data) > MAX_XML_BYTES:
        data = data[:MAX_XML_BYTES]
    # DOCTYPE declarations are never needed for feeds/sitemaps; dropping them blocks entity tricks.
    data = re.sub(rb"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", b"", data[:4096], flags=re.I | re.S) + data[4096:]
    return ET.fromstring(data)


def _text(el):
    if el is None:
        return ""
    return normalize_text(html.unescape(re.sub(r"<[^>]+>", " ", "".join(el.itertext()))))


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def parse_feed(data, base_url=""):
    """-> {"title", "entries": [{"url", "title", "summary", "published_at"}]} or None."""
    stripped = data.lstrip()[:1]
    if stripped == b"{":
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return None
        if not isinstance(obj, dict) or "items" not in obj:
            return None
        entries = []
        for it in obj.get("items", [])[:1000]:
            if isinstance(it, dict) and (it.get("url") or it.get("external_url")):
                entries.append({"url": it.get("url") or it.get("external_url"),
                                "title": normalize_text(it.get("title", "")),
                                "summary": normalize_text(it.get("summary") or it.get("content_text") or "")[:1000],
                                "published_at": parse_date(it.get("date_published") or it.get("date_modified"))})
        return {"title": normalize_text(obj.get("title", "")), "entries": entries}
    try:
        root = _parse_xml(data)
    except ET.ParseError:
        return None
    kind = _local(root.tag)
    entries = []
    if kind in ("rss", "rdf"):
        channel = _child(root, "channel")
        title = _text(_child(channel, "title")) if channel is not None else ""
        items = [el for el in root.iter() if _local(el.tag) == "item"]
        for it in items[:2000]:
            link = _child(it, "link")
            url = _text(link) if link is not None else ""
            if not url:
                guid = _child(it, "guid")
                if guid is not None and guid.get("isPermaLink", "true") != "false":
                    url = _text(guid)
            if not url:
                continue
            date = None
            for name in ("pubdate", "date", "published", "updated", "modified"):
                d = _child(it, name)
                if d is not None:
                    date = parse_date(_text(d))
                    if date:
                        break
            entries.append({"url": url, "title": _text(_child(it, "title")),
                            "summary": _text(_child(it, "description", "summary", "encoded"))[:1000],
                            "published_at": date})
        return {"title": title, "entries": entries}
    if kind == "feed":
        title = _text(_child(root, "title"))
        for it in [el for el in root if _local(el.tag) == "entry"][:2000]:
            url = ""
            for link in it:
                if _local(link.tag) == "link" and link.get("href") and link.get("rel", "alternate") == "alternate":
                    url = link.get("href")
                    break
            if not url:
                continue
            date = None
            for name in ("published", "updated", "issued", "modified"):
                d = _child(it, name)
                if d is not None:
                    date = parse_date(_text(d))
                    if date:
                        break
            entries.append({"url": url, "title": _text(_child(it, "title")),
                            "summary": _text(_child(it, "summary", "content"))[:1000], "published_at": date})
        return {"title": title, "entries": entries}
    return None


def parse_sitemap(data):
    """-> {"urls": [(url, lastmod_iso|None, priority|None, changefreq|None)], "sitemaps": [(url, lastmod)]} or None."""
    head = data.lstrip()[:200].lower()
    if not head.startswith((b"<", b"\xef\xbb\xbf<")):
        # plain-text sitemap: one URL per line
        urls = []
        for line in data.decode("utf-8", "replace").splitlines()[:MAX_SITEMAP_URLS]:
            line = line.strip()
            if line.startswith(("http://", "https://")):
                urls.append((line, None, None, None))
        return {"urls": urls, "sitemaps": []} if urls else None
    try:
        root = _parse_xml(data)
    except ET.ParseError:
        return None
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        return None
    urls, maps = [], []
    for el in root:
        tag = _local(el.tag)
        if tag not in ("url", "sitemap"):
            continue
        loc = lastmod = prio = freq = None
        for c in el:
            t = _local(c.tag)
            if t == "loc":
                loc = (c.text or "").strip()
            elif t == "lastmod":
                lastmod = parse_date((c.text or "").strip())
            elif t == "priority":
                try:
                    prio = float((c.text or "").strip())
                except ValueError:
                    pass
            elif t == "changefreq":
                freq = (c.text or "").strip().lower()
            elif t in ("news",):                    # Google News sitemap extension
                for n in c.iter():
                    if _local(n.tag) == "publication_date" and not lastmod:
                        lastmod = parse_date((n.text or "").strip())
        if not loc:
            continue
        if tag == "url":
            urls.append((loc, lastmod, prio, freq))
        else:
            maps.append((loc, lastmod))
        if len(urls) + len(maps) >= MAX_SITEMAP_URLS:
            break
    return {"urls": urls, "sitemaps": maps}


def xml_text(data):
    """Generic XML -> text fallback."""
    try:
        root = _parse_xml(data)
    except ET.ParseError:
        return "", normalize_text(re.sub(r"<[^>]+>", " ", data.decode("utf-8", "replace")))
    title = ""
    for el in root.iter():
        if _local(el.tag) == "title" and (el.text or "").strip():
            title = normalize_text(el.text)
            break
    parts = [normalize_text(t) for t in root.itertext() if t and t.strip()]
    return title, "\n".join(parts)
