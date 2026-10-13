"""On-disk inverted index segments (OwnSearch's own format, written from scratch).

A segment is immutable once written. Files per segment ``<name>``:

  <name>.docs   header + global doc ids (int64) + per-field lengths (uint32 x NF) + static score (uint8)
  <name>.post   per term: zlib( doc-num deltas uint32[n] | field tfs uint8[NF*n] (field-major)
                               | position offsets uint32[n+1] )  [+ zlib(champion doc nums uint32[k])]
  <name>.pos    per term, per doc: varint delta-encoded token positions
  <name>.terms  sorted term dictionary, in blocks of BLOCK_TERMS entries
  <name>.tix    JSON sparse index: first term and byte offset of every block

Local doc numbers inside a segment are ordered by global doc id, so a doc can be located by bisection.
Deletions are kept outside the segment as a bitmap file referenced from the manifest.
"""
import array
import bisect
import heapq
import json
import mmap
import os
import struct
import sys
import zlib
from itertools import accumulate

FIELDS = ("title", "headings", "url", "anchor", "body", "meta")
NF = len(FIELDS)
F_TITLE, F_HEAD, F_URL, F_ANCHOR, F_BODY, F_META = range(NF)
POSITION_GAP = 64                # gap between fields so phrases never span two fields
BLOCK_TERMS = 64
CHAMP_MIN_DF = 4096              # terms with at least this df get a champion (top-k) list
CHAMP_K = 1000
CHAMP_WEIGHTS = (3.0, 1.8, 1.2, 2.0, 1.0, 0.0)

_ENTRY = struct.Struct("<IQIQIQI")   # df, post_off, post_len, pos_off, pos_len, champ_off, champ_len
_TLEN = struct.Struct("<H")
_DOCS_HDR = struct.Struct("<4sII")
_LITTLE = sys.byteorder == "little"


def _arr(code, data=b""):
    a = array.array(code)
    if data:
        a.frombytes(data)
        if not _LITTLE:
            a.byteswap()
    return a


def _tobytes(a):
    if not _LITTLE:
        a = array.array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


def _varint(d):
    out = bytearray()
    while d >= 0x80:
        out.append((d & 0x7F) | 0x80)
        d >>= 7
    out.append(d)
    return bytes(out)


_VARINT = [_varint(d) for d in range(1 << 14)]      # precomputed encodings for deltas < 16384


def encode_positions(positions):
    if len(positions) == 1:
        d = positions[0]
        return _VARINT[d] if d < 16384 else _varint(d)
    prev = 0
    parts = []
    for p in positions:
        d = p - prev
        prev = p
        parts.append(_VARINT[d] if d < 16384 else _varint(d))
    return b"".join(parts)


def decode_positions(buf):
    res = []
    cur = val = shift = 0
    for b in buf:
        val |= (b & 0x7F) << shift
        if b & 0x80:
            shift += 7
        else:
            cur += val
            res.append(cur)
            val = shift = 0
    return res


def _fsync_replace(tmp, final):
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, final)


class Postings:
    """Decoded postings of one term in one segment."""
    __slots__ = ("docs", "tfs", "posoff", "pos_base", "n")

    def __init__(self, docs, tfs, posoff, pos_base):
        self.docs, self.tfs, self.posoff, self.pos_base, self.n = docs, tfs, posoff, pos_base, len(docs)

    def find(self, local):
        i = bisect.bisect_left(self.docs, local)
        return i if i < self.n and self.docs[i] == local else -1

    def tf(self, field, i):
        return self.tfs[field * self.n + i]

    def nbytes(self):
        return 64 + self.n * (8 + 4 + NF) + 4 * (self.n + 1)


class SegmentFileWriter:
    """Low level writer: terms must be added in sorted order."""

    def __init__(self, directory, name, docids, lengths, static):
        self.dir, self.name = str(directory), name
        self.docids, self.lengths, self.static = docids, lengths, static
        n = max(1, len(docids))
        self.avg = [max(1.0, sum(lengths[f::NF]) / n) for f in range(NF)]
        self._paths = {ext: os.path.join(self.dir, f"{name}.{ext}") for ext in ("post", "pos", "terms", "tix", "docs")}
        self._post = open(self._paths["post"] + ".tmp", "wb")
        self._pos = open(self._paths["pos"] + ".tmp", "wb")
        self._terms = open(self._paths["terms"] + ".tmp", "wb")
        self._blocks = []
        self._count = 0
        self._post_off = self._pos_off = self._terms_off = 0
        self.term_count = 0

    def _champions(self, locals_, tf_rows):
        lengths, avg, static = self.lengths, self.avg, self.static
        def weight(j):
            loc = locals_[j]
            base = loc * NF
            w = 0.0
            for f in range(NF - 1):
                tf = tf_rows[j][f]
                if tf:
                    w += CHAMP_WEIGHTS[f] * tf / (0.25 + 0.75 * lengths[base + f] / avg[f])
            return w * (0.6 + static[loc] / 255.0)
        best = heapq.nlargest(CHAMP_K, range(len(locals_)), key=weight)
        return sorted(locals_[j] for j in best)

    def add_term(self, term, locals_, tf_rows, pos_chunks):
        n = len(locals_)
        if n == 0:
            return
        deltas = array.array("I", [locals_[0]] + [b - a for a, b in zip(locals_, locals_[1:])])
        parts = []
        for f in range(NF):
            try:
                parts.append(bytes([row[f] for row in tf_rows]))
            except ValueError:                       # a tf above 255: clamp (BM25 saturates long before)
                parts.append(bytes([min(255, row[f]) for row in tf_rows]))
        tfs = b"".join(parts)
        posoff = array.array("I", [0])
        posoff.extend(accumulate(len(c) for c in pos_chunks))
        pos_blob = b"".join(pos_chunks)
        blob = zlib.compress(_tobytes(deltas) + tfs + _tobytes(posoff), 3)
        post_off = self._post_off
        self._post.write(blob)
        self._post_off += len(blob)
        champ_off = champ_len = 0
        if n >= CHAMP_MIN_DF:
            champ = zlib.compress(_tobytes(array.array("I", self._champions(locals_, tf_rows))), 6)
            champ_off, champ_len = self._post_off, len(champ)
            self._post.write(champ)
            self._post_off += champ_len
        pos_off = self._pos_off
        self._pos.write(pos_blob)
        self._pos_off += len(pos_blob)
        tb = term.encode("utf-8")
        if self._count % BLOCK_TERMS == 0:
            self._blocks.append([term, self._terms_off])
        entry = _TLEN.pack(len(tb)) + tb + _ENTRY.pack(n, post_off, len(blob), pos_off, len(pos_blob), champ_off, champ_len)
        self._terms.write(entry)
        self._terms_off += len(entry)
        self._count += 1
        self.term_count += 1

    def finish(self):
        for f in (self._post, self._pos, self._terms):
            f.flush()
            os.fsync(f.fileno())
            f.close()
        with open(self._paths["tix"] + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"blocks": self._blocks, "terms": self.term_count}, f, ensure_ascii=False)
        with open(self._paths["docs"] + ".tmp", "wb") as f:
            f.write(_DOCS_HDR.pack(b"OSD1", len(self.docids), NF))
            f.write(_tobytes(self.docids))
            f.write(_tobytes(self.lengths))
            f.write(bytes(self.static))
        for ext in ("post", "pos", "terms", "tix", "docs"):
            _fsync_replace(self._paths[ext] + ".tmp", self._paths[ext])
        return {"name": self.name, "n_docs": len(self.docids), "terms": self.term_count,
                "field_sums": [int(sum(self.lengths[f::NF])) for f in range(NF)]}

    def abort(self):
        for f in (self._post, self._pos, self._terms):
            try:
                f.close()
            except OSError:
                pass
        for p in self._paths.values():
            for cand in (p, p + ".tmp"):
                try:
                    os.unlink(cand)
                except OSError:
                    pass


class SegmentBuilder:
    """Accumulates analysed documents in memory and writes them as one segment."""

    def __init__(self):
        self.docs = {}          # doc_id -> (fields dict, static byte)
        self.tokens = 0

    def __len__(self):
        return len(self.docs)

    def add(self, doc_id, fields, static=128):
        self.docs[int(doc_id)] = (fields, max(0, min(255, int(static))))
        self.tokens += sum(len(v) for v in fields.values())

    def write(self, directory, name):
        order = sorted(self.docs)
        docids = array.array("q", order)
        lengths = array.array("I")
        static = bytearray()
        postings = {}   # term -> [locals, tf_rows, positions lists]
        for local, did in enumerate(order):
            fields, st = self.docs[did]
            static.append(st)
            per_term = {}
            pos = 0
            for f, fname in enumerate(FIELDS):
                toks = fields.get(fname) or ()
                lengths.append(len(toks))
                for tok in toks:
                    rec = per_term.get(tok)
                    if rec is None:
                        rec = per_term[tok] = [[0] * NF, []]
                    rec[0][f] += 1
                    if f != F_META:
                        rec[1].append(pos)
                    pos += 1
                pos += POSITION_GAP
            for tok, (tfs, plist) in per_term.items():
                p = postings.get(tok)
                if p is None:
                    p = postings[tok] = ([], [], [])
                p[0].append(local)
                p[1].append(tfs)
                p[2].append(encode_positions(plist))
        writer = SegmentFileWriter(directory, name, docids, lengths, static)
        try:
            for term in sorted(postings):
                locals_, rows, chunks = postings[term]
                writer.add_term(term, locals_, rows, chunks)
            return writer.finish()
        except BaseException:
            writer.abort()
            raise


def _map(path):
    size = os.path.getsize(path)
    if size == 0:
        return b""
    with open(path, "rb") as f:
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)


class SegmentReader:
    def __init__(self, directory, name, del_file=None):
        self.dir, self.name = str(directory), name
        base = os.path.join(self.dir, name)
        with open(base + ".docs", "rb") as f:
            raw = f.read()
        magic, n, nf = _DOCS_HDR.unpack_from(raw, 0)
        if magic != b"OSD1" or nf != NF:
            raise ValueError(f"Bad segment header in {name}")
        o = _DOCS_HDR.size
        self.n = n
        self.docids = _arr("q", raw[o:o + 8 * n])
        o += 8 * n
        self.lengths = _arr("I", raw[o:o + 4 * n * NF])
        o += 4 * n * NF
        self.static = raw[o:o + n]
        with open(base + ".tix", encoding="utf-8") as f:
            tix = json.load(f)
        self.block_terms = [b[0] for b in tix["blocks"]]
        self.block_offsets = [b[1] for b in tix["blocks"]]
        self.term_count = tix.get("terms", 0)
        self.post = _map(base + ".post")
        self.pos = _map(base + ".pos")
        self.terms = _map(base + ".terms")
        self.deleted = bytearray((n + 7) // 8)
        if del_file:
            with open(os.path.join(self.dir, del_file), "rb") as f:
                data = f.read()
            self.deleted[:len(data)] = data[:len(self.deleted)]
        self.n_deleted = sum(bin(b).count("1") for b in self.deleted)
        self.field_sums = [sum(self.lengths[f::NF]) for f in range(NF)]

    # ---------------------------------------------------------------- docs
    def is_deleted(self, local):
        return (self.deleted[local >> 3] >> (local & 7)) & 1

    def local_of(self, doc_id):
        i = bisect.bisect_left(self.docids, doc_id)
        return i if i < self.n and self.docids[i] == doc_id else None

    @property
    def live(self):
        return self.n - self.n_deleted

    # ---------------------------------------------------------------- terms
    def _parse_entry(self, off):
        (tl,) = _TLEN.unpack_from(self.terms, off)
        off += 2
        term = bytes(self.terms[off:off + tl]).decode("utf-8")
        off += tl
        entry = _ENTRY.unpack_from(self.terms, off)
        return term, entry, off + _ENTRY.size

    def lookup(self, term):
        if not self.block_terms:
            return None
        b = bisect.bisect_right(self.block_terms, term) - 1
        if b < 0:
            return None
        off = self.block_offsets[b]
        end = self.block_offsets[b + 1] if b + 1 < len(self.block_offsets) else len(self.terms)
        while off < end:
            t, entry, off = self._parse_entry(off)
            if t == term:
                return entry
            if t > term:
                return None
        return None

    def iter_terms(self):
        off, end = 0, len(self.terms)
        while off < end:
            t, entry, off = self._parse_entry(off)
            yield t, entry

    def decode(self, entry):
        df, post_off, post_len, pos_off, _pos_len, _co, _cl = entry
        raw = zlib.decompress(self.post[post_off:post_off + post_len])
        n = df
        docs = list(accumulate(_arr("I", raw[:4 * n])))
        tfs = raw[4 * n:4 * n + NF * n]
        posoff = _arr("I", raw[4 * n + NF * n:])
        return Postings(docs, tfs, posoff, pos_off)

    def champions(self, entry):
        _df, _po, _pl, _so, _sl, champ_off, champ_len = entry
        if not champ_len:
            return None
        return _arr("I", zlib.decompress(self.post[champ_off:champ_off + champ_len])).tolist()

    def positions(self, postings, i):
        a = postings.pos_base + postings.posoff[i]
        b = postings.pos_base + postings.posoff[i + 1]
        return decode_positions(self.pos[a:b])

    def position_bytes(self, postings, i):
        a = postings.pos_base + postings.posoff[i]
        b = postings.pos_base + postings.posoff[i + 1]
        return bytes(self.pos[a:b])

    def close(self):
        for m in (self.post, self.pos, self.terms):
            if isinstance(m, mmap.mmap):
                try:
                    m.close()
                except (BufferError, ValueError):
                    pass


def merge_segments(readers, directory, name):
    """Merge live documents of several segments into a new one (postings-level, no re-analysis)."""
    live = []
    for ri, r in enumerate(readers):
        for local in range(r.n):
            if not r.is_deleted(local):
                live.append((r.docids[local], ri, local))
    live.sort()
    remap = [array.array("i", [-1]) * r.n for r in readers]
    docids = array.array("q")
    lengths = array.array("I")
    static = bytearray()
    seen = set()
    for did, ri, local in live:
        if did in seen:                 # defensive: keep only one live copy of a doc
            continue
        seen.add(did)
        remap[ri][local] = len(docids)
        docids.append(did)
        r = readers[ri]
        lengths.extend(r.lengths[local * NF:(local + 1) * NF])
        static.append(r.static[local])
    writer = SegmentFileWriter(directory, name, docids, lengths, static)
    try:
        heap = []
        iters = [r.iter_terms() for r in readers]
        for ri, it in enumerate(iters):
            first = next(it, None)
            if first:
                heap.append((first[0], ri, first[1]))
        heapq.heapify(heap)
        while heap:
            term = heap[0][0]
            group = []
            while heap and heap[0][0] == term:
                _, ri, entry = heapq.heappop(heap)
                group.append((ri, entry))
                nxt = next(iters[ri], None)
                if nxt:
                    heapq.heappush(heap, (nxt[0], ri, nxt[1]))
            items = []
            for ri, entry in group:
                r = readers[ri]
                p = r.decode(entry)
                rm = remap[ri]
                for i, old in enumerate(p.docs):
                    new = rm[old]
                    if new < 0:
                        continue
                    items.append((new, tuple(p.tfs[f * p.n + i] for f in range(NF)), r.position_bytes(p, i)))
            if items:
                if len(group) > 1:
                    items.sort(key=lambda x: x[0])
                writer.add_term(term, [x[0] for x in items], [x[1] for x in items], [x[2] for x in items])
        return writer.finish()
    except BaseException:
        writer.abort()
        raise
