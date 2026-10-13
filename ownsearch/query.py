"""Query understanding: operators, phrases, exclusions, filters and freshness intent.

Syntax (Brave/Google style):
    word  "exact phrase"  -exclude  -"excluded phrase"  a OR b
    site:example.com  -site:spam.com  filetype:pdf  intitle:word  inurl:word
    lang:en  after:2024-01-01  before:2025-06-30
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .dates import parse_date
from .textproc import STOPWORDS, analyze, stem, tokenize
from .util import iso_to_ts

_LEX = re.compile(r'(-?)(?:(\w+):)?("([^"]*)"?|\S+)')
FRESH_WORDS = {"latest", "newest", "recent", "recently", "today", "yesterday", "tonight", "current", "currently",
               "news", "breaking", "update", "updates", "upcoming", "now", "live", "trending", "announced",
               "released", "new"}
FRESHNESS_WINDOWS = {"day": 86400, "pd": 86400, "week": 7 * 86400, "pw": 7 * 86400, "month": 31 * 86400,
                     "pm": 31 * 86400, "year": 366 * 86400, "py": 366 * 86400}
FILETYPE_ALIASES = {"doc": "docx", "word": "docx", "excel": "xlsx", "xls": "xlsx", "ppt": "pptx", "powerpoint": "pptx",
                    "htm": "web", "html": "web", "webpage": "web", "page": "web", "txt": "text", "image": "image",
                    "img": "image", "jpg": "image", "jpeg": "image", "png": "image"}


@dataclass
class ParsedQuery:
    raw: str
    required: list = field(default_factory=list)      # analysed terms that must match (AND)
    optional: list = field(default_factory=list)      # OR-group terms / stopwords: scored, not required
    phrases: list = field(default_factory=list)       # [[term, ...]] must appear as phrases
    excluded: list = field(default_factory=list)
    excluded_phrases: list = field(default_factory=list)
    sites: list = field(default_factory=list)
    not_sites: list = field(default_factory=list)
    filetypes: list = field(default_factory=list)
    intitle: list = field(default_factory=list)
    inurl: list = field(default_factory=list)
    lang: str = None
    after: float = None
    before: float = None
    freshness: str = None          # None | recent | day | week | month | year
    fresh_intent: bool = False
    surface: list = field(default_factory=list)       # surface words for snippets/highlighting

    @property
    def scoring_terms(self):
        seen, out = set(), []
        for t in self.required + self.optional + [t for p in self.phrases for t in p] + self.intitle:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @property
    def has_text(self):
        return bool(self.required or self.optional or self.phrases or self.intitle or self.inurl)

    @property
    def has_filters(self):
        return bool(self.sites or self.filetypes or self.lang or self.after or self.before or self.freshness
                    in FRESHNESS_WINDOWS)

    def normalized(self):
        return {"required": self.required, "optional": self.optional, "phrases": self.phrases,
                "excluded": self.excluded, "sites": self.sites, "not_sites": self.not_sites,
                "filetypes": self.filetypes, "intitle": self.intitle, "inurl": self.inurl, "lang": self.lang,
                "after": self.after, "before": self.before, "freshness": self.freshness,
                "fresh_intent": self.fresh_intent}


def _date_ts(value):
    iso = parse_date(value)
    return iso_to_ts(iso) if iso else None


def parse_query(raw, freshness=None, site=None, filetype=None, lang=None):
    q = ParsedQuery(raw=raw)
    tokens = list(_LEX.finditer(raw or ""))
    words = []                         # (term, surface, is_stop, or_group)
    or_next = False
    for i, m in enumerate(tokens):
        neg, op, whole, phrase = m.group(1), (m.group(2) or "").lower(), m.group(3), m.group(4)
        value = phrase if phrase is not None else whole
        if not neg and not op and whole == "OR":
            or_next = True
            if words:
                words[-1] = (*words[-1][:3], True)
            continue
        if op in ("site", "domain"):
            host = value.lower().strip().lstrip(".").removeprefix("https://").removeprefix("http://").split("/")[0]
            host = host.removeprefix("www.") if host.count(".") > 1 else host
            if host:
                (q.not_sites if neg else q.sites).append(host)
            continue
        if op in ("filetype", "ext", "type"):
            ft = value.lower().lstrip(".")
            q.filetypes.append(FILETYPE_ALIASES.get(ft, ft))
            continue
        if op == "lang":
            q.lang = value.lower()[:2]
            continue
        if op in ("after", "since"):
            q.after = _date_ts(value)
            continue
        if op in ("before", "until"):
            q.before = _date_ts(value)
            continue
        if op in ("intitle", "allintitle"):
            q.intitle.extend(analyze(value))
            continue
        if op == "inurl":
            q.inurl.extend(analyze(value))
            continue
        if op and op not in ("http", "https"):
            value = f"{op} {value}"          # unknown "foo:bar" is plain text
        if phrase is not None:
            terms = analyze(phrase)
            if not terms:
                continue
            if neg:
                q.excluded_phrases.append(terms)
            elif len(terms) == 1:
                words.append((terms[0], phrase, False, or_next))
            else:
                q.phrases.append(terms)
                q.surface.extend(tokenize(phrase))
            or_next = False
            continue
        for surf in tokenize(value):
            term = stem(surf)
            if neg:
                q.excluded.append(term)
            else:
                words.append((term, surf, surf in STOPWORDS, or_next))
            or_next = False
    content = [w for w in words if not w[2]]
    if not content and not q.phrases:
        content = words                     # query made only of stopwords ("the who"): use them
    for term, surf, is_stop, in_or in words:
        q.surface.append(surf)
    seen = set()
    for term, surf, is_stop, in_or in words:
        if term in seen:
            continue
        seen.add(term)
        # intent words ("latest", "current", "news") steer freshness; they are scored but never required
        if (term, surf, is_stop, in_or) in content and not in_or and (surf not in FRESH_WORDS or len(content) == 1):
            q.required.append(term)
        else:
            q.optional.append(term)
    if freshness:
        q.freshness = str(freshness).lower()
    if site:
        q.sites.extend(s.strip().lower() for s in str(site).split(",") if s.strip())
    if filetype:
        q.filetypes.extend(FILETYPE_ALIASES.get(f.strip().lower(), f.strip().lower())
                           for f in str(filetype).split(",") if f.strip())
    if lang:
        q.lang = str(lang).lower()[:2]
    low = {t.lower() for t in tokenize(raw)}
    year = datetime.now(timezone.utc).year
    if low & FRESH_WORDS or str(year) in low or str(year - 1) in low:
        q.fresh_intent = True
    if q.freshness in FRESHNESS_WINDOWS and not q.after:
        q.after = datetime.now(timezone.utc).timestamp() - FRESHNESS_WINDOWS[q.freshness]
    return q
