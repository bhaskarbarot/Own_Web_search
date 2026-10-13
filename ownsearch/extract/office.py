"""Office and e-book formats from ZIP containers: DOCX, XLSX, PPTX, ODT/ODS/ODP, EPUB."""
import html
import io
import re
import zipfile

from ..dates import parse_date
from ..util import clean_multiline, normalize_text

MAX_UNCOMPRESSED = 80 * 1024 * 1024
MAX_RATIO = 200


class OfficeError(Exception):
    pass


def _read(z, name, budget):
    info = z.getinfo(name)
    if info.file_size > MAX_UNCOMPRESSED or (info.compress_size and info.file_size / info.compress_size > MAX_RATIO
                                             and info.file_size > 5 * 1024 * 1024):
        raise OfficeError(f"Suspicious compression ratio in {name}")
    budget[0] -= info.file_size
    if budget[0] < 0:
        raise OfficeError("Archive expands beyond the size limit")
    return z.read(name).decode("utf-8", "replace")


def _xml_to_text(xml, para_end=(), cell_end=()):
    for tag in para_end:
        xml = re.sub(rf"</{tag}>", "\n", xml)
    for tag in cell_end:
        xml = re.sub(rf"</{tag}>", "\t", xml)
    xml = re.sub(r"<(?:w:tab|w:br|a:br|text:tab|text:line-break)\b[^>]*/?>", " ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(text)


def _core_props(z, budget):
    meta = {}
    for name in ("docProps/core.xml", "meta.xml"):
        if name in z.namelist():
            xml = _read(z, name, budget)
            for key, pat in (("title", r"<dc:title>(.*?)</dc:title>"), ("author", r"<dc:creator>(.*?)</dc:creator>"),
                             ("subject", r"<dc:subject>(.*?)</dc:subject>"),
                             ("keywords", r"<(?:cp|meta):keyword[s]?>(.*?)</(?:cp|meta):keyword[s]?>"),
                             ("created", r"<(?:dcterms:created|meta:creation-date)[^>]*>(.*?)</"),
                             ("modified", r"<(?:dcterms:modified|dc:date)[^>]*>(.*?)</")):
                m = re.search(pat, xml, re.S)
                if m and m.group(1).strip():
                    meta[key] = normalize_text(html.unescape(m.group(1)))
    return meta


def _natural(name):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", name)]


def extract_zip_document(data, filename=""):
    """-> {"kind", "title", "text", "metadata", "published_at", "modified_at"} or None if not a known format."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    names = set(z.namelist())
    budget = [MAX_UNCOMPRESSED]
    kind, parts = None, []
    if "word/document.xml" in names:
        kind = "docx"
        for n in ["word/document.xml"] + sorted(x for x in names if re.match(r"word/(footnotes|endnotes)\.xml", x)):
            parts.append(_xml_to_text(_read(z, n, budget), para_end=("w:p",), cell_end=("w:tc",)))
    elif "xl/workbook.xml" in names:
        kind = "xlsx"
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in re.findall(r"<si>(.*?)</si>", _read(z, "xl/sharedStrings.xml", budget), re.S):
                shared.append(html.unescape(re.sub(r"<[^>]+>", "", si)))
        sheet_names = re.findall(r'<sheet[^>]*name="([^"]*)"', _read(z, "xl/workbook.xml", budget))
        sheets = sorted((x for x in names if re.match(r"xl/worksheets/sheet\d+\.xml$", x)), key=_natural)
        for i, n in enumerate(sheets[:50]):
            xml = _read(z, n, budget)
            rows = []
            for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S)[:20000]:
                cells = []
                for attrs, inner in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                    v = re.search(r"<v>(.*?)</v>", inner, re.S)
                    if 't="s"' in attrs and v:
                        try:
                            cells.append(shared[int(v.group(1))])
                        except (ValueError, IndexError):
                            pass
                    elif "inlineStr" in attrs:
                        cells.append(html.unescape(re.sub(r"<[^>]+>", "", inner)))
                    elif v:
                        cells.append(html.unescape(v.group(1)))
                if cells:
                    rows.append("\t".join(cells))
            title = sheet_names[i] if i < len(sheet_names) else f"Sheet {i + 1}"
            parts.append(f"{html.unescape(title)}\n" + "\n".join(rows))
    elif "ppt/presentation.xml" in names:
        kind = "pptx"
        slides = sorted((x for x in names if re.match(r"ppt/slides/slide\d+\.xml$", x)), key=_natural)
        for n in slides[:2000]:
            parts.append(_xml_to_text(_read(z, n, budget), para_end=("a:p",)))
        notes = sorted((x for x in names if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", x)), key=_natural)
        for n in notes[:2000]:
            parts.append(_xml_to_text(_read(z, n, budget), para_end=("a:p",)))
    elif "content.xml" in names and "mimetype" in names:
        mime = z.read("mimetype")[:100].decode("ascii", "replace")
        kind = {"text": "odt", "spreadsheet": "ods", "presentation": "odp"}.get(
            next((k for k in ("text", "spreadsheet", "presentation") if k in mime), ""), "odf")
        parts.append(_xml_to_text(_read(z, "content.xml", budget), para_end=("text:p", "text:h", "table:table-row"),
                                  cell_end=("table:table-cell",)))
    elif "META-INF/container.xml" in names:
        kind = "epub"
        from .html import extract_html
        container = _read(z, "META-INF/container.xml", budget)
        m = re.search(r'full-path="([^"]+)"', container)
        opf_path = m.group(1) if m else ""
        order = []
        if opf_path in names:
            opf = _read(z, opf_path, budget)
            base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
            manifest = dict(re.findall(r'<item[^>]*id="([^"]+)"[^>]*href="([^"]+)"', opf))
            manifest.update({k: v for v, k in re.findall(r'<item[^>]*href="([^"]+)"[^>]*id="([^"]+)"', opf)})
            for idref in re.findall(r'<itemref[^>]*idref="([^"]+)"', opf):
                if idref in manifest:
                    order.append(base + manifest[idref])
        if not order:
            order = sorted(x for x in names if x.endswith((".xhtml", ".html", ".htm")))
        for n in order[:3000]:
            if n in names:
                parts.append(extract_html(_read(z, n, budget))["text"])
    if kind is None:
        return None
    meta = _core_props(z, budget)
    text = clean_multiline("\n".join(parts))
    return {"kind": kind, "title": meta.get("title", ""), "text": text, "metadata": meta,
            "published_at": parse_date(meta.get("created")), "modified_at": parse_date(meta.get("modified"))}
