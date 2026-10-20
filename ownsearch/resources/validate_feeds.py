#!/usr/bin/env python3
"""Check every feed in news_feeds.txt; writes news_feeds.valid.txt with only live, parseable feeds.
Usage: python validate_feeds.py [news_feeds.txt]   (needs: pip install feedparser requests)"""
import sys, requests, feedparser
from concurrent.futures import ThreadPoolExecutor
src = sys.argv[1] if len(sys.argv) > 1 else "news_feeds.txt"
urls = [l.strip() for l in open(src) if l.strip() and not l.startswith("#")]
def check(u):
    try:
        r = requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0 (feed-validator)"})
        f = feedparser.parse(r.content)
        return u, r.status_code == 200 and len(f.entries) > 0, f"{r.status_code} entries={len(f.entries)}"
    except Exception as e:
        return u, False, type(e).__name__
with ThreadPoolExecutor(16) as ex: res = list(ex.map(check, urls))
for u, ok, info in res: print("OK  " if ok else "FAIL", info, u)
open("news_feeds.valid.txt", "w").write("\n".join(u for u, ok, _ in res if ok) + "\n")
print(f"{sum(ok for _,ok,_ in res)}/{len(res)} feeds alive -> news_feeds.valid.txt")
