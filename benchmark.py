#!/usr/bin/env python3
"""Read-only snapshot benchmark against an existing corpus. Never writes the source index."""
import argparse,json,sqlite3,sys,tempfile,time,shutil,statistics
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-data-dir',required=True);p.add_argument('--output',required=True)
    p.add_argument('--engine-root',default=str(Path(__file__).resolve().parent));p.add_argument('--reindex',action='store_true')
    p.add_argument('--queries',default=str(Path(__file__).resolve().parent/'eval/queries.jsonl'))
    p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    sys.path.insert(0,str(Path(a.engine_root).resolve()))
    from ownsearch.config import Settings
    from ownsearch.engine import SearchEngine
    from ownsearch.query import parse_query
    from eval.run_eval import bootstrap,quantile
    src=Path(a.source_data_dir).resolve()
    with tempfile.TemporaryDirectory(prefix='ownsearch-scale-') as tmp:
        root=Path(tmp)
        source=sqlite3.connect('file:'+str(src/'ownsearch.db')+'?mode=ro',uri=True)
        dest=sqlite3.connect(root/'ownsearch.db');source.backup(dest);dest.close();source.close()
        if (src/'segments').exists():shutil.copytree(src/'segments',root/'segments')
        settings=Settings.load(root,knowledge_enabled=False,market_lookup_url='',market_chart_url='',news_feeds='',news_feeds_file='',log_queries=False)
        engine=SearchEngine(settings=settings)
        begin=time.perf_counter()
        if a.reindex:
            with engine.store.db.tx() as c:
                seq=engine.store._next_seq(c);c.execute('UPDATE documents SET seq=?',(seq,))
            engine.indexer.run()
        build_ms=(time.perf_counter()-begin)*1000
        cases=[json.loads(line)['query'] for line in Path(a.queries).read_text().splitlines() if line.strip()]
        latencies=[];parse=[];rows=[]
        for query in cases:
            times=[]
            for _ in range(max(1,a.repeats)):
                begin=time.perf_counter();parse_query(query,data_dir=root);parse.append((time.perf_counter()-begin)*1000)
                begin=time.perf_counter();response=engine.search(query,live=False,use_cache=False);times.append((time.perf_counter()-begin)*1000)
            latencies.append(statistics.median(times));rows.append({'query':query,'latency_ms':latencies[-1],'results':len(response['results'])})
        result={'scope':'Existing-corpus snapshot latency; no relevance judgments and no production-scale claim.',
            'documents':engine.index.doc_count,'reindexed':a.reindex,'reindex_ms':build_ms,
            'segment_bytes':sum(f.stat().st_size for f in settings.index_dir.iterdir() if f.is_file()),
            'latency_p50_ms':bootstrap(latencies,lambda v:quantile(v,.5)),
            'latency_p95_ms':bootstrap(latencies,lambda v:quantile(v,.95)),
            'parse_p95_ms':bootstrap(parse,lambda v:quantile(v,.95)), 'per_query':rows}
        Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='per_query'},indent=2))
if __name__=='__main__':main()
