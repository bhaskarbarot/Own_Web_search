"""Bulk ingestion from web archives: WARC / WET files and the free Common Crawl index.

Common Crawl (https://commoncrawl.org) publishes free monthly crawls of billions of pages. OwnSearch reads
them directly: it queries the public CDX index for URL patterns you choose, downloads only the matching
records with HTTP Range requests, and runs them through the same pipeline as the live crawler.
No API key, no account, no fees.
"""
import gzip
import io
import json
import time
import zlib
from urllib.parse import quote

from .fetcher import FetchError, Fetcher
from .pipeline import Processor

CC_INDEX = "https://index.commoncrawl.org"
CC_DATA = "https://data.commoncrawl.org"


def _open(path):
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


def iter_warc(stream, max_record=64 * 1024 * 1024):
    """Yield (headers dict, payload bytes) for every WARC record in a (decompressed) stream."""
    while True:
        line = stream.readline()
        if not line:
            return
        if not line.strip():
            continue
        if not line.startswith(b"WARC/"):
            continue
        headers = {}
        while True:
            h = stream.readline()
            if not h or h in (b"\r\n", b"\n"):
                break
            if b":" in h:
                k, v = h.split(b":", 1)
                headers[k.decode("latin-1").strip().lower()] = v.decode("utf-8", "replace").strip()
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = 0
        if length > max_record:
            stream.read(length)
            continue
        payload = stream.read(length)
        yield headers, payload


def _dechunk(body):
    out, pos = bytearray(), 0
    while pos < len(body):
        end = body.find(b"\r\n", pos)
        if end < 0:
            break
        try:
            size = int(body[pos:end].split(b";")[0], 16)
        except ValueError:
            return body
        if size == 0:
            break
        out.extend(body[end + 2:end + 2 + size])
        pos = end + 2 + size + 2
    return bytes(out)


def parse_http_response(payload):
    """-> (status, headers dict lowercased, body) from a raw HTTP/1.x response block."""
    sep = payload.find(b"\r\n\r\n")
    head_len = 4
    if sep < 0:
        sep = payload.find(b"\n\n")
        head_len = 2
    if sep < 0:
        return None
    head = payload[:sep].decode("latin-1", "replace").splitlines()
    body = payload[sep + head_len:]
    if not head or not head[0].startswith("HTTP/"):
        return None
    try:
        status = int(head[0].split()[1])
    except (IndexError, ValueError):
        return None
    headers = {}
    for line in head[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            headers[k] = headers[k] + ", " + v.strip() if k in headers else v.strip()
    if "chunked" in headers.get("transfer-encoding", "").lower():
        body = _dechunk(body)
    enc = headers.get("content-encoding", "").lower()
    if enc in ("gzip", "x-gzip", "deflate"):
        try:
            body = zlib.decompressobj(16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS).decompress(
                body, 64 * 1024 * 1024)
            headers.pop("content-encoding", None)
        except zlib.error:
            pass  # Common Crawl usually stores the decoded body already
    return status, headers, body


def import_warc(path, engine, frontier=None, limit=None, log=None):
    """Index HTML/PDF/etc. responses (WARC) or extracted text (WET) from a local archive file."""
    processor = Processor(engine.settings, engine.store, frontier)
    stats = {"records": 0, "indexed": 0, "skipped": 0, "errors": 0}
    with _open(path) as stream:
        for headers, payload in iter_warc(stream):
            wtype = headers.get("warc-type", "")
            url = headers.get("warc-target-uri", "").strip("<>")
            if not url.startswith(("http://", "https://")):
                continue
            stats["records"] += 1
            try:
                date = headers.get("warc-date")
                if wtype == "response" and "application/http" in headers.get("content-type", ""):
                    parsed = parse_http_response(payload)
                    if not parsed or not 200 <= parsed[0] < 300:
                        stats["skipped"] += 1
                        continue
                    out = processor.process(url, url, parsed[0], parsed[1], parsed[2], fetched_at=date,
                                            enqueue=frontier is not None, source_type=None)
                elif wtype == "conversion":                       # WET plain text
                    text = payload.decode("utf-8", "replace")
                    title = text.split("\n", 1)[0][:200]
                    engine.store.upsert(url, title, text, fetched_at=date, source_type="web",
                                        extraction_status="wet")
                    out = {"result": "ok"}
                else:
                    continue
                stats["indexed" if out.get("result") == "ok" else "skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                if log:
                    log(f"[warc] error {url}: {e!r}"[:300])
            if limit and stats["records"] >= limit:
                break
            if log and stats["records"] % 500 == 0:
                log(f"[warc] {stats}")
    stats["index_changes"] = engine.rebuild_index()
    return stats


class CommonCrawl:
    def __init__(self, settings):
        self.settings = settings
        self.fetcher = Fetcher(settings)

    def crawls(self):
        res = self.fetcher.fetch(CC_INDEX + "/collinfo.json", accept="application/json", max_bytes=4_000_000)
        if res.status != 200:
            raise FetchError(f"collinfo HTTP {res.status}", "http")
        return json.loads(res.body.decode("utf-8"))

    def latest_crawl(self):
        return self.crawls()[0]["id"]

    def query(self, crawl, url_pattern, limit=100, filters=("status:200",), mime=None):
        params = f"url={quote(url_pattern, safe='*/:')}&output=json&limit={int(limit)}"
        for f in filters:
            params += "&filter=" + quote(f)
        if mime:
            params += "&filter=" + quote("mime:" + mime)
        res = self.fetcher.fetch(f"{CC_INDEX}/{crawl}-index?{params}", accept="application/json",
                                 max_bytes=64 * 1024 * 1024, retries=3)
        if res.status == 404:
            return []
        if res.status != 200:
            raise FetchError(f"CDX HTTP {res.status}: {res.body[:200]!r}", "http")
        out = []
        for line in res.body.decode("utf-8", "replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def fetch_record(self, rec):
        offset, length = int(rec["offset"]), int(rec["length"])
        res = self.fetcher.fetch(f"{CC_DATA}/{rec['filename']}", max_bytes=length + 1024,
                                 extra_headers={"Range": f"bytes={offset}-{offset + length - 1}"},
                                 accept="*/*", retries=3)
        if res.status not in (200, 206):
            raise FetchError(f"WARC range HTTP {res.status}", "http")
        data = gzip.decompress(res.body)
        for headers, payload in iter_warc(io.BytesIO(data)):
            if headers.get("warc-type") == "response":
                return headers, parse_http_response(payload)
        return None, None

    def import_pattern(self, engine, url_pattern, crawl=None, limit=100, frontier=None, delay=0.5, log=None):
        crawl = crawl or self.latest_crawl()
        records = self.query(crawl, url_pattern, limit=limit)
        processor = Processor(engine.settings, engine.store, frontier)
        stats = {"crawl": crawl, "pattern": url_pattern, "records": len(records), "indexed": 0, "skipped": 0,
                 "errors": 0}
        for i, rec in enumerate(records):
            url = rec.get("url", "")
            try:
                headers, parsed = self.fetch_record(rec)
                if not parsed or not 200 <= parsed[0] < 300:
                    stats["skipped"] += 1
                    continue
                out = processor.process(url, url, parsed[0], parsed[1], parsed[2],
                                        fetched_at=(headers or {}).get("warc-date"), enqueue=frontier is not None)
                stats["indexed" if out.get("result") == "ok" else "skipped"] += 1
                if log:
                    log(f"[cc] {i + 1}/{len(records)} {out.get('result')} {url}")
            except Exception as e:
                stats["errors"] += 1
                if log:
                    log(f"[cc] error {url}: {e}"[:300])
            time.sleep(delay)
        stats["index_changes"] = engine.rebuild_index()
        return stats
