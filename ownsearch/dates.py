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
