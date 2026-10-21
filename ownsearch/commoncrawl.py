"""Common Crawl CDX Index client and WARC archive resolver.

Enables independent, broad-web URL discovery and page retrieval across billions of
archived pages without relying on commercial search APIs or overloading live servers.
Uses public Common Crawl CDX APIs (https://index.commoncrawl.org/) and byte-range
requests against the public AWS S3 / data.commoncrawl.org archive.
"""
from dataclasses import dataclass
import gzip
import io
import json
import logging
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
import urllib.request

logger = logging.getLogger(__name__)

# Fallback default collection if collinfo is unreachable
DEFAULT_CC_INDEX = "CC-MAIN-2024-38-index"
CC_INDEX_BASE = "https://index.commoncrawl.org"
CC_DATA_BASE = "https://data.commoncrawl.org"


@dataclass(frozen=True)
class CDXRecord:
    url: str
    timestamp: str
    mime: str
    status: int
    digest: str
    filename: str
    offset: int
    length: int


def get_latest_index(timeout: float = 5.0) -> str:
    """Fetch the latest available Common Crawl index collection identifier."""
    collinfo_url = f"{CC_INDEX_BASE}/collinfo.json"
    req = urllib.request.Request(
        collinfo_url,
        headers={"User-Agent": "OwnSearch/2.0 (Independent research crawler)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data and isinstance(data, list) and "id" in data[0]:
                return data[0]["id"]
    except Exception as exc:
        logger.debug("Failed to retrieve latest CC collinfo, using default %s: %s", DEFAULT_CC_INDEX, exc)
    return DEFAULT_CC_INDEX


def query_cdx(
    url_pattern: str,
    index_id: Optional[str] = None,
    limit: int = 50,
    filter_status: str = "200",
    filter_mime: str = "text/html",
    timeout: float = 8.0,
) -> List[CDXRecord]:
    """Query Common Crawl CDX index for a URL or domain pattern.

    Args:
        url_pattern: e.g. '*.postgresql.org/*', 'docs.python.org/*', 'en.wikipedia.org/wiki/*'
        index_id: Common Crawl collection (defaults to latest available)
        limit: Maximum records to return
        filter_status: HTTP status code filter (default '200')
        filter_mime: MIME type filter (default 'text/html')
        timeout: Request deadline in seconds

    Returns:
        List of matching CDXRecord objects.
    """
    if not index_id:
        index_id = DEFAULT_CC_INDEX

    params = {
        "url": url_pattern,
        "output": "json",
        "limit": str(max(1, min(limit, 200))),
        "fl": "url,timestamp,mime,status,digest,filename,offset,length",
    }
    if filter_status:
        params["filter"] = f"=status:{filter_status}"
    if filter_mime:
        params["filter"] = f"=mime:{filter_mime}"

    endpoint = f"{CC_INDEX_BASE}/{index_id}?{urlencode(params)}"
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "OwnSearch/2.0 (Independent research crawler)",
            "Accept": "application/json, text/plain",
        }
    )

    records = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    records.append(
                        CDXRecord(
                            url=data.get("url", ""),
                            timestamp=data.get("timestamp", ""),
                            mime=data.get("mime", ""),
                            status=int(data.get("status", 200)),
                            digest=data.get("digest", ""),
                            filename=data.get("filename", ""),
                            offset=int(data.get("offset", 0)),
                            length=int(data.get("length", 0)),
                        )
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.debug("Common Crawl CDX query failed for %s: %s", url_pattern, exc)

    return records


def fetch_warc_html(
    record: CDXRecord,
    max_bytes: int = 1_048_576,
    timeout: float = 10.0,
) -> Optional[str]:
    """Fetch and decompress the HTML payload for a specific WARC record.

    Uses an HTTP Range request to fetch only the exact byte slice from Common Crawl,
    decompressing the gzip member and extracting the HTTP response body.
    """
    if not record.filename or record.length <= 0:
        return None

    warc_url = f"{CC_DATA_BASE}/{record.filename}"
    end_byte = record.offset + record.length - 1
    req = urllib.request.Request(
        warc_url,
        headers={
            "User-Agent": "OwnSearch/2.0 (Independent research crawler)",
            "Range": f"bytes={record.offset}-{end_byte}",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            compressed = resp.read(max_bytes * 2)
            if not compressed:
                return None
            try:
                decompressed = gzip.decompress(compressed)
            except Exception:
                # Try reading with GzipFile in case of trailing bytes
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as gz:
                        decompressed = gz.read()
                except Exception as gz_exc:
                    logger.debug("Gzip decompression error for %s: %s", record.url, gz_exc)
                    return None

            # WARC record format: WARC headers, then \r\n\r\n, then HTTP response headers,
            # then \r\n\r\n, then the actual payload.
            parts = decompressed.split(b"\r\n\r\n", 2)
            if len(parts) >= 3:
                body_bytes = parts[2]
            elif len(parts) == 2:
                body_bytes = parts[1]
            else:
                body_bytes = decompressed

            return body_bytes.decode("utf-8", errors="replace")[:max_bytes]
    except Exception as exc:
        logger.debug("Failed to fetch WARC record for %s: %s", record.url, exc)
        return None
