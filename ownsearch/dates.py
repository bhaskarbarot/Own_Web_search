"""Date extraction for freshness: ISO-8601, RFC-822, PDF dates, common human formats and URL paths."""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def _valid(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt.year < 1990 or dt > now + timedelta(days=2):
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def is_valid_date(iso_str):
    """Return True if iso_str represents a valid parsed ISO date within allowable bounds."""
    if not iso_str:
        return False
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return 1990 <= dt.year and dt <= now + timedelta(days=2)
    except (ValueError, TypeError):
        return False


def start_of_today_utc():
    """Return the UNIX timestamp for the start of today (00:00:00 UTC)."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()


def parse_date(value):
    """Return an ISO-8601 UTC string or None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or len(s) > 100:
        return None
    if s.startswith("D:"):                                   # PDF date D:YYYYMMDDHHmmSS+HH'mm'
        m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", s)
        if m:
            parts = [int(x) if x else d for x, d in zip(m.groups(), (0, 1, 1, 0, 0, 0))]
            try:
                return _valid(datetime(*parts))
            except ValueError:
                return None
    try:
        return _valid(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    try:
        return _valid(parsedate_to_datetime(s))
    except (TypeError, ValueError, IndexError):
        pass
    low = s.lower()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", low)
    if m:
        try:
            return _valid(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r",?\s+(\d{4})", low)
    if m:
        try:
            return _valid(datetime(int(m.group(3)), _MONTHS[m.group(2)[:3]], int(m.group(1))))
        except ValueError:
            pass
    m = re.search(_MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", low)
    if m:
        try:
            return _valid(datetime(int(m.group(3)), _MONTHS[m.group(1)[:3]], int(m.group(2))))
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", low)
    if m:
        try:
            return _valid(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return None


def date_from_url(url):
    m = re.search(r"/((?:19|20)\d{2})[/-](0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])(?:[/-]|$)", url or "")
    if m:
        try:
            return _valid(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None
    return None


_UNIT_DAYS = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}     # calendar units (date-format grammar)
_NUMBER_WORDS = dict(zip("one two three four five six seven eight nine ten eleven twelve".split(), range(1, 13)))


def parse_duration(text):
    """Span of time mentioned in text ("last 6 months", "past 2 years") -> days, or None."""
    words = re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", (text or "").lower())
    for i, w in enumerate(words[:-1]):
        count = int(w) if w.isdigit() else _NUMBER_WORDS.get(w)
        if count is not None:
            unit = words[i + 1].rstrip("s")
            if unit in _UNIT_DAYS:
                return max(1, round(count * _UNIT_DAYS[unit]))
    return None


def parse_month_period(text):
    """Calendar-format grammar, e.g. September 2026, as a half-open UTC range."""
    match = re.search(_MONTH_RE + r"\s+(\d{4})\b", (text or '').lower())
    if not match:
        return None
    month, year = _MONTHS[match[1][:3]], int(match[2])
    if not 1990 <= year <= 9998:
        return None
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    return start.timestamp(), end.timestamp() - 0.001

