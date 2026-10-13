"""From-scratch PDF text extraction.

Supported: classic xref tables and xref streams (with /Prev chains), a full-file scan fallback for broken
xrefs, object streams, filters (Flate with PNG/TIFF predictors, LZW, ASCIIHex, ASCII85, RunLength),
the page tree with inherited resources, Form XObjects, fonts with ToUnicode CMaps, simple-font encodings
(WinAnsi/MacRoman/Standard + /Differences), Info/XMP metadata, per-page text (pages separated by "\\f"),
and RC4/AES-128 encryption with an empty user password.

Images on pages are returned (raw stream + parameters) so scanned PDFs can be OCR'd.
"""
import hashlib
import re
import struct
import zlib

from .aes import aes_cbc_decrypt

WS = b" \t\r\n\x0c\x00"
DELIM = b"()<>[]{}/%"
_NUM_RE = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_REF_RE = re.compile(rb"(\d+)\s+R(?=[\s/<>\[\]()%]|$)")


class PdfError(Exception):
    pass


class Name(str):
    __slots__ = ()


class Ref(tuple):
    __slots__ = ()

    def __new__(cls, num, gen):
        return tuple.__new__(cls, (num, gen))


class Op(str):
    __slots__ = ()


class Stream:
    __slots__ = ("dict", "raw", "num", "gen")

    def __init__(self, d, raw, num=0, gen=0):
        self.dict, self.raw, self.num, self.gen = d, raw, num, gen


# ---------------------------------------------------------------- lexer

class Lexer:
    def __init__(self, data, pos=0, refs=True):
        self.data, self.pos, self.refs = data, pos, refs
        self.n = len(data)

    def skip_ws(self):
        d, n, p = self.data, self.n, self.pos
        while p < n:
            c = d[p]
            if c in WS:
                p += 1
            elif c == 0x25:                         # % comment
                while p < n and d[p] not in b"\r\n":
                    p += 1
            else:
                break
        self.pos = p

    def _regular(self):
        d, n, p = self.data, self.n, self.pos
        start = p
        while p < n and d[p] not in WS and d[p] not in DELIM:
            p += 1
        self.pos = p
        return d[start:p]

    def next(self):
        """Return the next object, Op, or raise EOFError."""
        self.skip_ws()
        if self.pos >= self.n:
            raise EOFError
        d = self.data
        c = d[self.pos]
        if c == 0x2F:                               # /Name
            self.pos += 1
            raw = self._regular()
            if b"#" in raw:
                raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
            return Name(raw.decode("latin-1"))
        if c == 0x28:
            return self._literal()
        if c == 0x3C:
            if d[self.pos + 1:self.pos + 2] == b"<":
                self.pos += 2
                return self._dict()
            return self._hex()
        if c == 0x5B:
            self.pos += 1
            arr = []
            while True:
                self.skip_ws()
                if self.pos >= self.n:
                    return arr
                if d[self.pos] == 0x5D:
                    self.pos += 1
                    return arr
                arr.append(self.next())
        if c in b"]>)}{":
            self.pos += 1
            return Op(chr(c))
        tok = self._regular()
        if not tok:
            self.pos += 1
            return Op(chr(c))
        if _NUM_RE.fullmatch(tok):
            if b"." in tok:
                try:
                    return float(tok)
                except ValueError:
                    return 0.0
            val = int(tok)
            if self.refs:
                save = self.pos
                self.skip_ws()
                m = _REF_RE.match(d, self.pos)
                if m:
                    self.pos = m.end()
                    return Ref(val, int(m.group(1)))
                self.pos = save
            return val
        if tok == b"true":
            return True
        if tok == b"false":
            return False
        if tok == b"null":
            return None
        return Op(tok.decode("latin-1"))

    def _dict(self):
        out = {}
        d = self.data
        while True:
            self.skip_ws()
            if self.pos >= self.n:
                return out
            if d[self.pos:self.pos + 2] == b">>":
                self.pos += 2
                return out
            key = self.next()
            if not isinstance(key, Name):
                continue
            self.skip_ws()
            if d[self.pos:self.pos + 2] == b">>":
                out[str(key)] = None
                continue
            out[str(key)] = self.next()

    def _literal(self):
        d, n = self.data, self.n
        self.pos += 1
        depth, out = 1, bytearray()
        while self.pos < n:
            c = d[self.pos]
            self.pos += 1
            if c == 0x5C:                           # backslash
                if self.pos >= n:
                    break
                e = d[self.pos]
                self.pos += 1
                if e in b"nrtbf":
                    out.append({0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}[e])
                elif 0x30 <= e <= 0x37:
                    v = e - 0x30
                    for _ in range(2):
                        if self.pos < n and 0x30 <= d[self.pos] <= 0x37:
                            v = v * 8 + d[self.pos] - 0x30
                            self.pos += 1
                    out.append(v & 0xFF)
                elif e == 0x0D:
                    if self.pos < n and d[self.pos] == 0x0A:
                        self.pos += 1
                elif e == 0x0A:
                    pass
                else:
                    out.append(e)
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    break
                out.append(c)
            else:
                out.append(c)
        return bytes(out)

    def _hex(self):
        end = self.data.find(b">", self.pos)
        if end < 0:
            end = self.n
        raw = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[self.pos + 1:end])
        self.pos = end + 1
        if len(raw) % 2:
            raw += b"0"
        return bytes.fromhex(raw.decode("ascii"))


# ---------------------------------------------------------------- filters

def _png_unpredict(data, columns, colors, bpc):
    bpp = max(1, colors * bpc // 8)
    row_len = (columns * colors * bpc + 7) // 8
    out = bytearray()
    prev = bytearray(row_len)
    i = 0
    while i < len(data):
        ft = data[i]
        row = bytearray(data[i + 1:i + 1 + row_len])
        i += 1 + row_len
        if len(row) < row_len:
            row.extend(b"\x00" * (row_len - len(row)))
        if ft == 1:
            for x in range(bpp, row_len):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif ft == 2:
            for x in range(row_len):
                row[x] = (row[x] + prev[x]) & 0xFF
        elif ft == 3:
            for x in range(row_len):
                left = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ft == 4:
            for x in range(row_len):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[x] = (row[x] + pred) & 0xFF
        out.extend(row)
        prev = row
    return bytes(out)


def _lzw(data, early=1):
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    bits, buf, nbits, prev = 9, 0, 0, None
    for byte in data:
        buf = (buf << 8) | byte
        nbits += 8
        while nbits >= bits:
            nbits -= bits
            code = (buf >> nbits) & ((1 << bits) - 1)
            if code == 256:
                table = table[:258]
                bits, prev = 9, None
                continue
            if code == 257:
                return bytes(out)
            if prev is None:
                entry = table[code] if code < len(table) else b""
            elif code < len(table):
                entry = table[code]
                table.append(prev + entry[:1])
            else:
                entry = prev + prev[:1]
                table.append(entry)
            out.extend(entry)
            prev = entry
            size = len(table) + early
            if size >= 4096:
                bits = 12
            elif size >= 2048:
                bits = 12
            elif size >= 1024:
                bits = 11
            elif size >= 512:
                bits = 10
    return bytes(out)


def _a85(data):
    data = re.sub(rb"\s", b"", data)
    if data.startswith(b"<~"):
        data = data[2:]
    end = data.find(b"~>")
    if end >= 0:
        data = data[:end]
    out, group = bytearray(), []
    for c in data:
        if c == 0x7A and not group:
            out.extend(b"\x00\x00\x00\x00")
            continue
        if not 33 <= c <= 117:
            continue
        group.append(c - 33)
        if len(group) == 5:
            v = 0
            for g in group:
                v = v * 85 + g
            out.extend(struct.pack(">I", v & 0xFFFFFFFF))
            group = []
    if group:
        n = len(group)
        group += [84] * (5 - n)
        v = 0
        for g in group:
            v = v * 85 + g
        out.extend(struct.pack(">I", v & 0xFFFFFFFF)[:n - 1])
    return bytes(out)


def _runlength(data):
    out, i = bytearray(), 0
    while i < len(data):
        n = data[i]
        i += 1
        if n == 128:
            break
        if n < 128:
            out.extend(data[i:i + n + 1])
            i += n + 1
        else:
            out.extend(data[i:i + 1] * (257 - n))
            i += 1
    return bytes(out)


def _inflate(data):
    try:
        return zlib.decompress(data)
    except zlib.error:
        pass
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            d = zlib.decompressobj(wbits)
            return d.decompress(data, 256 * 1024 * 1024)
        except zlib.error:
            continue
    # last resort: decode byte by byte up to the corruption point
    d = zlib.decompressobj()
    out = bytearray()
    for i in range(0, len(data), 1024):
        try:
            out.extend(d.decompress(data[i:i + 1024]))
        except zlib.error:
            break
    return bytes(out)


IMAGE_FILTERS = {"DCTDecode", "DCT", "JPXDecode", "CCITTFaxDecode", "CCF", "JBIG2Decode"}


# ---------------------------------------------------------------- RC4 / encryption

def _rc4(key, data):
    s = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + s[i] + key[i % klen]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for k, byte in enumerate(data):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out[k] = byte ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


class _Decryptor:
    """Standard security handler with the empty user password (R2-R4: RC4 / AESV2, R5/R6: AESV3)."""

    def __init__(self, enc, file_id):
        self.v = int(enc.get("V", 0) or 0)
        self.r = int(enc.get("R", 0) or 0)
        self.aes = False
        self.encrypt_metadata = enc.get("EncryptMetadata", True) is not False
        if self.v >= 4:
            cf = enc.get("CF") or {}
            stmf = str(enc.get("StmF", "Identity"))
            method = str((cf.get(stmf) or {}).get("CFM", "V2"))
            if method == "None" or stmf == "Identity":
                self.key = None
                return
            self.aes = method in ("AESV2", "AESV3")
        if self.r >= 5:
            self.key = self._key_r6(enc)
            return
        length = int(enc.get("Length", 40) or 40) // 8 if self.v >= 2 else 5
        o = enc.get("O", b"")[:32]
        p = int(enc.get("P", 0)) & 0xFFFFFFFF
        h = hashlib.md5(_PAD + o + struct.pack("<I", p) + (file_id or b""))
        if self.r >= 4 and not self.encrypt_metadata:
            h.update(b"\xff\xff\xff\xff")
        key = h.digest()[:length]
        if self.r >= 3:
            for _ in range(50):
                key = hashlib.md5(key[:length]).digest()[:length]
        self.key = key[:length]

    def _key_r6(self, enc):
        u = enc.get("U", b"")
        ue = enc.get("UE", b"")
        salt = u[40:48]
        if self.r == 5:
            ikey = hashlib.sha256(salt).digest()
        else:
            ikey = _hash_r6(b"", salt, b"")
        return aes_cbc_decrypt(ikey, b"\x00" * 16 + ue[:32], unpad=False) if len(ue) >= 32 else None

    def decrypt(self, data, num, gen):
        if not self.key or not data:
            return data
        if self.r >= 5:
            key = self.key
        else:
            ext = self.key + struct.pack("<I", num)[:3] + struct.pack("<I", gen)[:2]
            if self.aes:
                ext += b"sAlT"
            key = hashlib.md5(ext).digest()[:min(len(self.key) + 5, 16)]
        if self.aes:
            if len(data) < 32:
                return b""
            return aes_cbc_decrypt(key, data)
        return _rc4(key, data)


def _hash_r6(password, salt, udata):
    from .aes import aes_cbc_encrypt
    k = hashlib.sha256(password + salt + udata).digest()
    i = 0
    while True:
        k1 = (password + k + udata) * 64
        e = aes_cbc_encrypt(k[:16], k[16:32], k1)
        mod = sum(e[:16]) % 3
        k = (hashlib.sha256, hashlib.sha384, hashlib.sha512)[mod](e).digest()
        i += 1
        if i >= 64 and e[-1] <= i - 32:
            return k[:32]


# ---------------------------------------------------------------- document

class PdfDocument:
    MAX_OBJECTS = 2_000_000

    def __init__(self, data):
        if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
            raise PdfError("Not a PDF")
        self.data = data
        self.xref = {}            # num -> ("off", offset) | ("stm", stream_num, index)
        self.trailer = {}
        self.cache = {}
        self.objstm_cache = {}
        self.decryptor = None
        self._resolving = set()
        try:
            self._read_xref_chain()
        except Exception:
            self.xref, self.trailer = {}, {}
        if not self.xref or "Root" not in self.trailer:
            self._scan()
        enc = self.trailer.get("Encrypt")
        if enc is not None:
            enc = self.resolve(enc, decrypt=False)
            ids = self.resolve(self.trailer.get("ID")) or [b""]
            first = ids[0] if isinstance(ids, list) and ids and isinstance(ids[0], bytes) else b""
            if isinstance(enc, dict) and str(enc.get("Filter", "Standard")) == "Standard":
                self.decryptor = _Decryptor(enc, first)
                if self.decryptor.key is None and int(enc.get("V", 0) or 0) < 4:
                    raise PdfError("Encrypted PDF (password required)")
            else:
                raise PdfError("Encrypted PDF with unsupported security handler")
            self.cache.clear()                      # objects parsed before the key existed
            self.objstm_cache.clear()

    # ------------------------------------------------------------ xref
    def _read_xref_chain(self):
        tail = self.data[-4096:]
        m = list(re.finditer(rb"startxref\s+(\d+)", tail))
        if not m:
            raise PdfError("no startxref")
        offset = int(m[-1].group(1))
        seen = set()
        while offset and offset not in seen and len(seen) < 100:
            seen.add(offset)
            trailer = self._read_xref_at(offset)
            for k, v in trailer.items():
                self.trailer.setdefault(k, v)
            if "XRefStm" in trailer:
                try:
                    self._read_xref_at(int(trailer["XRefStm"]))
                except Exception:
                    pass
            prev = trailer.get("Prev")
            offset = int(prev) if isinstance(prev, (int, float)) else 0

    def _read_xref_at(self, offset):
        d = self.data
        lex = Lexer(d, offset)
        lex.skip_ws()
        if d.startswith(b"xref", lex.pos):
            pos = lex.pos + 4
            while True:
                m = re.compile(rb"\s*(\d+)\s+(\d+)\s*[\r\n]+").match(d, pos)
                if not m:
                    break
                start, count = int(m.group(1)), int(m.group(2))
                pos = m.end()
                for i in range(count):
                    line = d[pos:pos + 20]
                    em = re.match(rb"\s*(\d{1,10})\s+(\d{1,5})\s+([nf])", line)
                    if not em:
                        break
                    pos += 20 if len(line) == 20 and line[-1:] in b"\r\n " else em.end() + 2
                    num = start + i
                    if em.group(3) == b"n" and num not in self.xref:
                        self.xref[num] = ("off", int(em.group(1)))
            t = d.find(b"trailer", pos)
            if t < 0:
                return {}
            lex = Lexer(d, t + 7)
            tr = lex.next()
            return tr if isinstance(tr, dict) else {}
        # xref stream
        obj = self._parse_indirect_at(offset)
        if not isinstance(obj, Stream) or str(obj.dict.get("Type")) != "XRef":
            raise PdfError("bad xref")
        sd = obj.dict
        data = self._decode_stream(obj, decrypt=False)
        w = [int(x) for x in sd.get("W", [1, 2, 1])]
        index = sd.get("Index") or [0, int(sd.get("Size", 0))]
        rec = sum(w)
        pos = 0
        for j in range(0, len(index) - 1, 2):
            start, count = int(index[j]), int(index[j + 1])
            for i in range(count):
                if pos + rec > len(data):
                    break
                fields, p = [], pos
                for width in w:
                    fields.append(int.from_bytes(data[p:p + width], "big") if width else None)
                    p += width
                pos += rec
                typ = 1 if w[0] == 0 else fields[0]
                num = start + i
                if num in self.xref:
                    continue
                if typ == 1:
                    self.xref[num] = ("off", fields[1])
                elif typ == 2:
                    self.xref[num] = ("stm", fields[1], fields[2])
        return dict(sd)

    def _scan(self):
        for m in re.finditer(rb"(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b", self.data):
            self.xref[int(m.group(1))] = ("off", m.start())
        for m in re.finditer(rb"trailer\s*<<", self.data):
            try:
                t = Lexer(self.data, m.end() - 2).next()
                if isinstance(t, dict):
                    self.trailer.update({k: v for k, v in t.items() if v is not None})
            except Exception:
                continue
        if "Root" not in self.trailer:
            for num, entry in list(self.xref.items()):
                try:
                    obj = self.get(num)
                except Exception:
                    continue
                if isinstance(obj, Stream) and str(obj.dict.get("Type")) == "XRef" and "Root" in obj.dict:
                    self.trailer.setdefault("Root", obj.dict["Root"])
                    self.trailer.setdefault("Info", obj.dict.get("Info"))
                    self.trailer.setdefault("Encrypt", obj.dict.get("Encrypt"))
                    self.trailer.setdefault("ID", obj.dict.get("ID"))
                elif isinstance(obj, dict) and str(obj.get("Type")) == "Catalog":
                    self.trailer.setdefault("Root", Ref(num, 0))
        # objects only reachable through object streams
        for num in list(self.xref):
            try:
                obj = self.get(num)
            except Exception:
                continue
            if isinstance(obj, Stream) and str(obj.dict.get("Type")) == "ObjStm":
                try:
                    for inner in self._objstm(num):
                        self.xref.setdefault(inner, ("stm", num, -1))
                except Exception:
                    continue
        self.trailer = {k: v for k, v in self.trailer.items() if v is not None}

    # ------------------------------------------------------------ objects
    def _parse_indirect_at(self, offset):
        d = self.data
        m = re.compile(rb"\s*(\d+)\s+(\d+)\s+obj\b").match(d, offset)
        if not m:
            # some writers have slightly wrong offsets: search nearby
            m = re.compile(rb"(\d+)\s+(\d+)\s+obj\b").search(d, max(0, offset - 64), offset + 128)
            if not m:
                raise PdfError(f"no object at {offset}")
        num, gen = int(m.group(1)), int(m.group(2))
        lex = Lexer(d, m.end())
        obj = lex.next()
        lex.skip_ws()
        if isinstance(obj, dict) and d.startswith(b"stream", lex.pos):
            start = lex.pos + 6
            if d[start:start + 2] == b"\r\n":
                start += 2
            elif d[start:start + 1] in (b"\n", b"\r"):
                start += 1
            length = obj.get("Length")
            if isinstance(length, Ref):
                try:
                    length = self.resolve(length)
                except Exception:
                    length = None
            raw = None
            if isinstance(length, int) and 0 <= length <= len(d) - start:
                after = d[start + length:start + length + 32].lstrip()
                if after.startswith(b"endstream"):
                    raw = d[start:start + length]
            if raw is None:
                end = d.find(b"endstream", start)
                if end < 0:
                    end = len(d)
                raw = d[start:end]
                if raw.endswith(b"\r\n"):
                    raw = raw[:-2]
                elif raw.endswith((b"\n", b"\r")):
                    raw = raw[:-1]
            return Stream(obj, raw, num, gen)
        return obj

    def _objstm(self, num):
        if num in self.objstm_cache:
            return self.objstm_cache[num]
        stm = self.get(num)
        if not isinstance(stm, Stream):
            raise PdfError("bad object stream")
        data = self._decode_stream(stm)
        n = int(stm.dict.get("N", 0))
        first = int(stm.dict.get("First", 0))
        lex = Lexer(data, 0, refs=False)
        pairs = []
        for _ in range(n):
            try:
                pairs.append((int(lex.next()), int(lex.next())))
            except (EOFError, TypeError, ValueError):
                break
        objs = {}
        for inner, off in pairs:
            try:
                objs[inner] = Lexer(data, first + off).next()
            except Exception:
                continue
        self.objstm_cache[num] = objs
        return objs

    def get(self, num):
        if num in self.cache:
            return self.cache[num]
        entry = self.xref.get(num)
        if entry is None:
            return None
        if num in self._resolving:
            return None
        self._resolving.add(num)
        try:
            if entry[0] == "off":
                obj = self._parse_indirect_at(entry[1])
                if self.decryptor and num != getattr(self, "_enc_num", -1):
                    obj = self._decrypt_obj(obj, num, 0)
            else:
                obj = self._objstm(entry[1]).get(num)
        finally:
            self._resolving.discard(num)
        if len(self.cache) < 200_000:
            self.cache[num] = obj
        return obj

    def _decrypt_obj(self, obj, num, gen):
        if isinstance(obj, bytes):
            return self.decryptor.decrypt(obj, num, gen)
        if isinstance(obj, Stream):
            if str(obj.dict.get("Type")) == "XRef":
                return obj
            obj.dict = self._decrypt_obj(obj.dict, num, gen)
            obj.raw = self.decryptor.decrypt(obj.raw, num, gen)
            return obj
        if isinstance(obj, dict):
            return {k: self._decrypt_obj(v, num, gen) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._decrypt_obj(v, num, gen) for v in obj]
        return obj

    def resolve(self, obj, decrypt=True):
        depth = 0
        while isinstance(obj, Ref) and depth < 32:
            if not decrypt:
                entry = self.xref.get(obj[0])
                if entry and entry[0] == "off":
                    self._enc_num = obj[0]
                    obj = self._parse_indirect_at(entry[1])
                    break
            obj = self.get(obj[0])
            depth += 1
        return obj

    def _decode_stream(self, stm, decrypt=True):
        d = stm.dict
        filters = self.resolve(d.get("Filter"))
        parms = self.resolve(d.get("DecodeParms") or d.get("DP"))
        if filters is None:
            filters = []
        elif not isinstance(filters, list):
            filters = [filters]
        if not isinstance(parms, list):
            parms = [parms] * len(filters)
        data = stm.raw
        for i, f in enumerate(filters):
            f = str(self.resolve(f))
            p = self.resolve(parms[i]) if i < len(parms) else None
            p = p if isinstance(p, dict) else {}
            if f in ("FlateDecode", "Fl"):
                data = _inflate(data)
            elif f in ("LZWDecode", "LZW"):
                data = _lzw(data, int(p.get("EarlyChange", 1)))
            elif f in ("ASCIIHexDecode", "AHx"):
                raw = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
                data = bytes.fromhex((raw + b"0" * (len(raw) % 2)).decode())
            elif f in ("ASCII85Decode", "A85"):
                data = _a85(data)
            elif f in ("RunLengthDecode", "RL"):
                data = _runlength(data)
            elif f in IMAGE_FILTERS or f == "Crypt":
                return data
            pred = int(p.get("Predictor", 1) or 1)
            if pred >= 10:
                data = _png_unpredict(data, int(p.get("Columns", 1)), int(p.get("Colors", 1)),
                                      int(p.get("BitsPerComponent", 8)))
            elif pred == 2 and int(p.get("BitsPerComponent", 8)) == 8:
                cols, colors = int(p.get("Columns", 1)), int(p.get("Colors", 1))
                row = cols * colors
                b = bytearray(data)
                for r0 in range(0, len(b), row):
                    for x in range(r0 + colors, min(r0 + row, len(b))):
                        b[x] = (b[x] + b[x - colors]) & 0xFF
                data = bytes(b)
        return data

    def stream_data(self, stm):
        return self._decode_stream(stm)

    # ------------------------------------------------------------ structure
    def catalog(self):
        root = self.resolve(self.trailer.get("Root"))
        return root if isinstance(root, dict) else {}

    def pages(self, limit=5000):
        out = []
        root = self.resolve(self.catalog().get("Pages"))
        seen = set()

        def walk(node, inherited, depth):
            if len(out) >= limit or depth > 64 or not isinstance(node, dict):
                return
            key = id(node)
            if key in seen:
                return
            seen.add(key)
            inh = dict(inherited)
            for k in ("Resources", "MediaBox", "Rotate"):
                if k in node:
                    inh[k] = node[k]
            kids = self.resolve(node.get("Kids"))
            if str(node.get("Type")) == "Page" or (kids is None and "Contents" in node):
                page = dict(node)
                for k, v in inh.items():
                    page.setdefault(k, v)
                out.append(page)
                return
            if isinstance(kids, list):
                for kid in kids:
                    walk(self.resolve(kid), inh, depth + 1)

        if isinstance(root, dict):
            walk(root, {}, 0)
        if not out:                                  # broken page tree: collect Page objects directly
            for num in sorted(self.xref):
                try:
                    obj = self.get(num)
                except Exception:
                    continue
                if isinstance(obj, dict) and str(obj.get("Type")) == "Page":
                    out.append(obj)
                    if len(out) >= limit:
                        break
        return out

    def info(self):
        info = self.resolve(self.trailer.get("Info"))
        out = {}
        if isinstance(info, dict):
            for k in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate"):
                v = self.resolve(info.get(k))
                if isinstance(v, bytes):
                    out[k] = decode_pdf_string(v)
                elif isinstance(v, str):
                    out[k] = str(v)
        meta = self.resolve(self.catalog().get("Metadata"))
        if isinstance(meta, Stream) and "Title" not in out:
            try:
                xmp = self.stream_data(meta).decode("utf-8", "replace")
                m = re.search(r"<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>", xmp, re.S)
                if m and m.group(1).strip():
                    out["Title"] = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            except Exception:
                pass
        return out


def decode_pdf_string(b):
    if b.startswith(b"\xfe\xff"):
        return b[2:].decode("utf-16-be", "replace")
    if b.startswith(b"\xff\xfe"):
        return b[2:].decode("utf-16-le", "replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    return b.decode("latin-1")


# ---------------------------------------------------------------- fonts

# Adobe glyph names that commonly appear in /Differences arrays.
_GLYPHS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "quoteright": "’", "quoteleft": "‘", "parenleft": "(",
    "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-", "minus": "−",
    "period": ".", "slash": "/", "colon": ":", "semicolon": ";", "less": "<", "equal": "=", "greater": ">",
    "question": "?", "at": "@", "bracketleft": "[", "backslash": "\\", "bracketright": "]",
    "asciicircum": "^", "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}",
    "asciitilde": "~", "bullet": "•", "endash": "–", "emdash": "—", "quotedblleft": "“",
    "quotedblright": "”", "quotesinglbase": "‚", "quotedblbase": "„", "ellipsis": "…", "fi": "fi",
    "fl": "fl", "ff": "ff", "ffi": "ffi", "ffl": "ffl", "dagger": "†", "daggerdbl": "‡", "trademark": "™",
    "copyright": "©", "registered": "®", "degree": "°", "section": "§", "paragraph": "¶", "cent": "¢",
    "sterling": "£", "yen": "¥", "Euro": "€", "euro": "€", "periodcentered": "·", "multiply": "×",
    "divide": "÷", "plusminus": "±", "nbspace": " ", "sfthyphen": "-", "dotlessi": "ı",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "germandbls": "ß", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
    "oslash": "ø", "Oslash": "Ø", "aring": "å", "Aring": "Å", "ccedilla": "ç", "Ccedilla": "Ç",
    "ntilde": "ñ", "Ntilde": "Ñ", "rupee": "₹", "rupeeindian": "₹",
}
_ACCENTS = {"acute": "́", "grave": "̀", "circumflex": "̂", "dieresis": "̈",
            "tilde": "̃", "caron": "̌", "cedilla": "̧", "ring": "̊"}


def glyph_to_unicode(name):
    name = str(name).split(".")[0]
    if name in _GLYPHS:
        return _GLYPHS[name]
    if len(name) == 1:
        return name
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4,})", name)
    if m:
        h = m.group(1)
        try:
            return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h) - len(h) % 4, 4))
        except ValueError:
            return ""
    m = re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ""
    for acc, mark in _ACCENTS.items():
        if name.endswith(acc) and len(name) == len(acc) + 1:
            import unicodedata
            return unicodedata.normalize("NFC", name[0] + mark)
    return ""


def _parse_cmap(text):
    """ToUnicode CMap -> (mapping bytes->str, code lengths)."""
    mapping, lengths = {}, set()
    for block in re.findall(r"begincodespacerange(.*?)endcodespacerange", text, re.S):
        for lo in re.findall(r"<([0-9A-Fa-f]+)>\s*<[0-9A-Fa-f]+>", block):
            lengths.add(len(lo) // 2)

    def u16(h):
        try:
            return bytes.fromhex(h if len(h) % 2 == 0 else h + "0").decode("utf-16-be", "replace")
        except ValueError:
            return ""

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[bytes.fromhex(src if len(src) % 2 == 0 else "0" + src)] = u16(dst)
            lengths.add((len(src) + 1) // 2)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)", block):
            nbytes = (len(lo) + 1) // 2
            lengths.add(nbytes)
            a, b = int(lo, 16), int(hi, 16)
            if b < a or b - a > 65535:
                continue
            if rest.startswith("["):
                for i, dst in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                    if a + i > b:
                        break
                    mapping[(a + i).to_bytes(nbytes, "big")] = u16(dst)
            else:
                dst = rest[1:-1]
                if not dst:
                    continue
                base = int(dst, 16)
                width = len(dst)
                for i in range(b - a + 1):
                    val = format(base + i, f"0{width}X")
                    mapping[(a + i).to_bytes(nbytes, "big")] = u16(val)
    return mapping, lengths or {1}


class FontDecoder:
    """Maps character codes of one font to Unicode and knows glyph widths (for word/line detection)."""

    def __init__(self, doc, font):
        self.map, self.lengths, self.table = {}, {1}, None
        subtype = str(font.get("Subtype"))
        self.cid = subtype == "Type0"
        if self.cid:
            self.lengths = {2}
        tu = doc.resolve(font.get("ToUnicode"))
        if isinstance(tu, Stream):
            try:
                self.map, lengths = _parse_cmap(doc.stream_data(tu).decode("latin-1"))
                self.lengths = lengths
            except Exception:
                self.map = {}
        if not self.cid:
            self.table = self._simple_encoding(doc, font)
        # widths, in text-space units per unit of font size
        self.widths, self.scale, self.default = {}, 0.001, 500.0
        try:
            self._load_widths(doc, font, subtype)
        except Exception:
            pass

    def _load_widths(self, doc, font, subtype):
        if subtype == "Type3":
            fm = doc.resolve(font.get("FontMatrix"))
            if isinstance(fm, list) and fm and isinstance(fm[0], (int, float)):
                self.scale = abs(float(fm[0])) or 0.001
        if self.cid:
            desc = doc.resolve(font.get("DescendantFonts"))
            desc = doc.resolve(desc[0]) if isinstance(desc, list) and desc else {}
            if not isinstance(desc, dict):
                return
            self.default = float(doc.resolve(desc.get("DW", 1000)) or 1000)
            w = doc.resolve(desc.get("W")) or []
            i = 0
            while i < len(w) - 1:
                first = doc.resolve(w[i])
                nxt = doc.resolve(w[i + 1])
                if isinstance(nxt, list):
                    for j, val in enumerate(nxt):
                        val = doc.resolve(val)
                        if isinstance(val, (int, float)):
                            self.widths[int(first) + j] = float(val)
                    i += 2
                elif i + 2 < len(w):
                    last, val = int(nxt), doc.resolve(w[i + 2])
                    if isinstance(val, (int, float)) and 0 <= last - int(first) <= 65535:
                        for c in range(int(first), last + 1):
                            self.widths[c] = float(val)
                    i += 3
                else:
                    break
            return
        first = int(doc.resolve(font.get("FirstChar", 0)) or 0)
        widths = doc.resolve(font.get("Widths")) or []
        for j, val in enumerate(widths if isinstance(widths, list) else []):
            val = doc.resolve(val)
            if isinstance(val, (int, float)):
                self.widths[first + j] = float(val)
        fd = doc.resolve(font.get("FontDescriptor"))
        if isinstance(fd, dict) and isinstance(doc.resolve(fd.get("MissingWidth")), (int, float)) and fd.get("MissingWidth"):
            self.default = float(doc.resolve(fd["MissingWidth"]))
        elif self.widths:
            vals = sorted(v for v in self.widths.values() if v > 0)
            self.default = vals[len(vals) // 2] if vals else 500.0

    @staticmethod
    def _simple_encoding(doc, font):
        enc = doc.resolve(font.get("Encoding"))
        base = "WinAnsiEncoding"
        diffs = None
        if isinstance(enc, str):
            base = str(enc)
        elif isinstance(enc, dict):
            base = str(enc.get("BaseEncoding", "WinAnsiEncoding"))
            diffs = doc.resolve(enc.get("Differences"))
        codec = {"MacRomanEncoding": "mac_roman"}.get(base, "cp1252")
        table = [bytes([i]).decode(codec, "replace") if i >= 32 else "" for i in range(256)]
        if base == "StandardEncoding":
            table[0x27], table[0x60] = "’", "‘"
        if isinstance(diffs, list):
            code = 0
            for item in diffs:
                if isinstance(item, (int, float)):
                    code = int(item)
                elif isinstance(item, str):
                    if 0 <= code < 256:
                        u = glyph_to_unicode(item)
                        if u:
                            table[code] = u
                    code += 1
        return table

    def codes(self, raw):
        """[(code, text)] for a shown string."""
        out, i, n = [], 0, len(raw)
        if self.map:
            lens = sorted(self.lengths)
            while i < n:
                for L in lens:
                    chunk = raw[i:i + L]
                    if chunk in self.map:
                        out.append((int.from_bytes(chunk, "big"), self.map[chunk]))
                        i += L
                        break
                else:
                    if self.table is not None:
                        out.append((raw[i], self.table[raw[i]]))
                        i += 1
                    else:
                        L = max(lens)
                        out.append((int.from_bytes(raw[i:i + L], "big"), ""))
                        i += L
            return out
        if self.cid:                    # glyph ids without a ToUnicode map cannot be turned into text
            return [(int.from_bytes(raw[j:j + 2], "big"), "") for j in range(0, n - 1, 2)]
        return [(b, self.table[b]) for b in raw]

    def width(self, code):
        return self.widths.get(code, self.default) * self.scale


def _content_bytes(doc, contents):
    contents = doc.resolve(contents)
    parts = contents if isinstance(contents, list) else [contents]
    out = []
    for c in parts:
        c = doc.resolve(c)
        if isinstance(c, Stream):
            try:
                out.append(doc.stream_data(c))
            except Exception:
                continue
    return b"\n".join(out)


def _mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _nums(stack, n):
    vals = stack[-n:]
    if len(vals) < n or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return None
    return [float(v) for v in vals]


class _PageText:
    """Content-stream interpreter that tracks text and graphics matrices to place spaces and line breaks."""

    def __init__(self, doc, font_cache, images):
        self.doc, self.font_cache, self.images = doc, font_cache, images
        self.out = []
        self.last_end = None            # (x, y, height) in device space after the previous shown string

    def _fonts(self, resources):
        fonts = {}
        fd = self.doc.resolve(resources.get("Font")) if isinstance(resources, dict) else None
        if isinstance(fd, dict):
            for name, ref in fd.items():
                key = ref if isinstance(ref, Ref) else id(ref)
                if key not in self.font_cache:
                    f = self.doc.resolve(ref)
                    try:
                        self.font_cache[key] = FontDecoder(self.doc, f) if isinstance(f, dict) else None
                    except Exception:
                        self.font_cache[key] = None
                fonts[name] = self.font_cache[key]
        return fonts

    def _newline(self):
        if self.out and not self.out[-1].endswith("\n"):
            self.out.append("\n")

    def _space(self):
        if self.out and not self.out[-1].endswith((" ", "\n")):
            self.out.append(" ")

    def run(self, data, resources, ctm=_IDENTITY, depth=0):
        if depth > 8:
            return "".join(self.out)
        doc = self.doc
        resources = doc.resolve(resources) if resources is not None else {}
        resources = resources if isinstance(resources, dict) else {}
        fonts = self._fonts(resources)
        xobjs = doc.resolve(resources.get("XObject"))
        xobjs = xobjs if isinstance(xobjs, dict) else {}
        lex = Lexer(data, 0, refs=False)
        stack, gstack = [], []
        font, fs, tc, tw, th, tl = None, 0.0, 0.0, 0.0, 1.0, 0.0
        tm = tlm = _IDENTITY

        def show(raw):
            nonlocal tm
            if not isinstance(raw, bytes):
                return
            m = _mul(tm, ctm)
            x, y = m[4], m[5]
            height = abs(fs) * ((m[2] ** 2 + m[3] ** 2) ** 0.5) or 1.0
            if self.last_end is not None:
                lx, ly, lh = self.last_end
                ref_h = max(height, lh, 1e-6)
                if abs(y - ly) > 0.5 * ref_h:
                    self._newline()
                elif x - lx > 0.15 * ref_h or x - lx < -2.0 * ref_h:
                    self._space()
            codes = font.codes(raw) if font else [(b, chr(b)) for b in raw]
            text = "".join(t for _, t in codes)
            if text:
                self.out.append(text)
            if font:
                adv = 0.0
                single = not font.cid
                for code, _t in codes:
                    adv += font.width(code) * fs + tc + (tw if single and code == 32 else 0.0)
                adv *= th
            else:
                adv = 0.5 * fs * len(codes)
            tm = _mul((1.0, 0.0, 0.0, 1.0, adv, 0.0), tm)
            m = _mul(tm, ctm)
            self.last_end = (m[4], m[5], height)

        while True:
            try:
                tok = lex.next()
            except EOFError:
                break
            except Exception:
                lex.pos += 1
                continue
            if not isinstance(tok, Op):
                stack.append(tok)
                if len(stack) > 64:
                    del stack[:32]
                continue
            op = str(tok)
            if op == "Tj" and stack:
                show(stack[-1])
            elif op == "TJ" and stack and isinstance(stack[-1], list):
                for item in stack[-1]:
                    if isinstance(item, bytes):
                        show(item)
                    elif isinstance(item, (int, float)):
                        tm = _mul((1.0, 0.0, 0.0, 1.0, -float(item) / 1000.0 * fs * th, 0.0), tm)
            elif op in ("'", '"'):
                tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
                tm = tlm
                if op == '"' and len(stack) >= 3:
                    v = _nums(stack[:-1], 2)
                    if v:
                        tw, tc = v
                if stack:
                    show(stack[-1])
            elif op == "Tf" and len(stack) >= 2:
                font = fonts.get(str(stack[-2]))
                fs = float(stack[-1]) if isinstance(stack[-1], (int, float)) else fs
            elif op in ("Td", "TD"):
                v = _nums(stack, 2)
                if v:
                    if op == "TD":
                        tl = -v[1]
                    tlm = _mul((1.0, 0.0, 0.0, 1.0, v[0], v[1]), tlm)
                    tm = tlm
            elif op == "Tm":
                v = _nums(stack, 6)
                if v:
                    tlm = tm = tuple(v)
            elif op == "T*":
                tlm = _mul((1.0, 0.0, 0.0, 1.0, 0.0, -tl), tlm)
                tm = tlm
            elif op == "BT":
                tm = tlm = _IDENTITY
            elif op == "Tc":
                v = _nums(stack, 1)
                tc = v[0] if v else tc
            elif op == "Tw":
                v = _nums(stack, 1)
                tw = v[0] if v else tw
            elif op == "Tz":
                v = _nums(stack, 1)
                th = v[0] / 100.0 if v else th
            elif op == "TL":
                v = _nums(stack, 1)
                tl = v[0] if v else tl
            elif op == "cm":
                v = _nums(stack, 6)
                if v:
                    ctm = _mul(tuple(v), ctm)
            elif op == "q":
                if len(gstack) < 64:
                    gstack.append(ctm)
            elif op == "Q":
                if gstack:
                    ctm = gstack.pop()
            elif op == "Do" and stack:
                xo = doc.resolve(xobjs.get(str(stack[-1])))
                if isinstance(xo, Stream):
                    sub = str(xo.dict.get("Subtype"))
                    if sub == "Form":
                        fm = doc.resolve(xo.dict.get("Matrix"))
                        sub_ctm = _mul(tuple(float(x) for x in fm), ctm) if isinstance(fm, list) and len(fm) == 6 else ctm
                        try:
                            self.run(doc.stream_data(xo), xo.dict.get("Resources", resources), sub_ctm, depth + 1)
                        except Exception:
                            pass
                    elif sub == "Image" and len(self.images) < 200:
                        self.images.append(xo)
            elif op == "ID":                        # inline image: skip binary data up to EI
                m = re.compile(rb"\sEI(?=\s|$)").search(data, lex.pos)
                lex.pos = m.end() if m else len(data)
            if op != "BI":
                stack.clear()
        return "".join(self.out)


def extract_pdf(data, max_pages=3000, max_chars=4_000_000):
    """Return {"pages": [text...], "metadata": {...}, "images": [(page_no, Stream)], "doc": PdfDocument}."""
    doc = PdfDocument(data)
    pages = doc.pages(max_pages)
    texts, images = [], []
    font_cache = {}
    total = 0
    for no, page in enumerate(pages, 1):
        page_images = []
        try:
            content = _content_bytes(doc, page.get("Contents"))
            pt = _PageText(doc, font_cache, page_images)
            text = pt.run(content, page.get("Resources"))
        except Exception:
            text = ""
        text = re.sub(r"[ \t]+", " ", text).strip()
        texts.append(text)
        images.extend((no, img) for img in page_images[:20])
        total += len(text)
        if total > max_chars:
            break
    meta = {}
    try:
        meta = doc.info()
    except Exception:
        pass
    meta["page_count"] = len(pages)
    meta["encrypted"] = doc.decryptor is not None
    return {"pages": texts, "metadata": meta, "images": images, "doc": doc}


def image_for_ocr(doc, stm):
    """Convert a PDF image XObject to (bytes, file_suffix) an OCR engine can read, or None."""
    d = stm.dict
    filters = doc.resolve(d.get("Filter"))
    filters = filters if isinstance(filters, list) else ([filters] if filters else [])
    names = [str(doc.resolve(f)) for f in filters]
    width, height = int(doc.resolve(d.get("Width", 0)) or 0), int(doc.resolve(d.get("Height", 0)) or 0)
    if width < 50 or height < 20:
        return None
    if names and names[-1] in ("DCTDecode", "DCT"):
        data = doc._decode_stream(stm) if len(names) > 1 else stm.raw
        return data, ".jpg"
    if names and names[-1] == "JPXDecode":
        return stm.raw, ".jp2"
    if names and names[-1] in ("CCITTFaxDecode", "CCF"):
        parms = doc.resolve(d.get("DecodeParms") or {})
        if isinstance(parms, list):
            parms = doc.resolve(parms[-1]) or {}
        return _ccitt_tiff(stm.raw if len(names) == 1 else doc._decode_stream(stm), width, height, parms), ".tif"
    if names and names[-1] == "JBIG2Decode":
        return None
    try:
        raw = doc.stream_data(stm)
    except Exception:
        return None
    bpc = int(doc.resolve(d.get("BitsPerComponent", 8)) or 8)
    cs = doc.resolve(d.get("ColorSpace"))
    comps = 1
    if isinstance(cs, Name) and str(cs) in ("DeviceRGB", "CalRGB"):
        comps = 3
    elif isinstance(cs, list) and cs and str(cs[0]) == "ICCBased":
        prof = doc.resolve(cs[1]) if len(cs) > 1 else None
        comps = int(prof.dict.get("N", 3)) if isinstance(prof, Stream) else 3
    elif isinstance(cs, Name) and str(cs) == "DeviceCMYK":
        return None
    if bpc == 1:
        row = (width + 7) // 8
        if len(raw) < row * height:
            return None
        inverted = bytes(b ^ 0xFF for b in raw[:row * height])       # PDF 1=white, PBM 1=black
        return b"P4\n%d %d\n" % (width, height) + inverted, ".pbm"
    if bpc == 8 and comps in (1, 3):
        need = width * height * comps
        if len(raw) < need:
            return None
        magic = b"P5" if comps == 1 else b"P6"
        return magic + b"\n%d %d\n255\n" % (width, height) + raw[:need], ".pnm" if comps == 3 else ".pgm"
    return None


def _ccitt_tiff(data, width, height, parms):
    """Wrap raw CCITT G3/G4 data in a minimal TIFF container."""
    k = int(parms.get("K", 0) or 0) if isinstance(parms, dict) else 0
    black1 = bool(parms.get("BlackIs1", False)) if isinstance(parms, dict) else False
    compression = 4 if k < 0 else 3
    entries = [
        (256, 4, 1, width), (257, 4, 1, height), (258, 3, 1, 1), (259, 3, 1, compression),
        (262, 3, 1, 1 if black1 else 0), (273, 4, 1, 0), (277, 3, 1, 1), (278, 4, 1, height),
        (279, 4, 1, len(data)),
    ]
    if compression == 3:
        entries.append((292, 4, 1, 1 if k > 0 else 0))
    entries.sort()
    ifd_off = 8
    data_off = ifd_off + 2 + 12 * len(entries) + 4
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_off))
    out += struct.pack("<H", len(entries))
    for tag, typ, count, value in entries:
        if tag == 273:
            value = data_off
        if typ == 3:
            out += struct.pack("<HHIHH", tag, typ, count, value, 0)
        else:
            out += struct.pack("<HHII", tag, typ, count, value)
    out += struct.pack("<I", 0)
    return bytes(out) + data
