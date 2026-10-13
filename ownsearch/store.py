"""Document store (SQLite): documents, link graph, near-duplicate bands, feedback and query log.

Every change to a document bumps a global sequence number (``seq``). The indexer consumes changes in
seq order, so indexing is incremental and crash-safe: anything after the index's committed seq is
simply re-applied.
"""
import json
import zlib

from .config import Settings
from .db import Database
from .quality import hamming, page_quality, simhash, simhash_bands
from .textproc import tokenize
from .util import clean_multiline, host_of, normalize_text, normalize_url, now_ts, sha256_text, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  final_url TEXT, host TEXT, title TEXT, description TEXT, headings TEXT, body BLOB,
  lang TEXT, content_type TEXT, source_type TEXT,
  published_at TEXT, modified_at TEXT, discovered_at TEXT, fetched_at TEXT, changed_at TEXT,
  content_hash TEXT, simhash INTEGER, duplicate_of INTEGER,
  quality REAL DEFAULT 0.5, pagerank REAL DEFAULT 0, word_count INTEGER DEFAULT 0,
  extraction_status TEXT, metadata TEXT, active INTEGER DEFAULT 1, seq INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_docs_seq ON documents(seq);
CREATE INDEX IF NOT EXISTS ix_docs_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS ix_docs_host ON documents(host);
CREATE INDEX IF NOT EXISTS ix_docs_dup ON documents(duplicate_of);
CREATE TABLE IF NOT EXISTS links(
  src_id INTEGER NOT NULL, dst_key TEXT NOT NULL, anchor TEXT, nofollow INTEGER DEFAULT 0, added_at REAL,
  PRIMARY KEY(src_id, dst_key)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_links_dst ON links(dst_key);
CREATE INDEX IF NOT EXISTS ix_links_added ON links(added_at);
CREATE TABLE IF NOT EXISTS simhash_bands(band INTEGER, value INTEGER, doc_id INTEGER,
  PRIMARY KEY(band, value, doc_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_bands_doc ON simhash_bands(doc_id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, ts REAL, agent TEXT, query TEXT, url TEXT,
  doc_id INTEGER, grade INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS query_log(id INTEGER PRIMARY KEY, ts REAL, agent TEXT, query TEXT,
  results INTEGER, latency_ms REAL);
"""

FEATURE_COLUMNS = ("id, url, final_url, host, title, description, lang, content_type, source_type, "
                   "published_at, modified_at, discovered_at, fetched_at, changed_at, simhash, duplicate_of, "
                   "quality, pagerank, word_count, extraction_status, active")


def _compress(text):
    return zlib.compress(text.encode("utf-8", "replace"), 6)


def _decompress(blob):
    if not blob:
        return ""
    try:
        return zlib.decompress(blob).decode("utf-8", "replace")
    except zlib.error:
        return ""


class DocumentStore:
    def __init__(self, root=None, settings=None):
        self.settings = settings or Settings.load(root)
        self.root = self.settings.data_dir
        self.settings.ensure_dirs()
        self.db = Database(self.settings.db_path, SCHEMA)
        with self.db.tx() as c:
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('seq', '0')")
        self._migrate_legacy()

    def ensure(self):
        self.settings.ensure_dirs()

    # ------------------------------------------------------------ meta helpers
    def get_meta(self, key, default=None):
        row = self.db.one("SELECT value FROM meta WHERE key=?", (key,))
        return row[0] if row else default

    def set_meta(self, key, value):
        with self.db.tx() as c:
            c.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    @staticmethod
    def _next_seq(c):
        return int(c.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key='seq' "
                             "RETURNING value").fetchone()[0])

    def current_seq(self):
        return int(self.get_meta("seq", 0))

    # ------------------------------------------------------------ writes
    def upsert(self, url, title, text, *, final_url=None, description="", headings="", lang="",
               content_type="", source_type="web", published_at=None, modified_at=None, fetched_at=None,
               metadata=None, extraction_status="ok", links=None, n_links=None, hidden_chars=0):
        """Insert or update a document keyed by its normalised URL.

        Returns {"id", "status": new|updated|unchanged, "duplicate_of", "changed"}.
        """
        key = normalize_url(url) or (url or "").strip()
        if not key:
            raise ValueError("Document needs a URL or identifier")
        title = normalize_text(title)[:1000]
        text = clean_multiline(text, keep_formfeed=True)[: self.settings.max_text_chars]
        if not title and not text:
            raise ValueError("Document has no searchable content")
        tokens = tokenize(title + " " + text[:300_000])
        content_hash = sha256_text(title + "\n" + text)
        fingerprint = simhash(tokens)
        quality = page_quality(title, tokens, key, n_links if n_links is not None else len(links or ()),
                               hidden_chars, len(text))
        now = utc_now()
        fetched_at = fetched_at or now
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)[:200_000]
        with self.db.tx() as c:
            row = c.execute("SELECT id, content_hash, active, duplicate_of, discovered_at FROM documents WHERE url=?",
                            (key,)).fetchone()
            if row and row["content_hash"] == content_hash and row["active"]:
                c.execute("UPDATE documents SET fetched_at=? WHERE id=?", (fetched_at, row["id"]))
                return {"id": row["id"], "status": "unchanged", "duplicate_of": row["duplicate_of"], "changed": False}
            dup = self._find_duplicate(c, content_hash, fingerprint, len(tokens), row["id"] if row else None)
            seq = self._next_seq(c)
            values = {
                "url": key, "final_url": final_url or key, "host": host_of(key), "title": title,
                "description": normalize_text(description)[:2000], "headings": normalize_text(headings)[:20000],
                "body": _compress(text), "lang": (lang or "")[:20], "content_type": (content_type or "")[:200],
                "source_type": source_type, "published_at": published_at, "modified_at": modified_at,
                "fetched_at": fetched_at, "changed_at": now, "content_hash": content_hash,
                "simhash": fingerprint, "duplicate_of": dup, "quality": quality, "word_count": len(tokens),
                "extraction_status": extraction_status, "metadata": meta_json, "active": 1, "seq": seq,
            }
            if row:
                doc_id, status = row["id"], "updated"
                sets = ", ".join(f"{k}=:{k}" for k in values)
                c.execute(f"UPDATE documents SET {sets} WHERE id=:id", dict(values, id=doc_id))
                self._release_duplicates(c, doc_id, seq)
            else:
                values["discovered_at"] = now
                cols = ", ".join(values)
                c.execute(f"INSERT INTO documents({cols}) VALUES({', '.join(':' + k for k in values)})", values)
                doc_id, status = c.execute("SELECT last_insert_rowid()").fetchone()[0], "new"
            c.execute("DELETE FROM simhash_bands WHERE doc_id=?", (doc_id,))
            if dup is None and len(tokens) >= 50:
                c.executemany("INSERT OR IGNORE INTO simhash_bands(band, value, doc_id) VALUES(?, ?, ?)",
                              [(b, v, doc_id) for b, v in simhash_bands(fingerprint)])
            if links is not None:
                self._store_links(c, doc_id, links)
        return {"id": doc_id, "status": status, "duplicate_of": dup, "changed": True}

    def _find_duplicate(self, c, content_hash, fingerprint, n_tokens, exclude_id):
        exclude_id = exclude_id or -1
        row = c.execute("SELECT id FROM documents WHERE content_hash=? AND active=1 AND duplicate_of IS NULL "
                        "AND id != ? LIMIT 1", (content_hash, exclude_id)).fetchone()
        if row:
            return row[0]
        if n_tokens < 50:
            return None
        candidates = set()
        for band, value in simhash_bands(fingerprint):
            for r in c.execute("SELECT doc_id FROM simhash_bands WHERE band=? AND value=? LIMIT 50", (band, value)):
                if r[0] != exclude_id:
                    candidates.add(r[0])
        if not candidates:
            return None
        marks = ",".join("?" * len(candidates))
        for r in c.execute(f"SELECT id, simhash, word_count FROM documents WHERE id IN ({marks}) AND active=1 "
                           "AND duplicate_of IS NULL ORDER BY id", list(candidates)):
            wc = r["word_count"] or 0
            if hamming(r["simhash"] or 0, fingerprint) <= 3 and abs(wc - n_tokens) <= 0.2 * max(wc, n_tokens):
                return r["id"]
        return None

    @staticmethod
    def _release_duplicates(c, doc_id, seq):
        """When a canonical document changes or disappears, its duplicates become independent again."""
        c.execute("UPDATE documents SET duplicate_of=NULL, seq=? WHERE duplicate_of=?", (seq, doc_id))

    @staticmethod
    def _store_links(c, src_id, links):
        new = {}
        for dst, anchor, nofollow in links:
            if dst and dst not in new:
                new[dst] = (normalize_text(anchor)[:200], 1 if nofollow else 0)
        old = {r[0] for r in c.execute("SELECT dst_key FROM links WHERE src_id=?", (src_id,))}
        gone = old - new.keys()
        if gone:
            c.executemany("DELETE FROM links WHERE src_id=? AND dst_key=?", [(src_id, d) for d in gone])
        ts = now_ts()
        c.executemany("INSERT OR IGNORE INTO links(src_id, dst_key, anchor, nofollow, added_at) VALUES(?,?,?,?,?)",
                      [(src_id, d, a, n, ts) for d, (a, n) in new.items() if d not in old])

    def touch(self, url, fetched_at=None):
        key = normalize_url(url) or url
        with self.db.tx() as c:
            c.execute("UPDATE documents SET fetched_at=? WHERE url=?", (fetched_at or utc_now(), key))

    def deactivate(self, doc_id=None, url=None, reason=""):
        with self.db.tx() as c:
            if doc_id is None:
                row = c.execute("SELECT id FROM documents WHERE url=?", (normalize_url(url) or url,)).fetchone()
                if not row:
                    return False
                doc_id = row[0]
            row = c.execute("SELECT active FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row or not row[0]:
                return False
            seq = self._next_seq(c)
            c.execute("UPDATE documents SET active=0, seq=?, extraction_status=? WHERE id=?",
                      (seq, ("removed: " + reason)[:200] if reason else "removed", doc_id))
            c.execute("DELETE FROM simhash_bands WHERE doc_id=?", (doc_id,))
            self._release_duplicates(c, doc_id, seq)
        return True

    def bump(self, doc_ids):
        """Mark documents for re-indexing (e.g. new anchor text pointing at them)."""
        ids = list(doc_ids)
        if not ids:
            return
        with self.db.tx() as c:
            seq = self._next_seq(c)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                c.execute(f"UPDATE documents SET seq=? WHERE id IN ({','.join('?' * len(chunk))})", [seq, *chunk])

    # ------------------------------------------------------------ reads
    def changes_since(self, seq, limit=1000):
        return self.db.query(
            "SELECT id, seq, url, host, title, description, headings, body, lang, source_type, content_type, "
            "quality, pagerank, active, duplicate_of, published_at FROM documents WHERE seq > ? ORDER BY seq, id LIMIT ?",
            (seq, limit))

    def anchors_for(self, url_key, limit=200):
        rows = self.db.query("SELECT anchor FROM links WHERE dst_key=? AND anchor != '' LIMIT ?", (url_key, limit))
        seen, out = set(), []
        for r in rows:
            a = r[0].strip()
            if a and a.lower() not in seen:
                seen.add(a.lower())
                out.append(a)
        return out

    def _row_to_doc(self, row, with_text=True):
        if row is None:
            return None
        d = dict(row)
        body = d.pop("body", None)
        if with_text:
            d["text"] = _decompress(body)
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except ValueError:
            d["metadata"] = {}
        return d

    def get(self, doc_id, with_text=True):
        try:
            doc_id = int(doc_id)
        except (TypeError, ValueError):
            return None
        return self._row_to_doc(self.db.one("SELECT * FROM documents WHERE id=?", (doc_id,)), with_text)

    def get_by_url(self, url, with_text=True):
        key = normalize_url(url) or url
        return self._row_to_doc(self.db.one("SELECT * FROM documents WHERE url=?", (key,)), with_text)

    def features(self, ids):
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            for r in self.db.query(f"SELECT {FEATURE_COLUMNS} FROM documents WHERE id IN ({','.join('?' * len(chunk))})",
                                   chunk):
                out[r["id"]] = dict(r)
        return out

    def texts(self, ids):
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            for r in self.db.query(f"SELECT id, body FROM documents WHERE id IN ({','.join('?' * len(chunk))})", chunk):
                out[r[0]] = _decompress(r[1])
        return out

    def stats(self):
        r = self.db.one("SELECT COUNT(*), SUM(active), SUM(CASE WHEN active=1 AND duplicate_of IS NOT NULL THEN 1 ELSE 0 END), "
                        "COUNT(DISTINCT host) FROM documents")
        by_type = {row[0] or "unknown": row[1] for row in
                   self.db.query("SELECT source_type, COUNT(*) FROM documents WHERE active=1 GROUP BY source_type")}
        links = self.db.one("SELECT COUNT(*) FROM links")[0]
        return {"documents_total": r[0] or 0, "documents_active": r[1] or 0, "duplicates": r[2] or 0,
                "hosts": r[3] or 0, "links": links, "by_type": by_type, "seq": self.current_seq()}

    # ------------------------------------------------------------ legacy API (v0.1 compatible)
    def add(self, title, text, url="", source_type="text", metadata=None):
        res = self.upsert(url or f"local://doc/{sha256_text(title + text)[:16]}", title, text,
                          source_type=source_type, metadata=metadata)
        return self.get(res["id"])

    def all_documents(self):
        for row in self.db.query("SELECT * FROM documents WHERE active=1 ORDER BY id"):
            yield self._row_to_doc(row)

    # ------------------------------------------------------------ feedback / logs
    def add_feedback(self, agent, query, url, doc_id, grade, note=""):
        with self.db.tx() as c:
            c.execute("INSERT INTO feedback(ts, agent, query, url, doc_id, grade, note) VALUES(?,?,?,?,?,?,?)",
                      (now_ts(), agent, query[:1000], url[:2000], doc_id, int(grade), note[:1000]))

    def log_query(self, agent, query, results, latency_ms):
        try:
            with self.db.tx() as c:
                c.execute("INSERT INTO query_log(ts, agent, query, results, latency_ms) VALUES(?,?,?,?,?)",
                          (now_ts(), agent, query[:1000], results, latency_ms))
        except Exception:
            pass

    # ------------------------------------------------------------ v0.1 data migration
    def _migrate_legacy(self):
        legacy = self.root / "documents" / "documents.jsonl"
        if not legacy.exists() or self.get_meta("legacy_migrated"):
            return
        inactive = set()
        meta_path = self.root / "metadata.json"
        if meta_path.exists():
            try:
                inactive = set(json.loads(meta_path.read_text(encoding="utf-8")).get("inactive_ids", []))
            except (OSError, ValueError):
                pass
        count = 0
        with legacy.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not d.get("active", True) or d.get("id") in inactive:
                    continue
                try:
                    self.upsert(d.get("url") or f"local://legacy/{d.get('id')}", d.get("title", ""), d.get("text", ""),
                                source_type=d.get("source_type", "text"), metadata=d.get("metadata") or {},
                                fetched_at=d.get("indexed_at"))
                    count += 1
                except ValueError:
                    continue
        self.set_meta("legacy_migrated", count)
