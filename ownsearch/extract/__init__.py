"""Content-type detection and extraction dispatch.

The kind of a response is decided from its bytes first (magic numbers, binary sniffing) and only then from
Content-Type / file extension, so mislabelled binaries are never indexed as text.
"""
import codecs
import re
import zlib
from dataclasses import dataclass, field

from ..dates import date_from_url, parse_date
from ..util import clean_multiline, file_extension, normalize_text

TEXT_EXTS = {"txt", "md", "markdown", "rst", "csv", "tsv", "log", "json", "yaml", "yml", "toml", "ini", "cfg",
             "py", "js", "ts", "java", "c", "h", "cpp", "go", "rs", "rb", "php", "sh", "sql", "tex", "srt", "vtt"}
_TEXT_BYTES = bytes(range(32, 127)) + b"\t\n\r\x0c\x1b" + bytes(range(128, 256))
_BINARY_MAGIC = (b"\x7fELF", b"MZ", b"7z\xbc\xaf", b"Rar!", b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x1cftyp",
                 b"\x00\x00\x00\x20ftyp", b"OggS", b"ID3", b"fLaC", b"\x00asm", b"\x1aE\xdf\xa3", b"wOFF", b"wOF2",
                 b"\x00\x01\x00\x00\x00", b"OTTO", b"\xca\xfe\xba\xbe", b"SQLite format 3", b"BZh", b"\xfd7zXZ")


@dataclass
class Extracted:
    kind: str                         # html pdf office text feed sitemap image xml binary empty
    title: str = ""
    text: str = ""
    headings: list = field(default_factory=list)
    markdown: str = ""
    code_blocks: list = field(default_factory=list)
    description: str = ""
    lang: str = ""
    published_at: str = None
    modified_at: str = None
    canonical: str = None
    links: list = field(default_factory=list)        # (url, anchor, nofollow)
    feeds: list = field(default_factory=list)
    noindex: bool = False
    nofollow: bool = False
    entries: list = field(default_factory=list)      # feed entries
    sitemap_urls: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    status: str = "ok"
    source_type: str = "web"
    hidden_chars: int = 0
    text_chars: int = 0

    @property
    def indexable(self):
        return self.kind in ("html", "pdf", "office", "text", "image", "xml") and bool(self.title or self.text)


def looks_binary(data):
    sample = data[:8192]
    if not sample:
        return False
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE, codecs.BOM_UTF8)):
        return False
    if b"\x00" in sample:
        return True
    bad = len(sample.translate(None, _TEXT_BYTES))
    return bad / len(sample) > 0.02


def sniff(data, content_type="", url=""):
    head = data[:16]
    if data.startswith(b"%PDF") or b"%PDF-" in data[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if (head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
            or (head[:4] == b"RIFF" and data[8:12] == b"WEBP")):
        return "image"
    if head.startswith(_BINARY_MAGIC) or looks_binary(data):
        return "binary"
    ct = (content_type or "").split(";")[0].strip().lower()
    low = data[:2048].lstrip().lower()
    if low.startswith(b"\xef\xbb\xbf"):
        low = low[3:]
    if b"<rss" in low or (b"<feed" in low and b"atom" in low) or b"<rdf:rdf" in low:
        return "feed"
    if b"<urlset" in low or b"<sitemapindex" in low:
        return "sitemap"
    if ct == "application/feed+json" or (ct.endswith("json") and b'"jsonfeed.org' in low):
        return "feed"
    if low.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or (b"<html" in low and b"<body" in low):
        return "html"
    if "html" in ct:
        return "html"
    if low.startswith(b"<?xml") or ct.endswith("xml"):
        return "xml"
    ext = file_extension(url)
    if ext in ("html", "htm", "xhtml"):
        return "html"
    if ext == "xml":
        return "xml"
    if ct.startswith("text/") or "json" in ct or ext in TEXT_EXTS or not ct:
        return "text"
    return "text" if not looks_binary(data) else "binary"


def decode_text(data, content_type=""):
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8", "replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    charset = None
    m = re.search(r"charset=[\"']?([\w.:-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    if not charset:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", data[:4096], re.I) or \
            re.search(rb"<\?xml[^>]+encoding=[\"']([\w.:-]+)", data[:512], re.I)
        if m:
            charset = m.group(1).decode("ascii", "replace")
    if charset:
        try:
            codecs.lookup(charset)
            if charset.lower() in ("iso-8859-1", "latin-1", "latin1", "us-ascii", "ascii"):
                charset = "cp1252"          # what browsers actually do
            return data.decode(charset, "replace")
        except LookupError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            from charset_normalizer import from_bytes
            guess = from_bytes(data[:1_000_000]).best()
            if guess is not None and guess.encoding and guess.percent_coherence >= 30:
                return data.decode(guess.encoding, "replace")
        except (ImportError, LookupError): pass
        return data.decode("cp1252", "replace")


def _first_line_title(text):
    for line in text.split("\n")[:20]:
        line = line.strip()
        if 3 <= len(line) <= 200:
            return line
    return ""


def _name_words(url):
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    return normalize_text(re.sub(r"[_\-.+%]+", " ", name))


def extract(data, url, content_type="", settings=None, depth=0):
    """Turn raw bytes into an Extracted record."""
    if not data:
        return Extracted(kind="empty", status="empty")
    kind = sniff(data, content_type, url)
    if kind == "gzip" and depth == 0:
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            inner = d.decompress(data, 64 * 1024 * 1024)
        except zlib.error:
            return Extracted(kind="binary", status="corrupt gzip")
        return extract(inner, re.sub(r"\.gz$", "", url), "", settings, depth + 1)
    if kind == "html":
        from .html import extract_html
        r = extract_html(decode_text(data, content_type), url)
        return Extracted(kind="html", title=r["title"], text=r["text"], headings=r["headings"],
                         markdown=r.get("markdown", ""), code_blocks=r.get("code_blocks", []),
                         description=r["description"], lang=r["lang"],
                         published_at=r["published_at"] or date_from_url(url), modified_at=r["modified_at"],
                         canonical=r["canonical"], links=r["links"], feeds=r["feeds"], noindex=r["noindex"],
                         nofollow=r["nofollow"], metadata=dict(r["metadata"], images=r["images"][:20],
                         publication_date_source='page_metadata' if r['published_at'] else 'url_inferred'),
                         hidden_chars=r["hidden_chars"], text_chars=r["text_chars"],
                         status="ok" if r["text"] else "no_text", source_type="web")
    if kind == "pdf":
        return _extract_pdf(data, url, settings)
    if kind == "zip":
        from .office import OfficeError, extract_zip_document
        try:
            r = extract_zip_document(data, url)
        except (OfficeError, Exception) as e:
            return Extracted(kind="binary", status=f"failed: {e}"[:200])
        if r is None:
            return Extracted(kind="binary", status="zip archive (not indexed)")
        return Extracted(kind="office", title=r["title"] or _first_line_title(r["text"]) or _name_words(url),
                         text=r["text"], metadata=r["metadata"], published_at=r["published_at"],
                         modified_at=r["modified_at"], source_type=r["kind"],
                         status="ok" if r["text"] else "no_text")
    if kind == "feed":
        from .feeds import parse_feed
        r = parse_feed(data, url)
        if r is None:
            return Extracted(kind="xml", status="unparseable feed")
        return Extracted(kind="feed", title=r["title"], entries=r["entries"], source_type="feed")
    if kind == "sitemap":
        from .feeds import parse_sitemap
        r = parse_sitemap(data)
        if r is None:
            return Extracted(kind="xml", status="unparseable sitemap")
        return Extracted(kind="sitemap", sitemap_urls=r["urls"], sitemaps=r["sitemaps"], source_type="sitemap")
    if kind == "image":
        return _extract_image(data, url, settings)
    if kind == "xml":
        from .feeds import parse_sitemap, xml_text
        if url.endswith((".txt",)) or "sitemap" in url.lower():
            r = parse_sitemap(data)
            if r:
                return Extracted(kind="sitemap", sitemap_urls=r["urls"], sitemaps=r["sitemaps"], source_type="sitemap")
        title, text = xml_text(data)
        return Extracted(kind="xml", title=title or _name_words(url), text=clean_multiline(text), source_type="xml")
    if kind == "text":
        text = decode_text(data, content_type)
        if "sitemap" in url.lower() and url.lower().endswith(".txt"):
            from .feeds import parse_sitemap
            r = parse_sitemap(data)
            if r:
                return Extracted(kind="sitemap", sitemap_urls=r["urls"], source_type="sitemap")
        ext = file_extension(url)
        if ext == "json" or (content_type or "").startswith("application/json"):
            text = re.sub(r'[{}\[\]",]+', " ", text)
        text = clean_multiline(text)
        return Extracted(kind="text", title=_first_line_title(text) if ext in ("md", "markdown", "rst", "txt") else "",
                         text=text, source_type="text" if not ext else ext)
    return Extracted(kind="binary", status="binary content (not indexed)", source_type="binary")


def _extract_pdf(data, url, settings):
    from .pdf import PdfError, extract_pdf, image_for_ocr
    try:
        r = extract_pdf(data)
    except PdfError as e:
        return Extracted(kind="binary", status=f"pdf: {e}"[:200], source_type="pdf")
    except Exception as e:
        return Extracted(kind="binary", status=f"pdf parse error: {e.__class__.__name__}"[:200], source_type="pdf")
    pages = r["pages"]
    meta = r["metadata"]
    status = "ok"
    chars = sum(len(p) for p in pages)
    if settings is not None and pages and chars / len(pages) < 40 and r["images"]:
        from .ocr import ocr_available, ocr_image
        if ocr_available(settings):
            done = 0
            for page_no, stm in r["images"]:
                if done >= settings.ocr_max_pages:
                    break
                try:
                    img = image_for_ocr(r["doc"], stm)
                except Exception:
                    img = None
                if not img:
                    continue
                text, st = ocr_image(img[0], img[1], settings)
                done += 1
                if text.strip():
                    pages[page_no - 1] = (pages[page_no - 1] + "\n" + text).strip()
            status = "ocr" if sum(len(p) for p in pages) > chars else "no_text (scanned, OCR found nothing)"
        else:
            status = "no_text (scanned PDF; OCR unavailable)"
    elif not chars:
        status = "no_text"
    text = "\f".join(clean_multiline(p) for p in pages)
    title = normalize_text(meta.get("Title", ""))
    if not title or title.lower() in ("untitled", "microsoft word - document1") or len(title) < 3:
        title = _first_line_title(text.replace("\f", "\n")) or _name_words(url)
    meta_out = {k: v for k, v in meta.items() if k in ("Author", "Subject", "Keywords", "Creator", "Producer",
                                                       "page_count", "encrypted")}
    return Extracted(kind="pdf", title=title, text=text, metadata=meta_out,
                     published_at=parse_date(meta.get("CreationDate")), modified_at=parse_date(meta.get("ModDate")),
                     status=status, source_type="pdf",
                     description=normalize_text(meta.get("Subject", ""))[:500])


def _extract_image(data, url, settings):
    from .image import image_info
    info = image_info(data)
    parts = [_name_words(url)] + info["text"] + list(info["exif"].values())
    status = "metadata"
    w, h = info.get("width") or 0, info.get("height") or 0
    if settings is not None and w * h >= 100 * 30 and w * h <= 40_000_000:
        from .ocr import ocr_available, ocr_image
        if ocr_available(settings):
            suffix = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "bmp": ".bmp", "tiff": ".tif",
                      "webp": ".webp"}.get(info["format"], ".img")
            text, st = ocr_image(data, suffix, settings)
            if text.strip():
                parts.append(text)
                status = "ocr"
    meta = {"format": info["format"], "width": w, "height": h, **{k: v for k, v in info["exif"].items()}}
    return Extracted(kind="image", title=_name_words(url) or "image", text=clean_multiline("\n".join(p for p in parts if p)),
                     metadata=meta, status=status, source_type="image",
                     published_at=parse_date(info["exif"].get("DateTimeOriginal", "").replace(":", "-", 2)))
