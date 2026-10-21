#!/usr/bin/env python3
"""Wrong-schema failure ablation; bounded fixture requests, no public network."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import types
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ownsearch.config import Settings
from ownsearch.fetcher import Fetcher,FetchResult
from ownsearch.query import parse_query
from ownsearch.webmodels import WebRequest
from ownsearch.webproviders import ProviderError
from ownsearch.vertical import OpenAlexApiProvider


def measure(factory):
    cfg=Settings(provider_min_interval=0);p=factory(cfg);p.minimum_interval=0;statuses=[]
    with patch.object(Fetcher,'fetch',return_value=FetchResult('','',200,{},b'{"results":"invalid"}')) as fetch:
        for _ in range(4):
            req=WebRequest('fixture research',parse_query('fixture research'),threading.Event())
            try:p.search(req,time.monotonic()+1);statuses.append('ok')
            except Exception as exc:statuses.append(getattr(exc,'status','error'))
        return {'fixture_http_calls':fetch.call_count,'statuses':statuses,'health':p.health_snapshot()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    old=types.ModuleType('ownsearch._schema_baseline');old.__package__='ownsearch';sys.modules[old.__name__]=old
    exec(compile(subprocess.check_output(['git','show','934a702:ownsearch/webproviders.py'],cwd=ROOT),'<schema-baseline>','exec'),old.__dict__)
    class Before(old.JsonProvider):
        name='openalex'
        def search(self,request,deadline):
            data=self.request(request,'https://api.example.org/search',deadline)
            if not isinstance(data.get('results'),list):raise ProviderError('Invalid result schema.')
    report={'scope':'Four identical wrong-schema HTTP-200 fixture responses; not live relevance.',
            'before':measure(Before),'after':measure(OpenAlexApiProvider)}
    assert report['before']['fixture_http_calls']==4 and report['after']['fixture_http_calls']==3
    assert report['after']['statuses'][-1]=='circuit_open'
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
