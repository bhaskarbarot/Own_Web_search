"""SQLite helpers: one connection per thread, WAL mode, explicit IMMEDIATE write transactions."""
import sqlite3
import threading
from contextlib import contextmanager


class Database:
    def __init__(self, path, schema=""):
        self.path = str(path)
        self._local = threading.local()
        self._wlock = threading.RLock()     # threads of one process queue here instead of SQLite busy-sleeping
        if schema:
            self.conn().executescript(schema)

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=60, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=60000")
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA cache_size=-65536")
            self._local.conn = c
        return c

    @contextmanager
    def tx(self):
        c = self.conn()
        if c.in_transaction:            # nested use joins the outer transaction
            yield c
            return
        with self._wlock:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def execute(self, sql, params=()):
        return self.conn().execute(sql, params)

    def query(self, sql, params=()):
        return self.conn().execute(sql, params).fetchall()

    def one(self, sql, params=()):
        return self.conn().execute(sql, params).fetchone()

    def close(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
