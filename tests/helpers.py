"""Test fixtures: a local test website, PDF/DOCX builders and an isolated engine factory."""
import gzip
import io
import tempfile
import threading
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ownsearch.config import Settings
from ownsearch.engine import SearchEngine


def test_settings(tmp, **kw):
    base = dict(allow_private_hosts=True, default_delay=0.0, max_crawl_delay=0.0, fetch_retries=0,
                fetch_timeout=5.0, crawl_threads=4, log_queries=False, ocr="off",
                market_lookup_url="", market_chart_url="", news_feeds="", news_feeds_file="",
                knowledge_enabled=False, searxng_url="", financial_provider_url="", brave_api_key="")
    base.update(kw)
    return Settings.load(tmp, **base)


def make_engine(**kw):
    tmp = tempfile.mkdtemp(prefix="ownsearch-test-")
    return SearchEngine(settings=test_settings(tmp, **kw)), tmp


def make_pdf(pages, title="Test PDF", compress=True, use_objstm=False):
    """Minimal valid PDF (Helvetica, one content stream per page, xref table)."""
    objs = {}
    n_pages = len(pages)
    font_id = 3
    first_page = 4
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    objs[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    for i, text in enumerate(pages):
        pid, cid = first_page + 2 * i, first_page + 2 * i + 1
        objs[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> "
                     f"/Contents {cid} 0 R >>").encode()
        lines = []
        y = 740
        for line in text.split("\n"):
            esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"BT /F1 12 Tf 72 {y} Td ({esc}) Tj ET")
            y -= 16
        stream = "\n".join(lines).encode("latin-1")
        if compress:
            data = zlib.compress(stream)
            objs[cid] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"
        else:
            objs[cid] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    info_id = max(objs) + 1
    objs[info_id] = f"<< /Title ({title}) /CreationDate (D:20240115120000Z) >>".encode()
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = out.tell()
        out.write(f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n")
    xref = out.tell()
    size = max(objs) + 1
    out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for num in range(1, size):
        out.write(f"{offsets[num]:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {size} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs, title="Docx Title"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        z.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')
        z.writestr("docProps/core.xml", f'<cp:coreProperties xmlns:dc="dc"><dc:title>{title}</dc:title>'
                                        f"<dcterms:created>2024-02-01T00:00:00Z</dcterms:created></cp:coreProperties>")
    return buf.getvalue()


WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
         "romeo sierra tango uniform victor whiskey xray yankee zulu").split()


def page_text(i):
    # unique, readable content per page
    w = [WORDS[(i * 7 + k * 3) % len(WORDS)] for k in range(60)]
    return f"Page number {i} talks about topic{i} and " + " ".join(w) + f". Unique marker token zq{i}x."


class TestSite:
    """Local website exercising every crawler edge case."""

    def __init__(self, n_pages=120):
        self.n = n_pages
        self.hits = {}
        self.flaky_count = 0
        self.lock = threading.Lock()
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                with site.lock:
                    site.hits[self.path] = site.hits.get(self.path, 0) + 1
                route = site.route(self.path, self.headers)
                status, headers, body = route
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def html(self, title, body, extra_head=""):
        return (f"<!doctype html><html lang=en><head><title>{title}</title>{extra_head}</head>"
                f"<body><nav><a href='/'>Home</a></nav><main>{body}</main><footer>footer text</footer></body></html>").encode()

    def route(self, path, headers):
        H = {"Content-Type": "text/html; charset=utf-8"}
        n = self.n
        if path == "/robots.txt":
            return 200, {"Content-Type": "text/plain"}, (
                "User-agent: *\nDisallow: /private/\nCrawl-delay: 0\n"
                f"Sitemap: {self.base}/sitemap.xml\n").encode()
        if path == "/sitemap.xml":
            urls = "".join(f"<url><loc>{self.base}/page/{i}</loc><lastmod>2024-05-0{1 + i % 9}</lastmod></url>"
                           for i in range(1, n // 2))
            return 200, {"Content-Type": "application/xml"}, (
                f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}'
                f"<url><loc>{self.base}/doc.pdf</loc></url></urlset>").encode()
        if path == "/":
            links = "".join(f"<a href='/page/{i}'>page {i}</a> " for i in range(1, 6))
            return 200, H, self.html("Test Site Home", f"<h1>Welcome</h1><p>Home of the test site.</p>{links}"
                                     "<a href='/feed.xml'>feed</a> <a href='/private/secret'>secret</a>"
                                     "<a href='/redirect'>moved</a> <a href='/gone'>gone</a> <a href='/flaky'>flaky</a>"
                                     "<a href='/binary.html'>bin</a> <a href='/brotli'>br</a> <a href='/dup/a'>a</a>"
                                     "<a href='/dup/b'>b</a> <a href='/print/7'>print</a> <a href='/noindex'>ni</a>"
                                     "<a href='/page/3?utm_source=newsletter'>tracked</a>",
                                     "<link rel=alternate type='application/rss+xml' href='/feed.xml'>")
        if path.startswith("/page/"):
            try:
                i = int(path.split("/")[2].split("?")[0])
            except ValueError:
                return 404, H, b"not found"
            if not 1 <= i <= n:
                return 404, H, b"not found"
            links = " ".join(f"<a href='/page/{j}'>link to page {j}</a>" for j in (i + 1, i * 2, i + 7) if j <= n)
            body = self.html(f"Page {i} title", f"<h1>Heading {i}</h1><p>{page_text(i)}</p><p>{links}</p>")
            if i % 5 == 0:                                   # gzip-encoded responses
                return 200, dict(H, **{"Content-Encoding": "gzip"}), gzip.compress(body)
            return 200, H, body
        if path.startswith("/news/"):
            i = path.split("/")[2]
            return 200, H, self.html(f"Breaking news {i}", f"<p>Fresh news story number {i} about the election results.</p>",
                                     f"<meta property='article:published_time' content='2026-10-0{i}T08:00:00Z'>")
        if path == "/feed.xml":
            items = "".join(f"<item><title>News {i}</title><link>{self.base}/news/{i}</link>"
                            f"<pubDate>Mon, 0{i} Oct 2026 08:00:00 GMT</pubDate></item>" for i in range(1, 4))
            return 200, {"Content-Type": "application/rss+xml"}, (
                f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test feed</title>{items}</channel></rss>').encode()
        if path == "/doc.pdf":
            return 200, {"Content-Type": "application/pdf"}, make_pdf(
                ["Quarterly report introduction", "The secret ingredient is cardamom in the recipe"], "Quarterly Report")
        if path == "/redirect":
            return 301, {"Location": "/page/2"}, b""
        if path == "/gone":
            return 404, H, b"gone"
        if path == "/flaky":
            with self.lock:
                self.flaky_count += 1
                first = self.flaky_count == 1
            if first:
                return 503, dict(H, **{"Retry-After": "0"}), b"try later"
            return 200, H, self.html("Flaky page", "<p>Recovered after a temporary failure.</p>")
        if path == "/binary.html":                        # compressed bytes labelled as HTML (the v0.1 bug)
            return 200, H, gzip.compress(b"x" * 2000 + bytes(range(256)) * 20)
        if path == "/brotli":
            return 200, dict(H, **{"Content-Encoding": "br"}), b"\x1b\x03\x00\xf8\xa5\x40\x02"
        if path in ("/dup/a", "/dup/b"):
            return 200, H, self.html("Duplicate page", "<p>" + page_text(999) * 3 + "</p>")
        if path == "/print/7":
            return 200, H, self.html("Page 7 title", f"<h1>Heading 7</h1><p>{page_text(7)}</p>",
                                     f"<link rel=canonical href='{self.base}/page/7'>")
        if path == "/noindex":
            return 200, H, self.html("Hidden page", "<p>Should not be indexed nzq.</p>",
                                     "<meta name=robots content='noindex'>")
        if path.startswith("/private/"):
            return 200, H, self.html("Secret", "<p>top secret text</p>")
        return 404, H, b"not found"
