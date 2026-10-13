"""Image metadata (dimensions, PNG text chunks, JPEG EXIF/XMP/comments) parsed from raw bytes."""
import re
import struct
import zlib


def image_info(data):
    """-> {"format", "width", "height", "text": [...], "exif": {...}} (best effort, never raises)."""
    info = {"format": None, "width": None, "height": None, "text": [], "exif": {}}
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            _png(data, info)
        elif data.startswith(b"\xff\xd8"):
            _jpeg(data, info)
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            info["format"] = "gif"
            info["width"], info["height"] = struct.unpack("<HH", data[6:10])
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            info["format"] = "webp"
            chunk = data[12:16]
            if chunk == b"VP8X":
                info["width"] = 1 + int.from_bytes(data[24:27], "little")
                info["height"] = 1 + int.from_bytes(data[27:30], "little")
            elif chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                info["width"], info["height"] = w & 0x3FFF, h & 0x3FFF
            elif chunk == b"VP8L":
                b = int.from_bytes(data[21:25], "little")
                info["width"], info["height"] = (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        elif data[:2] == b"BM":
            info["format"] = "bmp"
            info["width"], info["height"] = struct.unpack("<ii", data[18:26])
            info["height"] = abs(info["height"])
        elif data[:4] in (b"II*\x00", b"MM\x00*"):
            info["format"] = "tiff"
            _tiff_ifd(data, 0, info)
    except (struct.error, IndexError, ValueError):
        pass
    xmp = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>", data[:2_000_000], re.S)
    if xmp:
        x = xmp.group(0).decode("utf-8", "replace")
        for tag in ("dc:title", "dc:description", "dc:subject", "photoshop:Headline", "Iptc4xmpCore:Location"):
            for m in re.finditer(rf"<{tag}>(.*?)</{tag}>", x, re.S):
                txt = re.sub(r"<[^>]+>", " ", m.group(1))
                txt = " ".join(txt.split())
                if txt:
                    info["text"].append(txt)
    return info


def _png(data, info):
    info["format"] = "png"
    info["width"], info["height"] = struct.unpack(">II", data[16:24])
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"tEXt":
            k, _, v = body.partition(b"\x00")
            info["text"].append(f"{k.decode('latin-1')}: {v.decode('latin-1', 'replace')}")
        elif ctype == b"zTXt":
            k, _, rest = body.partition(b"\x00")
            try:
                info["text"].append(f"{k.decode('latin-1')}: {zlib.decompress(rest[1:]).decode('latin-1', 'replace')}")
            except zlib.error:
                pass
        elif ctype == b"iTXt":
            parts = body.split(b"\x00", 5)
            if len(parts) == 6:
                k, comp, _m, _lang, _tk, text = parts[0], parts[1][:1], parts[2], parts[3], parts[4], parts[5]
                try:
                    text = zlib.decompress(text) if comp == b"\x01" else text
                    info["text"].append(f"{k.decode('latin-1')}: {text.decode('utf-8', 'replace')}")
                except zlib.error:
                    pass
        elif ctype == b"IEND":
            break
        pos += 12 + length


_EXIF_TAGS = {0x010E: "ImageDescription", 0x013B: "Artist", 0x8298: "Copyright", 0x9003: "DateTimeOriginal",
              0x0132: "DateTime", 0x010F: "Make", 0x0110: "Model", 0x9286: "UserComment", 0x9C9B: "XPTitle",
              0x9C9F: "XPSubject", 0x9C9C: "XPComment", 0x9C9E: "XPKeywords"}


def _tiff_ifd(tiff, base, info, depth=0):
    if depth > 3 or len(tiff) < 8:
        return
    endian = "<" if tiff[:2] == b"II" else ">"
    (off,) = struct.unpack(endian + "I", tiff[4:8])
    seen = set()
    queue = [off]
    while queue and len(seen) < 8:
        off = queue.pop()
        if off in seen or off + 2 > len(tiff):
            continue
        seen.add(off)
        (n,) = struct.unpack(endian + "H", tiff[off:off + 2])
        for i in range(min(n, 500)):
            e = off + 2 + 12 * i
            if e + 12 > len(tiff):
                break
            tag, typ, count = struct.unpack(endian + "HHI", tiff[e:e + 8])
            raw = tiff[e + 8:e + 12]
            if tag == 0x8769:                   # Exif sub-IFD
                queue.append(struct.unpack(endian + "I", raw)[0])
                continue
            if tag in (0x0100, 0x0101) and info.get("format") == "tiff":
                val = struct.unpack(endian + ("H" if typ == 3 else "I"), raw[:2] if typ == 3 else raw)[0]
                info["width" if tag == 0x0100 else "height"] = val
            name = _EXIF_TAGS.get(tag)
            if not name or typ not in (1, 2, 7):
                continue
            if count > 4:
                (voff,) = struct.unpack(endian + "I", raw)
                value = tiff[voff:voff + min(count, 4096)]
            else:
                value = raw[:count]
            if name.startswith("XP"):
                text = value.decode("utf-16-le", "replace")
            elif name == "UserComment":
                text = value[8:].decode("utf-8", "replace") if value[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00") \
                    else value.decode("latin-1", "replace")
            else:
                text = value.decode("utf-8", "replace")
            text = text.strip("\x00 ").strip()
            if text:
                info["exif"][name] = text[:1000]


def _jpeg(data, info):
    info["format"] = "jpeg"
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xD9 or marker == 0xDA:
            break
        (length,) = struct.unpack(">H", data[pos + 2:pos + 4])
        seg = data[pos + 4:pos + 2 + length]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            info["height"], info["width"] = struct.unpack(">HH", seg[1:5])
        elif marker == 0xE1 and seg.startswith(b"Exif\x00\x00"):
            _tiff_ifd(seg[6:], 0, info)
        elif marker == 0xFE:
            c = seg.decode("utf-8", "replace").strip()
            if c:
                info["text"].append(c[:1000])
        pos += 2 + length
