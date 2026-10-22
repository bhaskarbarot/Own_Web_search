"""HTML extraction: title, main content, headings, metadata, dates, links with anchor text, feeds.

Hidden elements (``hidden``, ``aria-hidden``, ``display:none``) are not indexed: they are a spam signal
and a common carrier for prompt-injection text aimed at AI agents.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..dates import parse_date
from ..util import clean_multiline, normalize_text

SKIP = {"script", "style", "noscript", "svg", "canvas", "template", "iframe", "object", "embed", "math",
        "select", "datalist", "button", "dialog"}
BOILER = {"nav", "footer", "aside", "form", "menu"}
MAIN = {"main", "article"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr", "keygen"}
BLOCK = {"p", "div", "br", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
         "td", "th", "table", "section", "article", "main", "header", "footer", "nav", "aside", "blockquote",
         "pre", "figure", "figcaption", "hr", "form", "address", "details", "summary", "caption", "title"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|em|rem)?\s*(?:;|$)", re.I)
_BAD_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "about:", "blob:", "sms:", "callto:", "file:")
_BOILER_ATTR = re.compile(r"(?:^|[\s_-])(?:nav|navbar|navigation|menu|menubar|footer|header|masthead|sidebar|"
                          r"breadcrumbs?|cookie|consent|banner|skip|skiplink|social|share|sharing|toolbar|subnav|"
                          r"pagination|related|promo|advert|ads)(?:[\s_-]|$)", re.I)
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/rdf+xml")
DATE_META = ("article:published_time", "og:published_time", "datepublished", "date", "dc.date", "dc.date.issued",
             "dcterms.created", "dcterms.issued", "pubdate", "publish-date", "publish_date", "sailthru.date",
             "parsely-pub-date", "citation_publication_date", "citation_date", "release_date")
MODIFIED_META = ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified", "last-modified",
                 "dc.date.modified")


def _detect_code_lang(attrs_str, code):
    m = re.search(r"\b(?:language|lang)-([a-zA-Z0-9_+-]+)", attrs_str, re.I)
    if m:
        lang = m.group(1).lower()
        if lang in ("python", "py"): return "python"
        if lang in ("javascript", "js"): return "javascript"
        if lang in ("typescript", "ts"): return "typescript"
        return lang
    for l in ("python", "javascript", "typescript", "bash", "sql", "rust", "cpp", "c", "html", "css", "json"):
        if re.search(rf"\b{l}\b", attrs_str, re.I):
            return l
    if re.search(r"(?:^\s*def\s+\w+|^\s*import\s+\w+|^\s*from\s+\w+\s+import|class\s+\w+:|print\()", code, re.M):
        return "python"
    if re.search(r"(?:^\s*function\s+\w+|^\s*const\s+\w+\s*=|^\s*let\s+\w+\s*=|console\.log\()", code, re.M):
        return "javascript"
    if re.search(r"^\s*(?:SELECT\s+|INSERT\s+INTO|CREATE\s+TABLE)", code, re.I | re.M):
        return "sql"
    return ""


class _Parser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.stack = []                 # [tag, skip, hidden, boiler, main]
        self.skip = self.hidden = self.boiler = self.main = 0
        self.title_parts, self.in_title, self.title_done = [], False, False
        self.blocks = {"main": [], "normal": [], "boiler": []}
        self.cur = []
        self.cur_link_chars = 0
        self.cur_zone = "normal"
        self.headings = []
        self.heading_buf = None
        self.current_heading = ""
        self.markdown_blocks = []
        self.code_blocks = []
        self.in_pre = 0
        self.code_buf = []
        self.code_lang = ""
        self.links = []
        self.link_buf = None
        self.meta = {}
        self.feeds = []
        self.canonical = None
        self.lang = ""
        self.images = []
        self.ld_json = []
        self.ld_buf = None
        self.time_values = []
        self.hidden_chars = 0
        self.text_chars = 0

    # ----------------------------------------------------------- helpers
    def _zone(self):
        if self.main:
            return "main"
        if self.boiler:
            return "boiler"
        return "normal"

    def _flush(self):
        if self.cur:
            text = " ".join("".join(self.cur).split())
            if text:
                zone = self.cur_zone
                # mostly-link blocks (menus, tag clouds, "related" lists) are boilerplate
                if (zone != "boiler" and self.heading_buf is None and len(text) < 400
                        and self.cur_link_chars > 0.6 * len(text.replace(" ", ""))):
                    zone = "boiler"
                self.blocks[zone].append(text)
                if not self.in_pre and self.heading_buf is None:
                    self.markdown_blocks.append((zone, text))
            self.cur = []
        self.cur_link_chars = 0

    def _abs(self, href):
        href = (href or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(_BAD_SCHEMES):
            return None
        try:
            return urljoin(self.base, href)
        except ValueError:
            return None

    # ----------------------------------------------------------- tags
    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and a.get("href") and not getattr(self, "_base_set", False):
            self.base = urljoin(self.base, a["href"])
            self._base_set = True
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"].split("-")[0].lower()[:5]
        if tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("itemprop") or a.get("http-equiv") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
            if a.get("charset"):
                self.meta.setdefault("charset", a["charset"])
            return
        if tag == "link":
            rel = a.get("rel", "").lower().split()
            href = self._abs(a.get("href"))
            if href and "canonical" in rel and not self.canonical:
                self.canonical = href
            if href and "alternate" in rel and a.get("type", "").lower() in FEED_TYPES:
                self.feeds.append(href)
            return
        if tag == "img":
            if not (self.skip or self.hidden):
                alt = normalize_text(a.get("alt", ""))
                src = self._abs(a.get("src") or a.get("data-src"))
                if src and len(self.images) < 100:
                    self.images.append({"src": src, "alt": alt[:300]})
                if alt and len(alt) > 3:
                    self.cur.append(alt)
            return
        if tag in ("br", "hr", "wbr") or tag in VOID:
            if tag in ("br", "hr"):
                self._flush()
            return
        hidden = ("hidden" in a or a.get("aria-hidden", "").lower() == "true"
                  or bool(_HIDDEN_STYLE.search(a.get("style", ""))))
        skip = tag in SKIP and not (tag == "script" and "ld+json" in a.get("type", "").lower())
        boiler = tag in BOILER or (tag == "header" and not self.main) or (
            not self.main and tag in ("div", "ul", "section", "aside", "header", "footer", "p", "span", "ol")
            and bool(_BOILER_ATTR.search(a.get("id", "") + " " + a.get("class", "") + " " + a.get("role", ""))))
        main = tag in MAIN or a.get("role", "").lower() == "main"
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self.ld_buf = []
            skip = True
        if tag in BLOCK:
            self._flush()
        self.stack.append((tag, skip, hidden, boiler, main))
        self.skip += skip
        self.hidden += hidden
        self.boiler += boiler
        self.main += main
        self.cur_zone = self._zone()
        if tag == "title" and not self.title_done and not self.skip:
            self.in_title = True
        elif tag in HEADINGS and not (self.skip or self.hidden):
            self.heading_buf = []
        elif tag == "pre" and not (self.skip or self.hidden):
            self.in_pre += 1
            attrs_str = " ".join(f"{k} {v}" for k, v in attrs)
            self.code_lang = _detect_code_lang(attrs_str, "")
            self.code_buf = []
        elif tag == "code" and self.in_pre and not (self.skip or self.hidden):
            if not self.code_lang:
                attrs_str = " ".join(f"{k} {v}" for k, v in attrs)
                self.code_lang = _detect_code_lang(attrs_str, "")
        elif tag == "a":
            href = self._abs(a.get("href"))
            if href:
                rel = a.get("rel", "").lower()
                self.link_buf = [href, [], any(x in rel for x in ("nofollow", "sponsored", "ugc"))]
        elif tag == "time" and a.get("datetime"):
            self.time_values.append((a["datetime"], bool(self.main)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not any(item[0] == tag for item in self.stack):
            return
        while self.stack:
            t, skip, hidden, boiler, main = self.stack.pop()
            self.skip -= skip
            self.hidden -= hidden
            self.boiler -= boiler
            self.main -= main
            self._close(t)
            if t == tag:
                break
        self.cur_zone = self._zone()

    def _close(self, tag):
        if tag in BLOCK:
            self._flush()
        if tag == "title" and self.in_title:
            self.in_title = False
            if normalize_text(" ".join(self.title_parts)):
                self.title_done = True
        elif tag in HEADINGS and self.heading_buf is not None:
            text = normalize_text(" ".join(self.heading_buf))
            if text:
                level = HEADINGS.get(tag, 2)
                self.headings.append((level, text[:300]))
                self.current_heading = text[:300]
                self.markdown_blocks.append((self.cur_zone, f"{'#' * level} {text[:300]}"))
            self.heading_buf = None
        elif tag == "pre":
            if self.in_pre > 0:
                self.in_pre -= 1
            code_text = "".join(self.code_buf).rstrip()
            lines = code_text.splitlines()
            while lines and not lines[0].strip():
                lines.pop(0)
            clean_code = "\n".join(lines).rstrip()
            if len(clean_code) >= 10:
                lang = self.code_lang or _detect_code_lang("", clean_code)
                self.code_blocks.append({
                    "code": clean_code,
                    "language": lang or ("python" if any(k in clean_code for k in ("def ", "import ", "print(")) else ""),
                    "heading": self.current_heading
                })
                self.markdown_blocks.append((self.cur_zone, f"```{lang}\n{clean_code}\n```"))
            self.code_buf = []
            self.code_lang = ""
        elif tag == "li" and self.markdown_blocks:
            z, t = self.markdown_blocks[-1]
            if not t.startswith(("- ", "#", "```")):
                self.markdown_blocks[-1] = (z, f"- {t}")
        elif tag == "a" and self.link_buf is not None:
            href, parts, nofollow = self.link_buf
            if len(self.links) < 5000:
                self.links.append((href, normalize_text(" ".join(parts))[:200], nofollow))
            self.link_buf = None
        elif tag == "script" and self.ld_buf is not None:
            self.ld_json.append("".join(self.ld_buf))
            self.ld_buf = None

    def handle_data(self, data):
        if self.ld_buf is not None:
            self.ld_buf.append(data)
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip:
            return
        if self.in_pre > 0 and not self.hidden:
            self.code_buf.append(data)
        text = data.strip()
        if not text:
            if self.cur:
                self.cur.append(" ")
            return
        if self.hidden:
            self.hidden_chars += len(text)
            return
        self.text_chars += len(text)
        self.cur.append(re.sub(r"\s+", " ", data))
        if self.heading_buf is not None:
            self.heading_buf.append(text)
        if self.link_buf is not None:
            self.link_buf[1].append(text)
            self.cur_link_chars += len(text.replace(" ", ""))

    def close(self):
        super().close()
        while self.stack:
            t = self.stack.pop()[0]
            self._close(t)
        self._flush()


def _walk_ld(obj, out, depth=0):
    if depth > 6:
        return
    if isinstance(obj, list):
        for x in obj[:50]:
            _walk_ld(x, out, depth + 1)
    elif isinstance(obj, dict):
        for k in ("datePublished", "dateCreated", "uploadDate"):
            if k in obj and "published" not in out:
                out["published"] = obj[k]
        if "dateModified" in obj and "modified" not in out:
            out["modified"] = obj["dateModified"]
        if "headline" in obj and "headline" not in out and isinstance(obj["headline"], str):
            out["headline"] = obj["headline"]
        if "@type" in obj and "type" not in out:
            out["type"] = obj["@type"] if isinstance(obj["@type"], str) else str(obj["@type"])
        for v in obj.values():
            if isinstance(v, (list, dict)):
                _walk_ld(v, out, depth + 1)


def extract_html(html, base_url=""):
    p = _Parser(base_url)
    try:
        p.feed(html)
        p.close()
    except Exception:                       # malformed markup: keep whatever was parsed
        try:
            p._flush()
        except Exception:
            pass
    meta = p.meta
    ld = {}
    for raw in p.ld_json[:10]:
        try:
            _walk_ld(json.loads(raw.strip()), ld)
        except ValueError:
            continue
    title = normalize_text(" ".join(p.title_parts))
    if not title:
        title = normalize_text(meta.get("og:title") or ld.get("headline") or "")
    if not title and p.headings:
        title = p.headings[0][1]
    main_text = "\n".join(p.blocks["main"])
    normal_text = "\n".join(p.blocks["normal"])
    if len(main_text) >= 250:
        body = main_text
    else:
        body = "\n".join(x for x in (main_text, normal_text) if x)
        if len(body) < 80:
            body = "\n".join(x for x in (body, "\n".join(p.blocks["boiler"])) if x)

    main_md = [text for zone, text in p.markdown_blocks if zone == "main"]
    if len("\n\n".join(main_md)) >= 200:
        md_body = "\n\n".join(main_md)
    else:
        normal_md = [text for zone, text in p.markdown_blocks if zone != "boiler"]
        md_body = "\n\n".join(normal_md)
        if len(md_body) < 80:
            md_body = "\n\n".join(text for zone, text in p.markdown_blocks)

    if title and not md_body.startswith(f"# {title}"):
        markdown_output = f"# {title}\n\n{md_body}".strip()
    else:
        markdown_output = md_body.strip()

    robots = (meta.get("robots", "") + "," + meta.get("ownsearchbot", "")).lower()
    published = None
    for key in DATE_META:
        if meta.get(key):
            published = parse_date(meta[key])
            if published:
                break
    if not published and ld.get("published"):
        published = parse_date(ld["published"])
    if not published:
        for value, in_main in p.time_values[:5]:
            published = parse_date(value)
            if published:
                break
    modified = None
    for key in MODIFIED_META:
        if meta.get(key):
            modified = parse_date(meta[key])
            if modified:
                break
    if not modified and ld.get("modified"):
        modified = parse_date(ld["modified"])
    lang = p.lang or (meta.get("content-language", "").split(",")[0].split("-")[0].lower()[:5])
    description = normalize_text(meta.get("description") or meta.get("og:description") or "")
    return {
        "title": title[:1000],
        "text": clean_multiline(body),
        "markdown": markdown_output,
        "code_blocks": p.code_blocks,
        "headings": [h for _, h in p.headings[:100]],
        "description": description[:2000],
        "links": p.links,
        "feeds": p.feeds,
        "canonical": p.canonical,
        "lang": lang,
        "published_at": published,
        "modified_at": modified,
        "noindex": "noindex" in robots or "none" in robots,
        "nofollow": "nofollow" in robots or "none" in robots,
        "images": p.images,
        "hidden_chars": p.hidden_chars,
        "text_chars": p.text_chars,
        "metadata": {k: v[:500] for k, v in meta.items() if k in (
            "description", "keywords", "author", "og:type", "og:site_name", "og:image", "twitter:image", "generator",
            "article:section", "article:tag")} | ({"schema_type": ld["type"]} if ld.get("type") else {}),
    }
