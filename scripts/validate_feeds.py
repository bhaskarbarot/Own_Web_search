#!/usr/bin/env python3
"""Explicit, bounded feed health audit. Optional output removes confirmed dead/empty feeds only."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ownsearch.config import Settings
from ownsearch.feeds import registry,check_updates
from ownsearch.live import PageClient

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',default=Settings().news_feeds_file)
    p.add_argument('--output');p.add_argument('--report',required=True);p.add_argument('--budget',type=float,default=30);p.add_argument('--limit',type=int,default=20)
    a=p.parse_args();feeds,errors=registry(Path(a.input).read_text().splitlines())
    settings=Settings(fetch_timeout=2,discovery_max_requests=max(1,a.limit))
    client=PageClient(settings,time.monotonic()+max(0,a.budget));results=[];dead=set()
    for feed in feeds[:max(0,a.limit)]:
        if time.monotonic()>=client.deadline:break
        try:
            result=check_updates(feed,client)
            if result.get('http_status') in (404,410) or result['status']=='empty':dead.add(feed.url)
        except Exception as exc:result={'url':feed.url,'status':'unavailable','error':str(exc)}
        results.append(result)
    if a.output:
        Path(a.output).write_text('# url\tlang\tregion\tcategory\n'+''.join(f'{f.url}\t{f.lang}\t{f.region}\t{f.category}\n' for f in feeds if f.url not in dead))
    Path(a.report).write_text(json.dumps({'format_errors':errors,'checks':results,'removed':sorted(dead),'unchecked':len(feeds)-len(results)},indent=2))
if __name__=='__main__':main()
