"""Shared content pipeline: raw response -> extraction -> dedup/store -> link graph -> URL discovery.

Used by the live crawler, WARC / Common Crawl imports, local file ingestion and the /fetch API, so every
document goes through exactly the same quality and safety checks.
"""
import hashlib
import time

from .extract import extract
from .util import host_of, iso_to_ts, normalize_url, registrable_domain, utc_now


def _recency_bonus(ts, now):
    if not ts:
        return 0.0
    age = now - ts
    if age < 2 * 86400:
        return 3.0
    if age < 14 * 86400:
        return 1.5
    if age < 60 * 86400:
        return 0.5
    return 0.0


class Processor:
    def __init__(self, settings, store, frontier=None):
        self.settings, self.store, self.frontier = settings, store, frontier

    def process(self, url, final_url, status, headers, body, *, depth=0, fetched_at=None, previous_hash=None,
                enqueue=True, source_type=None, published_at=None, publication_source=None):
        headers = headers or {}
        final_url = normalize_url(final_url or url) or final_url or url
        content_type = headers.get("content-type", "")
        body_hash = hashlib.sha256(body).hexdigest()[:32]
        out = {"result": "ok", "status": status, "content_hash": body_hash, "changed": body_hash != previous_hash,
               "new_links": 0, "etag": headers.get("etag"), "last_modified": headers.get("last-modified")}
        ext = extract(body, final_url, content_type, self.settings)
        out["kind"] = ext.kind
        out["extraction_status"] = ext.status
        now = time.time()
        can_enqueue = enqueue and self.frontier is not None

        if ext.kind == "feed":
            if can_enqueue:
                items = []
                for e in ext.entries:
                    ts = iso_to_ts(e.get("published_at"))
                    items.append({"url": normalize_url(e["url"], final_url), "priority": 6.0 + _recency_bonus(ts, now),
                                  "source": "feed", "depth": depth + 1, "lastmod": ts})
                out["new_links"] = self.frontier.enqueue_many(items)
            out["entries"] = len(ext.entries)
            return out
        if ext.kind == "sitemap":
            if can_enqueue:
                items = []
                for loc, lastmod, prio, _freq in ext.sitemap_urls[:self.settings.max_sitemap_urls]:
                    ts = iso_to_ts(lastmod)
                    items.append({"url": normalize_url(loc, final_url), "source": "sitemap", "depth": depth + 1, "lastmod": ts,
                                  "priority": 4.0 + _recency_bonus(ts, now) + (prio or 0.5)})
                for loc, lastmod in (ext.sitemaps[:20] if depth < self.settings.max_sitemap_depth else []):
                    items.append({"url": normalize_url(loc, final_url), "source": "sitemap", "kind": "sitemap",
                                  "depth": depth + 1, "priority": 7.0, "lastmod": iso_to_ts(lastmod)})
                out["new_links"] = self.frontier.enqueue_many(items)
            out["entries"] = len(ext.sitemap_urls) + len(ext.sitemaps)
            return out

        # links + feeds discovered on HTML pages
        links = []
        if ext.links:
            seen = set()
            for href, anchor, nofollow in ext.links:
                key = normalize_url(href)
                if not key.startswith(("http://", "https://")) or key in seen or key == final_url:
                    continue
                seen.add(key)
                links.append((key, anchor, nofollow))
                if len(links) >= self.settings.max_links_per_page:
                    break
        if can_enqueue and not ext.nofollow:
            items = []
            src_host = host_of(final_url)
            for key, anchor, nofollow in links:
                prio = 3.0 - 0.25 * depth + (0.5 if host_of(key) == src_host else 0.0) - (2.0 if nofollow else 0.0)
                prio -= 0.05 * key.count("/") + (0.5 if "?" in key else 0.0)
                items.append({"url": key, "priority": prio, "source": "link", "depth": depth + 1})
            for feed in ext.feeds:
                items.append({"url": normalize_url(feed), "priority": 7.0, "source": "feed-link", "kind": "feed",
                              "depth": depth})
            if ext.canonical:
                canon = normalize_url(ext.canonical)
                if canon and canon != final_url:
                    items.append({"url": canon, "priority": 5.0, "source": "canonical", "depth": depth})
            out["new_links"] = self.frontier.enqueue_many(items)

        if ext.noindex:
            self.store.deactivate(url=final_url, reason="noindex")
            out.update(result="skipped", changed=False, extraction_status="noindex")
            return out
        if not ext.indexable:
            out.update(result="skipped", changed=False)
            return out
        # A same-site canonical that already exists in the store wins over this copy.
        if ext.canonical:
            canon = normalize_url(ext.canonical)
            if (canon and canon != final_url and registrable_domain(host_of(canon)) == registrable_domain(host_of(final_url))
                    and self.store.get_by_url(canon, with_text=False)):
                out.update(result="skipped", changed=False, extraction_status="non-canonical duplicate")
                return out
        from .language import document_language
        detected = document_language(ext.text, ext.lang or headers.get("content-language"),self.settings.language_detector,tuple(self.settings.document_languages.split(",")))
        ext.lang = detected["language"]
        meta = dict(ext.metadata)
        meta["language_evidence"] = detected
        if published_at and not ext.published_at:
            from .dates import parse_date
            ext.published_at = parse_date(published_at)
            if ext.published_at:
                meta["publication_source"] = publication_source or "provider"
        meta["http_status"] = status
        if ext.canonical:
            meta["canonical"] = ext.canonical
        for h in ("last-modified", "etag", "content-language"):
            if headers.get(h):
                meta[h] = headers[h][:200]
        modified = ext.modified_at
        if not modified and headers.get("last-modified"):
            from .dates import parse_date
            modified = parse_date(headers["last-modified"])
        res = self.store.upsert(
            final_url, ext.title or final_url, ext.text, final_url=final_url, description=ext.description,
            headings=" | ".join(ext.headings), lang=ext.lang, content_type=content_type.split(";")[0][:100],
            source_type=source_type or ext.source_type, published_at=ext.published_at, modified_at=modified,
            fetched_at=fetched_at or utc_now(), metadata=meta, extraction_status=ext.status, links=links,
            n_links=len(ext.links), hidden_chars=ext.hidden_chars)
        out.update(doc_id=res["id"], changed=res["changed"], doc_status=res["status"], duplicate_of=res["duplicate_of"],
                   title=ext.title)
        return out
