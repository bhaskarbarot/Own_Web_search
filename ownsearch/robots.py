"""robots.txt (RFC 9309) parsing and matching, plus Crawl-delay and Sitemap directives."""
import re
from urllib.parse import urlsplit

_PCT = re.compile(r"%([0-9a-fA-F]{2})")


def _norm_path(path):
    # compare in a canonical percent-encoding: decode unreserved, uppercase the rest
    def repl(m):
        ch = chr(int(m.group(1), 16))
        return ch if (ch.isalnum() and ch.isascii()) or ch in "-._~" else "%" + m.group(1).upper()
    return _PCT.sub(repl, path)


class RobotsPolicy:
    """allow-all / disallow-all / parsed rules for one user-agent token."""

    def __init__(self, rules=None, crawl_delay=None, sitemaps=None, mode="rules", status=None):
        self.rules = rules or []          # [(pattern, allow, compiled_regex)]
        self.crawl_delay = crawl_delay
        self.sitemaps = sitemaps or []
        self.mode = mode                  # rules | allow_all | disallow_all
        self.status = status

    @classmethod
    def allow_all(cls, status=None):
        return cls(mode="allow_all", status=status)

    @classmethod
    def disallow_all(cls, status=None):
        return cls(mode="disallow_all", status=status)

    @classmethod
    def parse(cls, text, token, status=200):
        token = token.lower()
        groups = []                       # [(agents, rules, delay)]
        sitemaps = []
        cur = None
        last_was_agent = False
        for raw in text.splitlines()[:20000]:
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower().replace("_", "-")
            if key == "sitemap":
                if value:
                    sitemaps.append(value)
                continue
            if key in ("user-agent", "useragent"):
                if cur is None or not last_was_agent:
                    cur = ([], [], None)
                    groups.append(cur)
                cur[0].append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if cur is None:
                continue
            if key in ("allow", "disallow"):
                if key == "disallow" and not value:
                    continue              # empty Disallow = allow everything
                cur[1].append((value, key == "allow"))
            elif key == "crawl-delay":
                try:
                    groups[-1] = cur = (cur[0], cur[1], float(value))
                except ValueError:
                    pass

        def agent_matches(agent):
            a = agent.split("/")[0].strip()
            return a and a != "*" and (a == token or token.startswith(a))

        chosen = [g for g in groups if any(agent_matches(a) for a in g[0])]
        if not chosen:
            chosen = [g for g in groups if "*" in g[0]]
        rules, delay = [], None
        for agents, grules, gdelay in chosen:
            for pattern, allow in grules:
                rules.append((pattern, allow, cls._compile(pattern)))
            if gdelay is not None:
                delay = gdelay if delay is None else min(delay, gdelay)
        return cls(rules, delay, sitemaps, "rules", status)

    @staticmethod
    def _compile(pattern):
        pattern = _norm_path(pattern)
        end = pattern.endswith("$")
        if end:
            pattern = pattern[:-1]
        return re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if end else ""))

    def allowed(self, url):
        if self.mode == "allow_all":
            return True
        if self.mode == "disallow_all":
            return False
        p = urlsplit(url)
        path = _norm_path((p.path or "/") + ("?" + p.query if p.query else ""))
        if path == "/robots.txt":
            return True
        best_len, best_allow = -1, True
        for pattern, allow, rx in self.rules:
            if rx.match(path):
                n = len(pattern)
                if n > best_len or (n == best_len and allow):
                    best_len, best_allow = n, allow
        return best_allow

