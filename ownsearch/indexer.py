"""Index manager (segments + manifest + deletions + merging) and the incremental indexer.

Durability model
  * Segment files are written to ``*.tmp``, fsync'd and renamed; the manifest is replaced atomically last.
  * The manifest records ``committed_seq``: every document change with a higher seq is (re)applied on the
    next indexer run, so a crash at any point loses nothing.
  * Only one writer at a time (``fcntl.flock`` on ``write.lock``); any number of reader processes, which
    pick up new manifests automatically.
"""
import json
import math
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:          # non-POSIX: fall back to an in-process lock only
    fcntl = None

from .segments import FIELDS, NF, SegmentBuilder, SegmentReader, merge_segments
from .store import _decompress
from .textproc import analyze, exact_tokens, ngrams, tokenize
from .transliterate import key as phonetic_key
from .util import file_extension, host_suffixes

META = "\x01"                 # prefix for hidden filter terms (site:, type:, ext:, lang:)


class SizedLRU:
    """Thread-safe LRU bounded by approximate bytes."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.bytes = 0
        self.data = OrderedDict()
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            item = self.data.get(key)
            if item is None:
                self.misses += 1
                return None
            self.data.move_to_end(key)
            self.hits += 1
            return item[0]

    def put(self, key, value, size):
        if size > self.max_bytes // 4:
            return
        with self.lock:
            old = self.data.pop(key, None)
            if old:
                self.bytes -= old[1]
            self.data[key] = (value, size)
            self.bytes += size
            while self.bytes > self.max_bytes and self.data:
                _, (_, s) = self.data.popitem(last=False)
                self.bytes -= s


class Snapshot:
    """An immutable view of the index used for the whole duration of one query."""

    def __init__(self, readers, manifest, cache):
        self.readers = readers
        self.manifest = manifest
        self.generation = manifest.get("generation", 0)
        self.cache = cache
        self.N = sum(r.live for r in readers)
        total = sum(r.n for r in readers) or 1
        self.avg = [max(1.0, sum(r.field_sums[f] for r in readers) / total) for f in range(NF)]
        self._entries = {}
        self._lock = threading.Lock()

    def entry(self, ri, term):
        key = (ri, term)
        e = self._entries.get(key, False)
        if e is False:
            e = self.readers[ri].lookup(term)
            with self._lock:
                self._entries[key] = e
        return e

    def df(self, term):
        return sum(e[0] for ri in range(len(self.readers)) if (e := self.entry(ri, term)))

    def idf(self, term):
        df = self.df(term)
        if not df:
            return 0.0
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def postings(self, ri, term):
        e = self.entry(ri, term)
        if not e:
            return None
        r = self.readers[ri]
        key = (r.name, term)
        p = self.cache.get(key)
        if p is None:
            p = r.decode(e)
            self.cache.put(key, p, p.nbytes())
        return p

    def champions(self, ri, term):
        e = self.entry(ri, term)
        return self.readers[ri].champions(e) if e else None


class IndexManager:
    MANIFEST = "manifest.json"

    def __init__(self, directory, merge_factor=8, cache_mb=256):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.merge_factor = max(2, int(merge_factor))
        self.cache = SizedLRU(int(cache_mb) * 1024 * 1024)
        self._thread_lock = threading.RLock()
        self._load_lock = threading.Lock()
        self._snapshot = None
        self.manifest = None
        self._mtime = None
        self._last_check = 0.0
        self._load()

    # ---------------------------------------------------------------- manifest
    @property
    def manifest_path(self):
        return self.dir / self.MANIFEST

    def _read_manifest(self):
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"generation": 0, "segments": [], "committed_seq": 0, "next_seg": 1}

    def _write_manifest(self, m):
        tmp = self.dir / (self.MANIFEST + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.manifest_path)
        try:
            fd = os.open(self.dir, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass

    def _load(self):
        with self._load_lock:
            last_err = None
            for _ in range(20):
                try:
                    mtime = self.manifest_path.stat().st_mtime_ns
                except FileNotFoundError:
                    mtime = None
                m = self._read_manifest()
                try:
                    readers = [SegmentReader(self.dir, s["name"], s.get("del_file")) for s in m["segments"]]
                except (FileNotFoundError, ValueError) as e:   # a concurrent writer replaced files; retry
                    last_err = e
                    time.sleep(0.05)
                    continue
                self.manifest = m
                self._mtime = mtime
                self._snapshot = Snapshot(readers, m, self.cache)
                return
            raise RuntimeError(f"Could not open index: {last_err}")

    def maybe_reload(self, interval=1.0):
        now = time.monotonic()
        if now - self._last_check < interval:
            return False
        self._last_check = now
        try:
            mtime = self.manifest_path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime = None
        if mtime != self._mtime:
            self._load()
            return True
        return False

    def snapshot(self):
        return self._snapshot

    @property
    def committed_seq(self):
        return int(self.manifest.get("committed_seq", 0))

    @property
    def generation(self):
        return int(self.manifest.get("generation", 0))

    @property
    def doc_count(self):
        return self._snapshot.N

    def stats(self):
        snap = self._snapshot
        return {"documents": snap.N, "segments": len(snap.readers), "generation": snap.generation,
                "committed_seq": self.committed_seq,
                "terms_upper_bound": sum(r.term_count for r in snap.readers),
                "deleted_pending_merge": sum(r.n_deleted for r in snap.readers),
                "avg_field_lengths": {FIELDS[i]: round(snap.avg[i], 1) for i in range(NF)},
                "postings_cache": {"bytes": self.cache.bytes, "hits": self.cache.hits, "misses": self.cache.misses}}

    # ---------------------------------------------------------------- writing
    @contextmanager
    def write_lock(self):
        with self._thread_lock:
            fd = os.open(self.dir / "write.lock", os.O_RDWR | os.O_CREAT, 0o644)
            try:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                self._load()
                yield
            finally:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def commit(self, changes, committed_seq=None):
        """Apply [(doc_id, fields | None, static_byte)] atomically. Caller must hold write_lock()."""
        m = self.manifest
        snap = self._snapshot
        final = {}
        for doc_id, fields, static in changes:
            final[int(doc_id)] = (fields, static) if fields else None
        gen = int(m.get("generation", 0)) + 1
        segs = [dict(s) for s in m["segments"]]
        dels = {}
        for doc_id in final:
            for ri, r in enumerate(snap.readers):
                loc = r.local_of(doc_id)
                if loc is not None and not r.is_deleted(loc):
                    dels.setdefault(ri, set()).add(loc)
        for ri, locs in dels.items():
            r = snap.readers[ri]
            bitmap = bytearray(r.deleted)
            for loc in locs:
                bitmap[loc >> 3] |= 1 << (loc & 7)
            fname = f"{r.name}.del{gen}"
            tmp = self.dir / (fname + ".tmp")
            with open(tmp, "wb") as f:
                f.write(bitmap)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.dir / fname)
            segs[ri]["del_file"] = fname
            segs[ri]["n_deleted"] = sum(bin(b).count("1") for b in bitmap)
        builder = SegmentBuilder()
        for doc_id, val in final.items():
            if val:
                builder.add(doc_id, val[0], val[1])
        next_seg = int(m.get("next_seg", 1))
        if len(builder):
            name = f"seg_{next_seg:08d}"
            next_seg += 1
            meta = builder.write(self.dir, name)
            meta.update(n_deleted=0, del_file=None, created=time.time())
            segs.append(meta)
        new = {"generation": gen, "segments": segs, "next_seg": next_seg, "updated_at": time.time(),
               "committed_seq": max(int(m.get("committed_seq", 0)), int(committed_seq or 0))}
        self._write_manifest(new)
        self._load()
        self._gc()

    def maybe_merge(self, force_all=False):
        """Tiered merge policy. Caller must hold write_lock()."""
        merged = 0
        while True:
            segs = self.manifest["segments"]
            if len(segs) <= 1 and not (segs and segs[0].get("n_deleted")) or not segs:
                break
            live = [(s["n_docs"] - s.get("n_deleted", 0), i) for i, s in enumerate(segs)]
            pick = None
            if force_all:
                pick = [i for _, i in live]
                if len(pick) == 1 and not segs[0].get("n_deleted"):
                    break
            else:
                tiers = {}
                for n, i in live:
                    tiers.setdefault(int(math.log(max(n, 1), self.merge_factor)), []).append(i)
                for _tier, idx in sorted(tiers.items()):
                    if len(idx) >= self.merge_factor:
                        pick = idx[:self.merge_factor]
                        break
                if pick is None:
                    heavy = [i for i, s in enumerate(segs) if s["n_docs"] >= 500 and s.get("n_deleted", 0) / s["n_docs"] > 0.4]
                    if heavy:
                        pick = heavy[:1]
            if not pick:
                break
            self._merge(pick)
            merged += 1
            if force_all:
                break
        return merged

    def _merge(self, indexes):
        m = self.manifest
        snap = self._snapshot
        readers = [snap.readers[i] for i in indexes]
        next_seg = int(m.get("next_seg", 1))
        name = f"seg_{next_seg:08d}"
        meta = merge_segments(readers, self.dir, name)
        meta.update(n_deleted=0, del_file=None, created=time.time(), merged_from=[r.name for r in readers])
        drop = set(indexes)
        segs = [dict(s) for i, s in enumerate(m["segments"]) if i not in drop]
        if meta["n_docs"]:
            segs.append(meta)
        new = dict(m, generation=int(m.get("generation", 0)) + 1, segments=segs, next_seg=next_seg + 1,
                   updated_at=time.time())
        self._write_manifest(new)
        self._load()
        self._gc()

    def _gc(self):
        keep = set()
        for s in self.manifest["segments"]:
            keep.update(f"{s['name']}.{ext}" for ext in ("post", "pos", "terms", "tix", "docs"))
            if s.get("del_file"):
                keep.add(s["del_file"])
        for p in self.dir.iterdir():
            if p.name.startswith("seg_") and p.name not in keep:
                try:
                    p.unlink()
                except OSError:
                    pass


def url_words(url):
    """Words from host labels and path segments (no scheme, no 'www', no query)."""
    from urllib.parse import urlsplit
    try:
        p = urlsplit(url)
    except ValueError:
        return ""
    host = (p.hostname or "")
    labels = [x for x in host.split(".") if x and x != "www"]
    return " ".join(labels) + " " + p.path.replace("/", " ").replace("-", " ").replace("_", " ").replace(".", " ")


def static_byte(quality, pagerank):
    return int(255 * max(0.0, min(1.0, 0.6 * (quality or 0) + 0.4 * (pagerank or 0))))


class Indexer:
    """Moves document changes from the store into index segments, incrementally."""

    def __init__(self, store, index, settings):
        self.store, self.index, self.settings = store, index, settings

    def fields_for(self, row):
        text = _decompress(row["body"])
        original=self.store.originals([row['id']]).get(row['id'],{})
        url = row["url"]
        anchors = self.store.anchors_for(url)
        meta = [META + "site:" + s for s in host_suffixes(row["host"] or "")]
        meta.append(META + "analysis:2")
        meta.append(META + "type:" + (row["source_type"] or "web"))
        ext = file_extension(url)
        if ext and len(ext) <= 8:
            meta.append(META + "ext:" + ext)
        if row["lang"]:
            meta.append(META + "lang:" + row["lang"].lower())
            if "-" in row["lang"]:
                meta.append(META + "lang:" + row["lang"].lower().split("-")[0])
        if row["published_at"]:
            meta.append(META + "dated")
        return {
            "title": analyze(row["title"] or ""),
            "headings": analyze(((row["headings"] or "") + " " + (row["description"] or ""))[:50_000]),
            "url": analyze(url_words(url)),
            "anchor": analyze(" ".join(anchors))[:3000],
            "body": analyze(text[:self.settings.max_index_chars])[: self.settings.max_index_tokens],
            "exact": ["\x02e:"+t for field in [original.get("title",row["title"] or ""), row["headings"] or "", original.get("text",text)] for t in exact_tokens(field[:self.settings.max_index_chars])[:self.settings.max_index_tokens]+["__boundary__"]],
            "ngram": ["\x02g:"+t for t in ngrams((row["title"] or "")+" "+text[:12000])][:12000],
            "phonetic": ["\x02p:"+phonetic_key(t) for t in tokenize((row["title"] or "")+" "+text[:20000]) if not t.isascii() and phonetic_key(t)],
            "meta": meta,
        }

    def _batch(self, seq, limit):
        rows = self.store.changes_since(seq, limit)
        if len(rows) == limit:                        # never split a group of rows sharing one seq
            last = rows[-1]
            rows.extend(self.store.db.query(
                "SELECT id, seq, url, host, title, description, headings, body, lang, source_type, content_type, "
                "quality, pagerank, active, duplicate_of, published_at FROM documents WHERE seq = ? AND id > ? ORDER BY id",
                (last["seq"], last["id"])))
        return rows

    def run(self, max_docs=None, merge=True):
        total = 0
        with self.index.write_lock():
            while True:
                rows = self._batch(self.index.committed_seq, self.settings.index_flush_docs)
                if not rows:
                    break
                changes = []
                for row in rows:
                    if row["active"] and row["duplicate_of"] is None:
                        changes.append((row["id"], self.fields_for(row), static_byte(row["quality"], row["pagerank"])))
                    else:
                        changes.append((row["id"], None, 0))
                self.index.commit(changes, max(r["seq"] for r in rows))
                total += len(rows)
                if max_docs and total >= max_docs:
                    break
            if merge:
                self.index.maybe_merge()
        return total

    def optimize(self):
        with self.index.write_lock():
            return self.index.maybe_merge(force_all=True)


__all__ = ["IndexManager", "Indexer", "Snapshot", "META", "tokenize"]
