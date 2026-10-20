"""Safe HTTP client written on http.client.

* Only http/https; URLs with credentials are rejected.
* DNS is resolved once, every address is checked (no private/loopback/link-local/reserved targets unless
  explicitly allowed) and the connection is pinned to the checked IP, which defeats DNS rebinding.
  TLS still verifies the certificate against the real hostname (SNI).
* Redirects are followed manually; every hop is re-validated and can be vetoed (robots.txt).
* gzip/deflate are decoded with a decompression-bomb limit. Unsupported encodings (br, zstd) raise an
  error instead of letting compressed bytes be indexed as text.
* Bounded reads, connect/read timeouts, transient-error retries with backoff, conditional GET support.
"""
import http.client
import ipaddress
import socket
import threading
_DNS_SLOTS = threading.BoundedSemaphore(8)
import ssl
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from .util import normalize_url

REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    """kind: invalid | blocked | dns | network | timeout | tls | too_large | encoding | robots | redirect"""

    def __init__(self, message, kind="network", retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after

    @property
    def transient(self):
        return self.kind in ("network", "timeout", "dns")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict
    body: bytes
    redirects: list = field(default_factory=list)
    elapsed: float = 0.0
    truncated: bool = False

    @property
    def content_type(self):
        return self.headers.get("content-type", "")

    @property
    def not_modified(self):
        return self.status == 304


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _retry_after(value):
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        from email.utils import parsedate_to_datetime
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def _inflate(data, wbits, limit):
    d = zlib.decompressobj(wbits)
    try:
        res = d.decompress(data, limit + 1)
    except zlib.error as e:
        raise FetchError(f"Corrupt compressed body: {e}", "encoding") from e
    if len(res) > limit or d.unconsumed_tail:
        raise FetchError("Decompressed body too large", "too_large")
    return res


def decode_content(body, encoding, limit):
    """Undo Content-Encoding (applied in listed order, so decode in reverse)."""
    out = body
    for enc in reversed([e.strip().lower() for e in (encoding or "").split(",") if e.strip()]):
        if enc in ("identity", "none"):
            continue
        if enc in ("gzip", "x-gzip"):
            out = _inflate(out, 16 + zlib.MAX_WBITS, limit)
        elif enc == "deflate":                  # servers disagree on zlib-wrapped vs raw deflate
            try:
                out = _inflate(out, zlib.MAX_WBITS, limit)
            except FetchError:
                out = _inflate(out, -zlib.MAX_WBITS, limit)
        else:
            raise FetchError(f"Unsupported Content-Encoding: {enc}", "encoding")
    return out


class Fetcher:
    def __init__(self, settings):
        self.settings = settings
        self.context = ssl.create_default_context()
        self.allow_private = bool(settings.allow_private_hosts)

    # ------------------------------------------------------------ validation
    def check_url(self, url):
        try:
            p = urlsplit(url)
        except ValueError as e:
            raise FetchError(f"Invalid URL: {e}", "invalid") from e
        if p.scheme not in ("http", "https") or not p.hostname:
            raise FetchError("Only absolute http/https URLs are supported", "invalid")
        if p.username or p.password:
            raise FetchError("URLs containing credentials are rejected", "invalid")
        if len(url) > 4096:
            raise FetchError("URL too long", "invalid")
        return p

    def _ip_allowed(self, ip):
        if self.allow_private:
            return not ip.is_unspecified and not ip.is_multicast
        return ip.is_global and not ip.is_multicast

    def resolve(self, host, port):
        host = host.strip("[]").rstrip(".").lower()
        if not self.allow_private and (host in ("localhost", "localhost.localdomain") or host.endswith(
                (".localhost", ".local", ".internal", ".lan", ".home.arpa"))):
            raise FetchError("Local hostnames are blocked", "blocked")
        try:
            ip = ipaddress.ip_address(host)
            if not self._ip_allowed(ip):
                raise FetchError("Non-public IP address blocked", "blocked")
            return str(ip)
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise FetchError(f"DNS lookup failed: {e}", "dns") from e
        except OSError as e:
            raise FetchError(f"DNS error: {e}", "dns") from e
        addrs = []
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if not self._ip_allowed(ip):
                raise FetchError("Host resolves to a non-public address; blocked", "blocked")
            addrs.append(str(ip))
        if not addrs:
            raise FetchError("Host did not resolve", "dns")
        v4 = [a for a in addrs if ":" not in a]
        return (v4 or addrs)[0]

    def _resolve_for_request(self,host,port,deadline):
        until=min(deadline or float('inf'),time.monotonic()+self.settings.fetch_timeout)
        if not _DNS_SLOTS.acquire(False):raise FetchError('DNS resolver capacity reached','timeout')
        event=threading.Event();result={}
        def lookup():
            try:result['ip']=self.resolve(host,port)
            except Exception as exc:result['error']=exc
            finally:_DNS_SLOTS.release();event.set()
        threading.Thread(target=lookup,name='ownsearch-dns',daemon=True).start()
        if not event.wait(max(0,until-time.monotonic())):raise FetchError('DNS lookup exceeded request deadline','timeout')
        if 'error' in result:raise result['error']
        return result['ip']

    # ------------------------------------------------------------ requests
    def _request_once(self, url, headers, max_bytes, method="GET", deadline=None):
        p = self.check_url(url)
        port = p.port or (443 if p.scheme == "https" else 80)
        ip = self._resolve_for_request(p.hostname, port, deadline)
        timeout = self.settings.fetch_timeout
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise FetchError("Request budget exhausted", "timeout")
        if p.scheme == "https":
            conn = _PinnedHTTPSConnection(p.hostname, port, ip, timeout, self.context)
        else:
            conn = _PinnedHTTPConnection(p.hostname, port, ip, timeout)
        path = (p.path or "/") + ("?" + p.query if p.query else "")
        try:
            conn.request(method, path, headers=headers)
            resp = conn.getresponse()
            hdrs = {}
            for k, v in resp.getheaders():
                k = k.lower()
                hdrs[k] = hdrs[k] + ", " + v if k in hdrs else v
            truncated = False
            chunks, size = [], 0
            if method != "HEAD":
                declared = hdrs.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes * 4:
                    raise FetchError(f"Declared body too large ({declared} bytes)", "too_large")
                while True:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise FetchError("Request budget exhausted", "timeout")
                        if conn.sock:
                            conn.sock.settimeout(min(timeout, remaining))
                    chunk = resp.read(min(65536, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        truncated = True
                        break
            body = b"".join(chunks)[:max_bytes]
            return resp.status, hdrs, body, truncated
        except socket.timeout as e:
            raise FetchError("Timed out", "timeout") from e
        except ssl.SSLCertVerificationError as e:
            raise FetchError(f"TLS certificate error: {e}", "tls") from e
        except ssl.SSLError as e:
            raise FetchError(f"TLS error: {e}", "network") from e
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            if isinstance(e, FetchError):
                raise
            raise FetchError(f"Network error: {e.__class__.__name__}: {e}", "network") from e
        finally:
            conn.close()

    def fetch(self, url, *, etag=None, last_modified=None, max_bytes=None, accept=None,
              allow=None, extra_headers=None, retries=None, method="GET", deadline=None, before_request=None, max_decompressed_bytes=None,
              preserve_query=False):
        """GET a URL safely. ``allow(url) -> bool`` vetoes redirect hops (robots.txt)."""
        max_bytes = int(max_bytes or self.settings.max_page_bytes)
        retries = self.settings.fetch_retries if retries is None else retries
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,"
                                "application/pdf;q=0.8,text/*;q=0.7,*/*;q=0.3",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en,*;q=0.5",
            "Connection": "close",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if extra_headers:
            headers.update(extra_headers)
        start = time.monotonic()
        self.check_url(url)
        canonicalize = (lambda value: urlsplit(value)._replace(fragment='').geturl()) if preserve_query else normalize_url
        current = canonicalize(url) or url
        redirects = []
        for hop in range(self.settings.max_redirects + 1):
            if hop and allow is not None and not allow(current):
                raise FetchError(f"Redirect target disallowed: {current}", "robots")
            attempt = 0
            while True:
                try:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise FetchError("Request budget exhausted", "timeout")
                    if before_request is not None:
                        before_request(current)
                    status, hdrs, body, truncated = self._request_once(current, headers, max_bytes, method, deadline)
                    break
                except FetchError as e:
                    if e.transient and attempt < retries:
                        attempt += 1
                        delay = min(8.0, 0.75 * 2 ** attempt)
                        if deadline is not None and time.monotonic() + delay >= deadline:
                            raise
                        time.sleep(delay)
                        continue
                    raise
            if status in REDIRECT_CODES and hdrs.get("location"):
                raw_target = urljoin(current, hdrs["location"].strip())
                self.check_url(raw_target)
                target = canonicalize(raw_target)
                if not target or not target.startswith(("http://", "https://")):
                    raise FetchError("Invalid redirect target", "redirect")
                redirects.append({"from": current, "to": target, "status": status})
                if target == current or any(r["from"] == target for r in redirects):
                    raise FetchError("Redirect loop", "redirect")
                old_origin = urlsplit(current)
                new_origin = urlsplit(target)
                if (old_origin.scheme, old_origin.netloc) != (new_origin.scheme, new_origin.netloc):
                    # API tokens, cookies and other caller headers must never
                    # travel to a different origin through a redirect.
                    sensitive = {k.lower() for k in (extra_headers or {})}
                    sensitive.update(("authorization", "cookie", "proxy-authorization"))
                    headers = {k: v for k, v in headers.items() if k.lower() not in sensitive}
                current = target
                headers.pop("If-None-Match", None)
                headers.pop("If-Modified-Since", None)
                continue
            if truncated and hdrs.get("content-encoding", "identity").lower() not in ("", "identity"):
                raise FetchError("Compressed body exceeded size limit", "too_large")
            body = decode_content(body, hdrs.get("content-encoding"), min(self.settings.max_decompressed_bytes, max_decompressed_bytes or self.settings.max_decompressed_bytes))
            result = FetchResult(url=url, final_url=current, status=status, headers=hdrs, body=body,
                                 redirects=redirects, elapsed=time.monotonic() - start, truncated=truncated)
            if status in (429, 503):
                ra = _retry_after(hdrs.get("retry-after"))
                result.headers["x-retry-after"] = "" if ra is None else str(ra)
            return result
        raise FetchError("Too many redirects", "redirect")
