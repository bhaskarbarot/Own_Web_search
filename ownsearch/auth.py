"""Per-agent API keys (stored hashed), scopes, token-bucket rate limits and daily quotas."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

ALL_SCOPES = ("search", "fetch", "crawl", "ingest", "admin")
DEFAULT_SCOPES = ("search", "fetch")


def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyStore:
    def __init__(self, path):
        self.path = str(path)
        self._mtime = None
        self._by_hash = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError:
            self._by_hash, self._mtime = {}, None
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self._by_hash = {k["key_sha256"]: k for k in data.get("keys", []) if not k.get("disabled")}
        self._mtime = mtime

    def _save(self, keys):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"keys": keys}, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._mtime = None
        self._load()

    def _all(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f).get("keys", [])
        except (OSError, ValueError):
            return []

    @property
    def enabled(self):
        self._load()
        return bool(self._by_hash)

    def create(self, agent, rps=20.0, burst=40, daily_quota=0, scopes=DEFAULT_SCOPES):
        bad = set(scopes) - set(ALL_SCOPES)
        if bad:
            raise ValueError(f"Unknown scopes: {sorted(bad)}")
        key = "os_" + secrets.token_urlsafe(32)
        with self._lock:
            keys = [k for k in self._all() if k["agent"] != agent]
            keys.append({"agent": agent, "key_sha256": _hash(key), "rps": float(rps), "burst": int(burst),
                         "daily_quota": int(daily_quota), "scopes": list(scopes),
                         "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            self._save(keys)
        return key

    def revoke(self, agent):
        with self._lock:
            keys = self._all()
            new = [k for k in keys if k["agent"] != agent]
            self._save(new)
        return len(keys) - len(new)

    def list(self):
        return [{k: v for k, v in rec.items() if k != "key_sha256"} for rec in self._all()]

    def authenticate(self, key):
        if not key:
            return None
        self._load()
        h = _hash(key)
        rec = self._by_hash.get(h)
        if rec and hmac.compare_digest(rec["key_sha256"], h):
            return rec
        return None


class RateLimiter:
    """Token bucket per agent plus a UTC-day quota counter (in memory, per process)."""

    def __init__(self):
        self.buckets = {}
        self.daily = {}
        self.lock = threading.Lock()

    def check(self, agent, rps, burst, daily_quota=0, cost=1.0):
        """-> (allowed, retry_after_seconds, reason)"""
        now = time.monotonic()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.lock:
            used_day, used = self.daily.get(agent, (day, 0))
            if used_day != day:
                used = 0
            if daily_quota and used + cost > daily_quota:
                return False, 3600.0, "daily quota exceeded"
            tokens, last = self.buckets.get(agent, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * rps)
            if tokens < cost:
                self.buckets[agent] = (tokens, now)
                return False, (cost - tokens) / max(rps, 1e-6), "rate limit"
            self.buckets[agent] = (tokens - cost, now)
            self.daily[agent] = (day, used + cost)
            return True, 0.0, ""

    def usage(self):
        with self.lock:
            return {a: {"day": d, "requests": n} for a, (d, n) in self.daily.items()}
