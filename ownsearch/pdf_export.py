"""Pure Python PDF generator for exporting search results without external dependencies."""
from pathlib import Path

def _escape_pdf(text):
    text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    # ASCII encode with replacement for standard 14 font compatibility
    return text.encode('latin-1', 'replace').decode('latin-1')

def generate_pdf(title, sections, output_path=None):
    """Generate a clean, formatted PDF with title and sections (list of (heading, text, url))."""
    lines = []
    lines.append(f"BT /F1 18 Tf 50 740 Td ({_escape_pdf(title)}) Tj ET")
    
    y = 700
    for heading, snippet, url in sections:
        if y < 80:
            break
        # Heading
        lines.append(f"BT /F1 12 Tf 50 {y} Td ({_escape_pdf(heading[:80])}) Tj ET")
        y -= 16
        # URL
        if url:
            lines.append(f"BT /F1 9 Tf 50 {y} Td ({_escape_pdf(url[:100])}) Tj ET")
            y -= 14
        # Snippet (split into ~85 char lines)
        words = snippet.split()
        cur_line = []
        for w in words:
            cur_line.append(w)
            if len(" ".join(cur_line)) > 85:
                text_line = " ".join(cur_line[:-1])
                lines.append(f"BT /F1 10 Tf 50 {y} Td ({_escape_pdf(text_line)}) Tj ET")
                y -= 13
                cur_line = [w]
                if y < 80:
                    break
        if cur_line and y >= 80:
            lines.append(f"BT /F1 10 Tf 50 {y} Td ({_escape_pdf(' '.join(cur_line))}) Tj ET")
            y -= 18
        y -= 10

    stream_content = "\n".join(lines).encode('latin-1')
    stream_len = len(stream_content)

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>")
    objects.append(b"<< /Length " + str(stream_len).encode('ascii') + b" >>\nstream\n" + stream_content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    body = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode('ascii') + obj + b"\nendobj\n"

    xref_offset = len(body)
    body += b"xref\n0 " + str(len(objects) + 1).encode('ascii') + b"\n0000000000 65535 f \n"
    for off in offsets:
        body += f"{off:010d} 00000 n \n".encode('ascii')

    body += b"trailer\n<< /Size " + str(len(objects) + 1).encode('ascii') + b" /Root 1 0 R >>\n"
    body += b"startxref\n" + str(xref_offset).encode('ascii') + b"\n%%EOF\n"

    if output_path:
        Path(output_path).write_bytes(body)
    return body
