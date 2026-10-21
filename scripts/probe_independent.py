#!/usr/bin/env python3
"""Probe configured starting pages directly. Availability only, not relevance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ownsearch.config import Settings
from ownsearch.webfetch import OriginState,WebFetchSession
from ownsearch.util import origin_of


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    output=Path(args.output)
    if output.exists():raise SystemExit('Refusing to overwrite earlier evidence')
    cfg=replace(Settings.load(),fetch_timeout=3,max_requests_per_query=6)
    urls=cfg.starting_urls()
    origins=OriginState(cfg.origin_cache_entries)
    allowed={origin_of(url) for url in urls}
    def probe(url):
        cancel=threading.Event()
        session=WebFetchSession(cfg,cancel,origins);session.allowed_origins=allowed
        start=time.perf_counter()
        row={'requested_url':url}
        try:
            page=session.crawl(url,time.monotonic()+8)
            row.update(status='fetched',final_url=page.url,kind=page.kind,
                       title=page.item.title if page.item else None,
                       fetched_text_chars=len(page.item.content) if page.item else 0,
                       discovered_links=len(page.links))
        except Exception as error:
            row.update(status=getattr(error,'kind','error'),detail=str(error)[:300])
        finally:cancel.set()
        row.update(took_ms=round((time.perf_counter()-start)*1000,3),request_attempts=session.requests,
                   decoded_bytes=session.decoded_bytes,budget_bytes=session.budget_bytes)
        return row
    with ThreadPoolExecutor(max_workers=min(4,max(1,len(urls)))) as pool:
        rows=list(pool.map(probe,urls))
    report={'scope':'One direct starting-page attempt per configured URL; robots enforced. Not query relevance, domain-wide availability, or unlimited access.',
            'sources':rows,'fetched_count':sum(row['status']=='fetched' for row in rows),'attempted':len(rows)}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
