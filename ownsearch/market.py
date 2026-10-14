"""Live market data answers: stock quotes and price-history analysis.

The data source is configuration (``market_lookup_url`` / ``market_chart_url``; defaults point to a free public
feed). The company is identified by asking the source's own symbol lookup with the query's subject words,
rarest word first (rarity measured on our own index). Every number shown comes from the source with its
market timestamp; nothing is estimated, and failures are reported as unavailable.
The analysis (returns, volatility, drawdown, moving averages, monthly table) is computed here.
"""
import json
import math
import statistics
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote

from .fetcher import FetchError, Fetcher

_cache = {}
_lock = threading.Lock()
_disk_caches = {}


def _cached(key, ttl, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    if val is not None:
        with _lock:
            if len(_cache) > 2000:
                _cache.clear()
            _cache[key] = (now, val)
    return val


def _json(fetcher, url, max_bytes=8_000_000, deadline=None, errors=None):
    deadline = min(deadline or float("inf"), time.monotonic() + fetcher.settings.financial_timeout)
    try:
        res = fetcher.fetch(url, accept="application/json", max_bytes=max_bytes, retries=0, deadline=deadline)
    except FetchError as exc:
        if errors is not None:
            errors.append(f'Market provider request failed: {exc.kind}: {exc}')
        return None
    if res.status != 200:
        if errors is not None:
            errors.append(f'Market provider returned HTTP {res.status}.')
        return None
    try:
        return json.loads(res.body.decode("utf-8", "replace"))
    except ValueError:
        if errors is not None:
            errors.append('Market provider returned invalid JSON.')
        return None


def _zone(name=None):
    try:
        return ZoneInfo(name or 'UTC')
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo('UTC')


def _day(ts, zone=None):
    return datetime.fromtimestamp(ts, _zone(zone)).strftime("%Y-%m-%d")


class Market:
    def __init__(self, settings, deadline=None):
        self.settings = settings
        self.deadline = deadline
        self.fetcher = Fetcher(settings)
        self.errors = []
        from .db import Database
        key = str(settings.data_dir)
        with _lock:
            if key not in _disk_caches:
                _disk_caches[key] = Database(settings.data_dir / 'market_cache.db',
                    'CREATE TABLE IF NOT EXISTS responses(key TEXT PRIMARY KEY, ts REAL, value TEXT);')
            self.cache = _disk_caches[key]

    def _cached(self, key, ttl, fetch):
        cache_key = json.dumps(key)
        row = self.cache.one('SELECT ts,value FROM responses WHERE key=?', (cache_key,))
        if row and time.time() - row[0] < ttl:
            self._last_cached_at = row[0]
            return json.loads(row[1])
        value = _cached(key, ttl, fetch)
        if value is not None:
            with _lock:
                captured = _cache.get(key, (time.time(),))[0]
            self._last_cached_at = captured
            with self.cache.tx() as c:
                c.execute('INSERT OR REPLACE INTO responses VALUES(?,?,?)', (cache_key,captured,json.dumps(value)))
        return value

    @property
    def enabled(self):
        return bool(self.settings.market_chart_url and self.settings.market_lookup_url)

    # ------------------------------------------------------------ data source
    def _lookup(self, text):
        url = self.settings.market_lookup_url.format(q=quote(text))
        def fetch():
            data = _json(self.fetcher, url, deadline=self.deadline, errors=self.errors)
            return data if data and data.get('quotes') else None
        data = self._cached(("lookup", self.settings.market_lookup_url, text.lower()), 86400, fetch)
        return [qd for qd in (data or {}).get("quotes", []) if qd.get("symbol") and qd.get("quoteType")]

    def _chart(self, symbol, days=1, interval=None):
        now = int(time.time())
        days = max(1, days)
        period1 = now - int(max(days, 4) * 86400)          # cover weekends/holidays for short windows
        interval = interval or ("5m" if days <= 1 else "30m" if days <= 5 else "1d" if days <= 400 else "1wk")
        url = self.settings.market_chart_url.format(symbol=quote(symbol), period1=period1, period2=now,
                                                    interval=interval)
        ttl = 60 if days <= 5 else 1800
        def fetch():
            data = _json(self.fetcher, url, deadline=self.deadline, errors=self.errors)
            results = ((data or {}).get('chart') or {}).get('result')
            return data if results and isinstance(results[0],dict) and results[0].get('meta') else None
        data = self._cached(("chart", self.settings.market_chart_url, symbol, days, interval), ttl, fetch)
        try:
            return dict(data["chart"]["result"][0], _retrieved_at=self._last_cached_at)
        except (TypeError, KeyError, IndexError):
            return None

    def resolve(self, words, rarity=None, chart_days=1):
        """Subject words -> (symbol, name). Tries the whole subject, then single words, rarest first;
        a word is accepted only if the source returns an instrument whose symbol or name contains it."""
        words = [w for w in words if w]
        if not words:
            return None, None
        order = sorted(words, key=lambda w: rarity(w) if rarity else 0, reverse=True)
        tries = ([" ".join(words)] if len(words) > 1 else []) + order
        for text in tries:
            for qd in self._lookup(text):
                sym = qd["symbol"]
                name = qd.get("longname") or qd.get("shortname") or sym
                hay = (sym.split(".")[0] + " " + name).lower()
                chart = (lambda: self._chart(sym,1)) if chart_days == 1 else (lambda: self._chart(sym,chart_days,interval='1d'))
                if all(t.lower() in hay for t in words) and chart():
                    return sym, name
        return None, None

    # ------------------------------------------------------------ answers
    def _source(self, sym):
        return {"name": self.settings.market_source_name,
                "url": self.settings.market_quote_page.format(symbol=quote(sym))}

    def _disclaimer(self):
        return (f"Market data from {self.settings.market_source_name}; quotes may be delayed. "
                "Informational only, not investment advice.")

    def quote(self, words, rarity=None):
        sym, disp = self.resolve(words, rarity)
        if not sym:
            return None
        r = self._chart(sym, 1)
        m = (r or {}).get("meta") or {}
        price = m.get("regularMarketPrice")
        if price is None:
            return None
        ts = m.get("regularMarketTime")
        if not _positive(price) or not _positive(ts):
            return None
        age = time.time() - ts
        if age < -300 or age > 7 * 86400:
            return None
        # chartPreviousClose is the close before the whole requested range,
        # which can span several sessions. It is not yesterday's close.
        prev = m.get("previousClose")
        zone = _zone(m.get('exchangeTimezoneName')).key
        if not _positive(prev):
            prev = None
        if prev is None:
            daily = self._chart(sym, 7, interval="1d") or {}
            daily_closes = (((daily.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
            earlier = [(t, c) for t, c in zip(daily.get("timestamp") or [], daily_closes)
                       if _positive(t) and _positive(c) and t < ts and _day(t,zone) < _day(ts,zone)]
            prev = max(earlier)[1] if earlier else None
        as_of = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None
        cur = m.get("currency", "")
        change = (price - prev) if prev else None
        pct = (change / prev * 100) if prev else None
        name_out = m.get("longName") or m.get("shortName") or disp
        exch = m.get("fullExchangeName") or m.get("exchangeName") or ""
        lines = [f"{name_out} ({sym}, {exch}): {price:,.2f} {cur} (latest regular-market quote)"]
        if change is not None:
            lines[0] += f"  {change:+,.2f} ({pct:+.2f}%) vs previous close {prev:,.2f}"
        if m.get("regularMarketDayLow") and m.get("regularMarketDayHigh"):
            lines.append(f"Day range {m['regularMarketDayLow']:,.2f} – {m['regularMarketDayHigh']:,.2f}")
        if m.get("fiftyTwoWeekLow") and m.get("fiftyTwoWeekHigh"):
            lines.append(f"52-week range {m['fiftyTwoWeekLow']:,.2f} – {m['fiftyTwoWeekHigh']:,.2f}")
        if m.get("regularMarketVolume"):
            lines.append(f"Volume {m['regularMarketVolume']:,}")
        lines.append(f"As of {as_of} (market time reported by the data source)")
        return {"type": "stock_quote", "scope": "regular_market", "symbol": sym, "name": name_out, "exchange": exch, "currency": cur,
                "exchange_timezone": zone,
                "price": price, "previous_close": prev, "change": change, "change_pct": pct,
                "day_low": m.get("regularMarketDayLow"), "day_high": m.get("regularMarketDayHigh"),
                "week52_low": m.get("fiftyTwoWeekLow"), "week52_high": m.get("fiftyTwoWeekHigh"),
                "volume": m.get("regularMarketVolume"), "as_of": as_of, "delayed": True, "age_seconds": round(age), "text": "\n".join(lines),
                "source": self._source(sym), "disclaimer": self._disclaimer()}

    def history(self, words, days=183, rarity=None):
        sym, disp = self.resolve(words, rarity, chart_days=days)
        if not sym:
            return None
        r = self._chart(sym, days, interval="1d")
        if not r:
            return None
        m = r.get("meta") or {}
        zone = _zone(m.get('exchangeTimezoneName')).key
        ts = r.get("timestamp") or []
        ind = r.get("indicators") or {}
        adjusted = (ind.get("adjclose") or [{}])[0].get("adjclose")
        closes = adjusted or (ind.get("quote") or [{}])[0].get("close") or []
        price_basis = "adjusted close" if adjusted else "close"
        now = time.time()
        start = now - days * 86400
        if len(ts) != len(closes) or any(not _positive(t) or t > now + 300 for t in ts):
            return None
        if any(b <= a for a,b in zip(ts,ts[1:])):
            return None
        rows = sorted((t, c) for t, c in zip(ts, closes) if _positive(c) and start <= t <= now)
        if len({t for t, _ in rows}) != len(rows):
            return None
        weeks, rest = divmod(max(0,int(days)),7)
        weekday = datetime.fromtimestamp(start,_zone(zone)).weekday()
        expected = weeks * 5 + sum((weekday+n) % 7 < 5 for n in range(rest))
        if (len(rows) < 5 or now - rows[-1][0] > 7 * 86400 or rows[0][0] - start > 7 * 86400
                or len(rows) < expected * 0.75 or any(b[0] - a[0] > 10 * 86400 for a, b in zip(rows, rows[1:]))):
            return None
        cur = m.get("currency", "")
        name_out = m.get("longName") or m.get("shortName") or disp
        valid_pairs = {(a, b) for a, b, ca, cb in zip(ts, ts[1:], closes, closes[1:])
                       if _positive(ca) and _positive(cb)}
        a = analyse(rows, return_pairs=valid_pairs, timezone_name=zone)
        lines = [
            f"{name_out} ({sym}) — {_day(rows[0][0],zone)} to {_day(rows[-1][0],zone)}, {len(rows)} trading sessions, {cur}; {price_basis}",
            f"Start {a['start'][1]:,.2f}   End {a['end'][1]:,.2f}   Change {a['change']:+,.2f} ({a['change_pct']:+.2f}%)",
            f"High {a['high'][1]:,.2f} on {_day(a['high'][0],zone)}   Low {a['low'][1]:,.2f} on {_day(a['low'][0],zone)}   "
            f"Average {a['mean']:,.2f}",
            f"Annualised volatility {a['volatility_pct']:.1f}%   Max drawdown {a['max_drawdown_pct']:.1f}% "
            f"({_day(a['drawdown_peak'][0],zone)} → {_day(a['drawdown_trough'][0],zone)})",
        ]
        if a.get("sma20") and a.get("sma50"):
            lines.append(f"20-day average {a['sma20']:,.2f}, 50-day average {a['sma50']:,.2f} → {a['trend']}")
        lines.append("Last available price in each month: " + ", ".join(
            f"{mo} {c:,.2f}" + (f" ({p:+.1f}%)" if p is not None else "") for mo, c, p in a["monthly"]))
        if a.get("best_month") and a.get("worst_month"):
            lines.append(f"Best month {a['best_month'][0]} ({a['best_month'][1]:+.1f}%), "
                         f"worst month {a['worst_month'][0]} ({a['worst_month'][1]:+.1f}%)")
        market_ts = m.get("regularMarketTime")
        if market_ts is not None and (not _positive(market_ts) or market_ts > now + 300 or market_ts < rows[-1][0]):
            return None
        as_of = datetime.fromtimestamp(market_ts or rows[-1][0], timezone.utc).isoformat(
            timespec="seconds")
        lines.append(f"Data as of {as_of}")
        regular = (m.get("currentTradingPeriod") or {}).get("regular") or {}
        incomplete = bool(regular.get("start", 0) <= (market_ts or rows[-1][0]) and
                          regular.get("end", 0) > r.get('_retrieved_at', time.time()) and
                          _day(rows[-1][0],zone) == _day(m.get("regularMarketTime") or rows[-1][0],zone))
        if incomplete:
            lines.append("The latest session is still in progress; its price and the current month's return are provisional.")
        if any(not _positive(c) for c in closes):
            lines.append('Statistics use available prices; volatility omits intervals containing missing prices.')
        return {"type": "stock_history", "symbol": sym, "name": name_out, "currency": cur, "days": days,
                "exchange_timezone": zone,
                "price_basis": price_basis, "incomplete_last_session": incomplete,
                "data_quality": {"observations": len(rows), "expected_weekdays": expected,
                                 "missing_prices": sum(not _positive(c) for c in closes),
                                 "volatility_observations": sum((a[0],b[0]) in valid_pairs for a,b in zip(rows,rows[1:])),
                                 "requested_start": _day(start,zone), "requested_end": _day(now,zone),
                                 "calendar": "Weekday coverage estimate; exchange holidays are not modeled."},
                "analysis": {k: v for k, v in a.items() if k not in ("start", "end", "high", "low", "drawdown_peak",
                                                                     "drawdown_trough")}
                | {"start": [_day(a["start"][0],zone), a["start"][1]], "end": [_day(a["end"][0],zone), a["end"][1]],
                   "high": [_day(a["high"][0],zone), a["high"][1]], "low": [_day(a["low"][0],zone), a["low"][1]]},
                "series": [[_day(t,zone), round(c, 4)] for t, c in rows], "as_of": as_of, "text": "\n".join(lines),
                "source": self._source(sym), "disclaimer": self._disclaimer()}


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def analyse(rows, return_pairs=None, timezone_name=None):
    """rows = [(unix_ts, close)] in time order -> descriptive statistics (no forecasting)."""
    closes = [c for _, c in rows]
    start, end = rows[0], rows[-1]
    high = max(rows, key=lambda r: r[1])
    low = min(rows, key=lambda r: r[1])
    rets = [math.log(b[1] / a[1]) for a, b in zip(rows, rows[1:])
            if a[1] > 0 and b[1] > 0 and (return_pairs is None or (a[0],b[0]) in return_pairs)]
    vol = statistics.pstdev(rets) * math.sqrt(252) * 100 if len(rets) > 2 else 0.0
    peak, mdd, pk, tr = rows[0], 0.0, rows[0], rows[0]
    for r in rows:
        if r[1] > peak[1]:
            peak = r
        dd = (r[1] - peak[1]) / peak[1] * 100
        if dd < mdd:
            mdd, pk, tr = dd, peak, r
    sma = lambda n: sum(closes[-n:]) / n if len(closes) >= n else None
    s20, s50 = sma(20), sma(50)
    trend = None
    if s20 and s50:
        if end[1] > s20 > s50:
            trend = "price above both averages, short-term average above long-term (uptrend)"
        elif end[1] < s20 < s50:
            trend = "price below both averages, short-term average below long-term (downtrend)"
        else:
            trend = "averages crossing (no clear trend)"
    months = {}
    for t, c in rows:
        months[datetime.fromtimestamp(t, _zone(timezone_name)).strftime("%b %Y")] = c
    monthly, prev = [], None
    for mo, c in months.items():
        monthly.append((mo, c, (c - prev) / prev * 100 if prev else None))
        prev = c
    changes = [(mo, p) for mo, _c, p in monthly if p is not None]
    return {"start": start, "end": end, "change": end[1] - start[1],
            "change_pct": (end[1] - start[1]) / start[1] * 100, "high": high, "low": low,
            "mean": sum(closes) / len(closes), "volatility_pct": vol, "max_drawdown_pct": mdd,
            "drawdown_peak": pk, "drawdown_trough": tr, "sma20": s20, "sma50": s50, "trend": trend,
            "monthly": monthly, "best_month": max(changes, key=lambda x: x[1]) if changes else None,
            "worst_month": min(changes, key=lambda x: x[1]) if changes else None}
