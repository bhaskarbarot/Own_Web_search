#!/usr/bin/env python3
"""Fetch bounded MIRACL topics/qrels from primary files. Corpus is imported separately.
The HF viewer is disabled for this dataset; no remote dataset loading code is executed.
"""
import argparse,hashlib,json
from pathlib import Path
from urllib.request import urlopen

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True);p.add_argument('--languages',nargs='+',default=['en','hi']);a=p.parse_args()
    root=Path(a.output_dir);root.mkdir(parents=True,exist_ok=True);sources=[]
    for lang in a.languages:
        if lang not in ('ar','bn','en','es','fa','fi','fr','hi','id','ja','ko','ru','sw','te','th','zh','de','yo'):raise ValueError('Not a MIRACL language: '+lang)
        for directory,prefix in [('topics','topics'),('qrels','qrels')]:
            filename=f'{prefix}.miracl-v1.0-{lang}-dev.tsv'
            url=f'https://huggingface.co/datasets/miracl/miracl/resolve/main/miracl-v1.0-{lang}/{directory}/{filename}'
            try:
                with urlopen(url,timeout=20) as response:raw=response.read(5_000_001)
                if len(raw)>5_000_000:raise ValueError('sample metadata exceeds download budget')
                (root/filename).write_bytes(raw)
                sources.append({'language':lang,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
                print(filename,len(raw),'bytes',flush=True)
            except Exception as exc:sources.append({'language':lang,'url':url,'error':str(exc)});print(lang,str(exc),flush=True)
    (root/'manifest.json').write_text(json.dumps({'sources':sources,'license':'Apache-2.0','source':'https://huggingface.co/datasets/miracl/miracl',
        'scope':'Topics/qrels only. Passage pool/full corpus must be supplied before ranking can be evaluated.'},indent=2))
if __name__=='__main__':main()
