"""Owned PDF/Office fixture builders; no database engine."""
import io
import zipfile
import zlib

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


