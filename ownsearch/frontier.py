"""Persistent URL frontier (SQLite).

* ``urls``: every known URL with status, priority, next fetch time, retry counters, validators (ETag /
  Last-Modified), change history and an adaptive recrawl interval.
* ``hosts``: per-host politeness (next allowed time, crawl-delay, error backoff, in-flight lease), cached
  robots.txt and the earliest due URL (``next_due_at``) so claiming work is an indexed lookup.
* Leases make it safe to run several crawler processes on one frontier; expired leases are recovered,
  so a crash or restart never loses the queue.

Statuses: queued (includes scheduled recrawls) | leased | gone | blocked | disallowed | failed | redirected
"""
import json
import random
import time

from .db import Database
from .util import host_of, is_probable_trap, normalize_url, registrable_domain, url_depth

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls(
  url TEXT PRIMARY KEY, host TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  priority REAL DEFAULT 1, next_fetch_at REAL DEFAULT 0, lease_until REAL DEFAULT 0,
  attempts INTEGER DEFAULT 0, last_error TEXT, depth INTEGER DEFAULT 0, source TEXT, kind TEXT DEFAULT 'page',
  discovered_at REAL, last_fetched_at REAL, last_changed_at REAL, fetch_count INTEGER DEFAULT 0,
  change_count INTEGER DEFAULT 0, recrawl_interval REAL, etag TEXT, last_modified TEXT, content_hash TEXT,
  sitemap_lastmod REAL, doc_id INTEGER, http_status INTEGER) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_urls_host_due ON urls(host, status, next_fetch_at);
CREATE INDEX IF NOT EXISTS ix_urls_host_prio ON urls(host, status, priority);
CREATE INDEX IF NOT EXISTS ix_urls_status ON urls(status);
CREATE INDEX IF NOT EXISTS ix_urls_lease ON urls(status, lease_until);
CREATE TABLE IF NOT EXISTS hosts(
  host TEXT PRIMARY KEY, next_allowed_at REAL DEFAULT 0, lease_until REAL DEFAULT 0, crawl_delay REAL,
  backoff_until REAL DEFAULT 0, consecutive_errors INTEGER DEFAULT 0, next_due_at REAL,
  robots_txt TEXT, robots_status INTEGER, robots_fetched_at REAL, pages_fetched INTEGER DEFAULT 0,
  urls_known INTEGER DEFAULT 0, sitemaps_checked_at REAL, seed INTEGER DEFAULT 0) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_hosts_due ON hosts(next_due_at);
CREATE TABLE IF NOT EXISTS fmeta(key TEXT PRIMARY KEY, value TEXT);
"""

SCOPES = ("host", "domain", "open")
TERMINAL = ("gone", "blocked", "disallowed", "failed", "redirected")
DEFAULT_INTERVALS = {"feed": 3600.0, "sitemap": 12 * 3600.0, "home": 6 * 3600.0}


class Frontier:
    def __init__(self, settings):
        self.settings = settings
        settings.ensure_dirs()
        self.db = Database(settings.frontier_path, SCHEMA)
        self._scope_cache = None
        self._scope_loaded = 0.0

    # ------------------------------------------------------------ scope
    def get_meta(self, key, default=None):
        row = self.db.one("SELECT value FROM fmeta WHERE key=?", (key,))
        return row[0] if row else default

    def set_meta(self, key, value):
        with self.db.tx() as c:
            c.execute("INSERT INTO fmeta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    def set_scope(self, scope):
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        self.set_meta("scope", scope)
        self._scope_cache = None

    def _scope(self):
        now = time.monotonic()
        if self._scope_cache is None or now - self._scope_loaded > 10:
            scope = self.get_meta("scope", "domain")
            seeds = [r[0] for r in self.db.query("SELECT host FROM hosts WHERE seed=1")]
            self._scope_cache = (scope, set(seeds), {registrable_domain(h) for h in seeds})
            self._scope_loaded = now
        return self._scope_cache

    def in_scope(self, url):
        scope, hosts, domains = self._scope()
        host = host_of(url)
        if scope == "open":
            return True
        if scope == "host":
            return host in hosts
        return registrable_domain(host) in domains

    # ------------------------------------------------------------ enqueue
    def add_seeds(self, urls, priority=10.0, scope=None):
        if scope:
            self.set_scope(scope)
        items = []
        with self.db.tx() as c:
            for u in urls:
                key = normalize_url(u)
                if not key.startswith(("http://", "https://")):
                    continue
                c.execute("INSERT INTO hosts(host, seed) VALUES(?, 1) ON CONFLICT(host) DO UPDATE SET seed=1",
                          (host_of(key),))
                items.append({"url": key, "priority": priority, "source": "seed", "depth": 0, "force": True})
        self._scope_cache = None
        return self.enqueue_many(items)

    def enqueue_many(self, items, respect_scope=True):
        """items: dicts with url, priority, depth, source, kind, lastmod (ts), force (bool). Returns # new."""
        now = time.time()
        new = 0
        max_depth = self.settings.max_depth
        rows = []
        for it in items:
            url = normalize_url(it.get("url", ""))
            if not url.startswith(("http://", "https://")) or is_probable_trap(url):
                continue
            if respect_scope and not it.get("force") and not self.in_scope(url):
                continue
            depth = int(it.get("depth", 0))
            if depth > max_depth and not it.get("force"):
                continue
            rows.append((url, it))
        if not rows:
            return 0
        with self.db.tx() as c:
            host_counts = {}
            for url, it in rows:
                host = host_of(url)
                if host not in host_counts:
                    r = c.execute("SELECT urls_known FROM hosts WHERE host=?", (host,)).fetchone()
                    if r is None:
                        c.execute("INSERT INTO hosts(host) VALUES(?)", (host,))
                        host_counts[host] = 0
                    else:
                        host_counts[host] = r[0] or 0
                existing = c.execute("SELECT status, last_fetched_at, sitemap_lastmod, priority FROM urls WHERE url=?",
                                     (url,)).fetchone()
                prio = float(it.get("priority", 1.0))
                lastmod = it.get("lastmod")
                when = float(it.get("next_fetch_at", now))
                if existing is None:
                    if host_counts[host] >= self.settings.max_pages_per_host and not it.get("force"):
                        continue
                    kind = it.get("kind") or ("home" if url_depth(url) == 0 and not url.split("?")[1:] else "page")
                    c.execute("INSERT INTO urls(url, host, status, priority, next_fetch_at, depth, source, kind, "
                              "discovered_at, sitemap_lastmod) VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (url, host, "queued", prio, when, int(it.get("depth", 0)), it.get("source", "link"),
                               kind, now, lastmod))
                    host_counts[host] += 1
                    new += 1
                    c.execute("UPDATE hosts SET urls_known=urls_known+1, next_due_at=MIN(COALESCE(next_due_at, ?), ?) "
                              "WHERE host=?", (when, when, host))
                    continue
                status, fetched, old_lastmod, old_prio = existing
                updates, params = [], []
                if prio > (old_prio or 0):
                    updates.append("priority=?")
                    params.append(prio)
                # sitemap/feed says the page changed after we last fetched it: fetch again soon
                if lastmod and fetched and lastmod > fetched and status == "queued":
                    updates.append("next_fetch_at=MIN(next_fetch_at, ?)")
                    params.append(now)
                    c.execute("UPDATE hosts SET next_due_at=MIN(COALESCE(next_due_at, ?), ?) WHERE host=?",
                              (now, now, host))
                if lastmod and lastmod != old_lastmod:
                    updates.append("sitemap_lastmod=?")
                    params.append(lastmod)
                if it.get("force") and status in TERMINAL and status != "disallowed":
                    updates.append("status='queued', attempts=0, next_fetch_at=?")
                    params.append(now)
                    c.execute("UPDATE hosts SET next_due_at=MIN(COALESCE(next_due_at, ?), ?) WHERE host=?",
                              (now, now, host))
                if updates:
                    c.execute(f"UPDATE urls SET {', '.join(updates)} WHERE url=?", (*params, url))
        return new

    # ------------------------------------------------------------ claiming
    def recover_leases(self):
        now = time.time()
        with self.db.tx() as c:
            n = c.execute("UPDATE urls SET status='queued', lease_until=0 WHERE status='leased' AND lease_until < ?",
                          (now,)).rowcount
            c.execute("UPDATE hosts SET lease_until=0 WHERE lease_until > 0 AND lease_until < ?", (now,))
            if n:
                c.execute("UPDATE hosts SET next_due_at=(SELECT MIN(next_fetch_at) FROM urls u "
                          "WHERE u.host=hosts.host AND u.status='queued')")
        return n

    def _refresh_due(self, c, host):
        c.execute("UPDATE hosts SET next_due_at=(SELECT MIN(next_fetch_at) FROM urls WHERE host=? AND status='queued') "
                  "WHERE host=?", (host, host))

    def claim(self, lease_seconds=None):
        """Atomically lease the best due URL whose host may be contacted now. Returns a dict or None."""
        now = time.time()
        lease = lease_seconds or (self.settings.fetch_timeout * (self.settings.max_redirects + 2) + 30)
        if not self.db.one("SELECT 1 FROM hosts WHERE next_due_at <= ? AND next_allowed_at <= ? AND lease_until <= ? "
                           "AND backoff_until <= ? LIMIT 1", (now, now, now, now)):
            return None                      # cheap read-only check: nothing claimable, skip the write lock
        with self.db.tx() as c:
            hosts = c.execute(
                "SELECT host FROM hosts WHERE next_due_at IS NOT NULL AND next_due_at <= ? AND next_allowed_at <= ? "
                "AND lease_until <= ? AND backoff_until <= ? ORDER BY next_allowed_at LIMIT 16",
                (now, now, now, now)).fetchall()
            for (host,) in hosts:
                row = c.execute("SELECT * FROM urls WHERE host=? AND status='queued' AND next_fetch_at <= ? "
                                "ORDER BY priority DESC, next_fetch_at LIMIT 1", (host, now)).fetchone()
                if row is None:
                    self._refresh_due(c, host)
                    continue
                c.execute("UPDATE urls SET status='leased', lease_until=? WHERE url=?", (now + lease, row["url"]))
                c.execute("UPDATE hosts SET lease_until=? WHERE host=?", (now + lease, host))
                self._refresh_due(c, host)
                return dict(row)
        return None

    def next_due_in(self):
        now = time.time()
        row = self.db.one("SELECT MIN(MAX(next_due_at, next_allowed_at, backoff_until)) FROM hosts "
                          "WHERE next_due_at IS NOT NULL AND lease_until <= ?", (now,))
        if not row or row[0] is None:
            return None
        return max(0.0, row[0] - now)

    def leased_count(self):
        return self.db.one("SELECT COUNT(*) FROM urls WHERE status='leased'")[0]

    # ------------------------------------------------------------ host data
    def host(self, host):
        row = self.db.one("SELECT * FROM hosts WHERE host=?", (host,))
        return dict(row) if row else None

    def save_robots(self, host, text, status, crawl_delay):
        with self.db.tx() as c:
            c.execute("INSERT INTO hosts(host) VALUES(?) ON CONFLICT(host) DO NOTHING", (host,))
            c.execute("UPDATE hosts SET robots_txt=?, robots_status=?, robots_fetched_at=?, crawl_delay=? WHERE host=?",
                      (text[:500_000] if text else text, status, time.time(), crawl_delay, host))

    def mark_sitemaps_checked(self, host):
        with self.db.tx() as c:
            c.execute("UPDATE hosts SET sitemaps_checked_at=? WHERE host=?", (time.time(), host))

    # ------------------------------------------------------------ completion
    def _interval(self, row, outcome):
        s = self.settings
        kind = row.get("kind") or "page"
        base = row.get("recrawl_interval") or DEFAULT_INTERVALS.get(kind, s.default_recrawl)
        lo = 900.0 if kind == "feed" else s.min_recrawl
        if outcome.get("hint"):
            return max(lo, min(s.max_recrawl, float(outcome["hint"])))
        if outcome.get("changed"):
            base *= 0.5
        else:
            base *= 1.6
        if outcome.get("new_links", 0) >= 5:               # hub page that keeps producing new URLs
            base *= 0.7
        return max(lo, min(s.max_recrawl, base))

    def complete(self, url, outcome):
        """Record a fetch outcome. outcome["result"] in:
        ok | not_modified | gone | blocked | disallowed | retry | failed | redirected | skipped"""
        now = time.time()
        res = outcome.get("result", "ok")
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM urls WHERE url=?", (url,)).fetchone()
            if row is None:
                return
            row = dict(row)
            host = row["host"]
            h = c.execute("SELECT crawl_delay, consecutive_errors FROM hosts WHERE host=?", (host,)).fetchone()
            delay = max(self.settings.default_delay, min(self.settings.max_crawl_delay, (h["crawl_delay"] or 0) if h else 0))
            host_updates = {"lease_until": 0, "next_allowed_at": now + delay}
            fields = {"lease_until": 0, "last_error": outcome.get("error"), "http_status": outcome.get("status")}
            if res in ("ok", "not_modified", "skipped"):
                changed = res == "ok" and bool(outcome.get("changed"))
                interval = self._interval(row, {**outcome, "changed": changed})
                fields.update(status="queued", attempts=0, last_fetched_at=now, fetch_count=row["fetch_count"] + 1,
                              recrawl_interval=interval, next_fetch_at=now + interval * random.uniform(0.9, 1.1))
                if changed:
                    fields.update(last_changed_at=now, change_count=row["change_count"] + 1)
                for k in ("etag", "last_modified", "content_hash", "doc_id"):
                    if outcome.get(k) is not None:
                        fields[k] = outcome[k]
                host_updates["consecutive_errors"] = 0
                c.execute("UPDATE hosts SET pages_fetched=pages_fetched+1 WHERE host=?", (host,))
            elif res == "retry":
                attempts = row["attempts"] + 1
                if attempts >= self.settings.max_attempts:
                    fields.update(status="failed", attempts=attempts)
                else:
                    ra = outcome.get("retry_after")
                    wait = min(6 * 3600, ra) if ra is not None else min(6 * 3600, 60 * (3 ** attempts))
                    fields.update(status="queued", attempts=attempts,
                                  next_fetch_at=now + wait * random.uniform(1.0, 1.3))
                errs = (h["consecutive_errors"] if h else 0) + 1
                host_updates["consecutive_errors"] = errs
                if outcome.get("host_backoff") or errs >= 5:
                    ra = outcome.get("retry_after")
                    back = min(24 * 3600, ra) if ra is not None else min(24 * 3600, 30 * (2 ** min(errs, 12)))
                    host_updates["backoff_until"] = now + back
            elif res in TERMINAL:
                fields.update(status=res, last_fetched_at=now)
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE urls SET {sets} WHERE url=?", (*fields.values(), url))
            hs = ", ".join(f"{k}=?" for k in host_updates)
            c.execute(f"UPDATE hosts SET {hs} WHERE host=?", (*host_updates.values(), host))
            self._refresh_due(c, host)

    def release(self, url, delay=0.0):
        """Give a leased URL back without counting an attempt (e.g. robots.txt still loading)."""
        now = time.time()
        with self.db.tx() as c:
            row = c.execute("SELECT host FROM urls WHERE url=?", (url,)).fetchone()
            if not row:
                return
            c.execute("UPDATE urls SET status='queued', lease_until=0, next_fetch_at=? WHERE url=?", (now + delay, url))
            c.execute("UPDATE hosts SET lease_until=0 WHERE host=?", (row[0],))
            self._refresh_due(c, row[0])

    def mark_redirected(self, url, target):
        with self.db.tx() as c:
            c.execute("UPDATE urls SET status='redirected', last_error=?, lease_until=0 WHERE url=?",
                      (("-> " + target)[:500], url))

    # ------------------------------------------------------------ admin / stats
    def retry_failed(self, include=("failed",)):
        now = time.time()
        with self.db.tx() as c:
            marks = ",".join("?" * len(include))
            n = c.execute(f"UPDATE urls SET status='queued', attempts=0, next_fetch_at=? WHERE status IN ({marks})",
                          (now, *include)).rowcount
            c.execute("UPDATE hosts SET backoff_until=0, consecutive_errors=0, next_due_at=(SELECT MIN(next_fetch_at) "
                      "FROM urls u WHERE u.host=hosts.host AND u.status='queued')")
        return n

    def recrawl_now(self, url_like=None):
        now = time.time()
        with self.db.tx() as c:
            if url_like:
                n = c.execute("UPDATE urls SET next_fetch_at=? WHERE status='queued' AND url LIKE ?",
                              (now, url_like)).rowcount
            else:
                n = c.execute("UPDATE urls SET next_fetch_at=? WHERE status='queued'", (now,)).rowcount
            c.execute("UPDATE hosts SET next_due_at=(SELECT MIN(next_fetch_at) FROM urls u WHERE u.host=hosts.host "
                      "AND u.status='queued')")
        return n

    def stats(self):
        now = time.time()
        by_status = {r[0]: r[1] for r in self.db.query("SELECT status, COUNT(*) FROM urls GROUP BY status")}
        due = self.db.one("SELECT COUNT(*) FROM urls WHERE status='queued' AND next_fetch_at <= ?", (now,))[0]
        never = self.db.one("SELECT COUNT(*) FROM urls WHERE status='queued' AND fetch_count=0")[0]
        hosts = self.db.one("SELECT COUNT(*), SUM(CASE WHEN backoff_until > ? THEN 1 ELSE 0 END) FROM hosts", (now,))
        return {"urls": sum(by_status.values()), "by_status": by_status, "due_now": due, "never_fetched": never,
                "hosts": hosts[0] or 0, "hosts_in_backoff": hosts[1] or 0, "scope": self.get_meta("scope", "domain")}

    def list_urls(self, status=None, limit=50):
        if status:
            rows = self.db.query("SELECT url, status, priority, attempts, last_error, http_status, fetch_count, "
                                 "next_fetch_at FROM urls WHERE status=? ORDER BY priority DESC LIMIT ?", (status, limit))
        else:
            rows = self.db.query("SELECT url, status, priority, attempts, last_error, http_status, fetch_count, "
                                 "next_fetch_at FROM urls ORDER BY priority DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def export_state(self):
        return json.dumps(self.stats())
