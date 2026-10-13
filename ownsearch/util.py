"""URL, text and time helpers shared by every component."""
import hashlib
import ipaddress
import re
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "mc_cid", "mc_eid", "_ga", "_gl", "igshid",
    "ref_src", "ref_url", "spm", "trk", "si", "s_cid", "cmpid", "oly_anon_id", "oly_enc_id",
    "vero_conv", "vero_id", "wickedid", "__hssc", "__hstc", "__hsfp", "hsctatracking",
}
SESSION_PARAMS = {"sid", "sessionid", "session_id", "phpsessid", "jsessionid", "aspsessionid", "cfid", "cftoken"}
SECOND_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "co.in", "org.in", "net.in", "gov.in",
    "ac.in", "nic.in", "res.in", "edu.in", "firm.in", "gen.in", "ind.in", "com.au", "net.au", "org.au",
    "edu.au", "gov.au", "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "com.br", "com.cn", "net.cn",
    "org.cn", "gov.cn", "com.mx", "co.nz", "org.nz", "co.za", "com.sg", "com.tr", "co.kr", "or.kr",
    "com.tw", "com.hk", "com.my", "com.pk", "com.bd", "com.np", "com.lk", "co.id", "com.ar", "com.co",
    "github.io", "gitlab.io", "blogspot.com", "herokuapp.com", "netlify.app", "vercel.app", "pages.dev",
    "wordpress.com", "substack.com", "medium.com", "readthedocs.io", "appspot.com", "web.app",
    "firebaseapp.com", "azurewebsites.net", "cloudfront.net", "s3.amazonaws.com",
}
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PCT = re.compile(r"%([0-9a-fA-F]{2})")
_INVISIBLE = re.compile("[­᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_SPACES = re.compile(r"[ \t\r\f\v   -     　]+")


# ---------------------------------------------------------------- time

def now_ts():
    return time.time()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ts_to_iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds")


def iso_to_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------- text

def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def normalize_text(text):
    """Single-line normalisation: NFKC, invisible characters removed, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text or "").replace("\x00", " ")
    text = _INVISIBLE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_multiline(text, keep_formfeed=False):
    """Collapse whitespace inside lines but keep paragraph breaks (and optional page breaks)."""
    text = unicodedata.normalize("NFKC", text or "").replace("\x00", " ")
    text = _INVISIBLE.sub("", text)
    if keep_formfeed:
        pages = text.split("\f")
        return "\f".join(clean_multiline(p) for p in pages)
    out, blank = [], False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _SPACES.sub(" ", line).strip()
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            blank = True
    return "\n".join(out)


def truncate(text, n):
    if len(text) <= n:
        return text
    cut = text[:n]
    space = cut.rfind(" ")
    return (cut[:space] if space > n * 0.7 else cut) + "…"


# ---------------------------------------------------------------- URLs

def _fix_percent(segment, safe):
    def repl(m):
        ch = chr(int(m.group(1), 16))
        return ch if ch in _UNRESERVED else "%" + m.group(1).upper()
    segment = _PCT.sub(repl, segment)
    return quote(segment, safe=safe + "%")


def _remove_dot_segments(path):
    out = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    result = "/".join(out)
    if path.endswith(("/.", "/..")):
        result += "/"
    return result if result.startswith("/") else "/" + result


def normalize_url(url, base=None):
    """Canonical form used as the identity of a URL everywhere in OwnSearch.

    http(s) URLs: lowercase scheme/host, IDNA host, default port removed, dot segments resolved,
    percent-encoding normalised, fragment dropped, tracking/session parameters removed, query sorted.
    Returns "" for unusable http(s) URLs. Other schemes (file://, local://) are returned trimmed.
    """
    url = (url or "").strip()
    if base:
        try:
            url = urljoin(base, url)
        except ValueError:
            return ""
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return ""
    scheme = p.scheme.lower()
    if scheme not in ("http", "https"):
        return url.split("#", 1)[0] if scheme else url
    host = (p.hostname or "").rstrip(".").lower()
    if not host or p.username or p.password:
        return ""
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
    netloc = f"[{host}]" if ":" in host else host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += f":{port}"
    path = re.sub(r";jsessionid=[^/?#]*", "", p.path or "/", flags=re.I)
    path = _remove_dot_segments(_fix_percent(path, "/:@!$&'()*+,;="))
    params = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        kl = k.lower()
        if kl.startswith("utm_") or kl in TRACKING_PARAMS or kl in SESSION_PARAMS:
            continue
        params.append((k, v))
    params.sort()
    query = urlencode(params, doseq=True, quote_via=quote)
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url):
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def origin_of(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def registrable_domain(host):
    host = (host or "").lower().strip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def host_suffixes(host):
    """docs.python.org -> [docs.python.org, python.org, org]"""
    labels = [x for x in (host or "").lower().split(".") if x]
    return [".".join(labels[i:]) for i in range(len(labels))]


def url_depth(url):
    try:
        path = urlsplit(url).path
    except ValueError:
        return 0
    return len([s for s in path.split("/") if s])


def is_probable_trap(url, max_len=2000):
    """Cheap crawler-trap heuristics: very long URLs, repeating path segments, huge queries."""
    if len(url) > max_len:
        return True
    try:
        p = urlsplit(url)
    except ValueError:
        return True
    segs = [s for s in p.path.split("/") if s]
    if len(segs) > 16:
        return True
    if len(segs) >= 6:
        counts = {}
        for s in segs:
            counts[s] = counts.get(s, 0) + 1
            if counts[s] >= 3:
                return True
    if p.query.count("&") >= 8:
        return True
    return bool(re.search(r"/(?:calendar|cal)/\d{4}/\d{1,2}/\d{1,2}/.*/\d{4}/", p.path))


def file_extension(url):
    try:
        path = urlsplit(url).path
    except ValueError:
        return ""
    last = path.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""
