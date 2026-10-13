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
from urllib.parse import quote

from .fetcher import FetchError, Fetcher

_cache = {}
_lock = threading.Lock()


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


def _json(fetcher, url, max_bytes=8_000_000):
    try:
        res = fetcher.fetch(url, accept="application/json", max_bytes=max_bytes, retries=1)
    except FetchError:
        return None
    if res.status != 200:
        return None
    try:
        return json.loads(res.body.decode("utf-8", "replace"))
    except ValueError:
        return None


def _day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


class Market:
    def __init__(self, settings):
        self.settings = settings
        self.fetcher = Fetcher(settings)

    @property
    def enabled(self):
        return bool(self.settings.market_chart_url and self.settings.market_lookup_url)

    # ------------------------------------------------------------ data source
    def _lookup(self, text):
        url = self.settings.market_lookup_url.format(q=quote(text))
        data = _cached(("lookup", text.lower()), 86400, lambda: _json(self.fetcher, url))
        return [qd for qd in (data or {}).get("quotes", []) if qd.get("symbol") and qd.get("quoteType")]

    def _chart(self, symbol, days=1):
        now = int(time.time())
        days = max(1, days)
        period1 = now - int(max(days, 4) * 86400)          # cover weekends/holidays for short windows
        interval = "5m" if days <= 1 else "30m" if days <= 5 else "1d" if days <= 400 else "1wk"
        url = self.settings.market_chart_url.format(symbol=quote(symbol), period1=period1, period2=now,
                                                    interval=interval)
        ttl = 60 if days <= 5 else 1800
        data = _cached(("chart", symbol, days), ttl, lambda: _json(self.fetcher, url))
        try:
            return data["chart"]["result"][0]
        except (TypeError, KeyError, IndexError):
            return None

    def resolve(self, words, rarity=None):
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
                if all(t.lower() in hay for t in text.split()) and self._chart(sym, 1):
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
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        ts = m.get("regularMarketTime")
        as_of = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None
        cur = m.get("currency", "")
        change = (price - prev) if prev else None
        pct = (change / prev * 100) if prev else None
        name_out = m.get("longName") or m.get("shortName") or disp
        exch = m.get("fullExchangeName") or m.get("exchangeName") or ""
        lines = [f"{name_out} ({sym}, {exch}): {price:,.2f} {cur}"]
        if change is not None:
            lines[0] += f"  {change:+,.2f} ({pct:+.2f}%) vs previous close {prev:,.2f}"
        if m.get("regularMarketDayLow") and m.get("regularMarketDayHigh"):
            lines.append(f"Day range {m['regularMarketDayLow']:,.2f} – {m['regularMarketDayHigh']:,.2f}")
        if m.get("fiftyTwoWeekLow") and m.get("fiftyTwoWeekHigh"):
            lines.append(f"52-week range {m['fiftyTwoWeekLow']:,.2f} – {m['fiftyTwoWeekHigh']:,.2f}")
        if m.get("regularMarketVolume"):
            lines.append(f"Volume {m['regularMarketVolume']:,}")
        lines.append(f"As of {as_of} (market time reported by the data source)")
        return {"type": "stock_quote", "symbol": sym, "name": name_out, "exchange": exch, "currency": cur,
                "price": price, "previous_close": prev, "change": change, "change_pct": pct,
                "day_low": m.get("regularMarketDayLow"), "day_high": m.get("regularMarketDayHigh"),
                "week52_low": m.get("fiftyTwoWeekLow"), "week52_high": m.get("fiftyTwoWeekHigh"),
                "volume": m.get("regularMarketVolume"), "as_of": as_of, "text": "\n".join(lines),
                "source": self._source(sym), "disclaimer": self._disclaimer()}

    def history(self, words, days=183, rarity=None):
        sym, disp = self.resolve(words, rarity)
        if not sym:
            return None
        r = self._chart(sym, days)
        if not r:
            return None
        m = r.get("meta") or {}
        ts = r.get("timestamp") or []
        ind = r.get("indicators") or {}
        closes = ((ind.get("adjclose") or [{}])[0].get("adjclose")
                  or (ind.get("quote") or [{}])[0].get("close") or [])
        rows = [(t, c) for t, c in zip(ts, closes) if c is not None]
        if len(rows) < 5:
            return None
        cur = m.get("currency", "")
        name_out = m.get("longName") or m.get("shortName") or disp
        a = analyse(rows)
        lines = [
            f"{name_out} ({sym}) — {_day(rows[0][0])} to {_day(rows[-1][0])}, {len(rows)} trading sessions, {cur}",
            f"Start {a['start'][1]:,.2f}   End {a['end'][1]:,.2f}   Change {a['change']:+,.2f} ({a['change_pct']:+.2f}%)",
            f"High {a['high'][1]:,.2f} on {_day(a['high'][0])}   Low {a['low'][1]:,.2f} on {_day(a['low'][0])}   "
            f"Average {a['mean']:,.2f}",
            f"Annualised volatility {a['volatility_pct']:.1f}%   Max drawdown {a['max_drawdown_pct']:.1f}% "
            f"({_day(a['drawdown_peak'][0])} → {_day(a['drawdown_trough'][0])})",
        ]
        if a.get("sma20") and a.get("sma50"):
            lines.append(f"20-day average {a['sma20']:,.2f}, 50-day average {a['sma50']:,.2f} → {a['trend']}")
        lines.append("Monthly closes: " + ", ".join(
            f"{mo} {c:,.2f}" + (f" ({p:+.1f}%)" if p is not None else "") for mo, c, p in a["monthly"]))
        if a.get("best_month") and a.get("worst_month"):
            lines.append(f"Best month {a['best_month'][0]} ({a['best_month'][1]:+.1f}%), "
                         f"worst month {a['worst_month'][0]} ({a['worst_month'][1]:+.1f}%)")
        as_of = datetime.fromtimestamp(m.get("regularMarketTime") or rows[-1][0], timezone.utc).isoformat(
            timespec="seconds")
        lines.append(f"Data as of {as_of}")
        return {"type": "stock_history", "symbol": sym, "name": name_out, "currency": cur, "days": days,
                "analysis": {k: v for k, v in a.items() if k not in ("start", "end", "high", "low", "drawdown_peak",
                                                                     "drawdown_trough")}
                | {"start": [_day(a["start"][0]), a["start"][1]], "end": [_day(a["end"][0]), a["end"][1]],
                   "high": [_day(a["high"][0]), a["high"][1]], "low": [_day(a["low"][0]), a["low"][1]]},
                "series": [[_day(t), round(c, 4)] for t, c in rows], "as_of": as_of, "text": "\n".join(lines),
                "source": self._source(sym), "disclaimer": self._disclaimer()}


def analyse(rows):
    """rows = [(unix_ts, close)] in time order -> descriptive statistics (no forecasting)."""
    closes = [c for _, c in rows]
    start, end = rows[0], rows[-1]
    high = max(rows, key=lambda r: r[1])
    low = min(rows, key=lambda r: r[1])
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
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
        months[datetime.fromtimestamp(t, timezone.utc).strftime("%b %Y")] = c
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
