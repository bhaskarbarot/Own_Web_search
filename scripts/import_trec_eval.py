#!/usr/bin/env python3
"""Import MIRACL/IndicIRSuite-compatible local exports, preserving supplied judgments.

Inputs: corpus JSONL (docid/title/text), topic TSV (id/query), TREC qrels
(id Q0 docid grade). No downloads, invented translations, or generated judgments.
"""
import argparse,gzip,json
from pathlib import Path
from urllib.parse import quote

def convert(corpus_path,topics_path,qrels_path,language,output,limit=None):
    topics={}
    for line in Path(topics_path).read_text().splitlines():
        if line.strip():
            qid,text=line.split('\t',1);topics[qid]=text
            if limit and len(topics)>=limit:break
    qrels={qid:{} for qid in topics}
    for line in Path(qrels_path).read_text().splitlines():
        parts=line.split()
        if len(parts)!=4:raise ValueError('TREC qrels need four columns')
        qid,_,docid,grade=parts
        if qid in qrels:qrels[qid][docid]=max(0,min(3,int(grade)))
    needed={d for judgments in qrels.values() for d in judgments};docs=[];found=set()
    opener=gzip.open if str(corpus_path).endswith('.gz') else open
    def url(docid):return 'local://public-dataset/'+quote(language,safe='')+'/'+quote(docid,safe='')
    with opener(corpus_path,'rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);docid=str(row.get('docid',row.get('_id','')))
            if docid not in needed or docid in found:continue
            docs.append({'title':row.get('title',''),'text':row['text'],'url':url(docid),'lang':language,
                         'metadata':{'dataset_docid':docid}});found.add(docid)
            if found==needed:break
    if needed-found:raise ValueError(f'{len(needed-found)} judged passages are missing from supplied corpus; evaluation refused')
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    cases=[{'id':language+'-'+qid,'query':text,'language':language,'judgment_scope':'public_supplied_judgments_passage_pool',
            'judgments':{url(d):grade for d,grade in qrels[qid].items()},'expected_empty':not any(qrels[qid].values())} for qid,text in topics.items()]
    (root/'corpus.json').write_text(json.dumps({'as_of':'2026-10-20T12:00:00+00:00','scope':'Judged passage pool only, not full-corpus or web coverage','documents':docs},ensure_ascii=False))
    (root/'queries.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases))
    return {'documents':len(docs),'queries':len(cases),'scope':'supplied judged passage pool'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','topics','qrels','language','output-dir'):p.add_argument('--'+name,required=True)
    p.add_argument('--limit',type=int);a=p.parse_args()
    print(json.dumps(convert(a.corpus,a.topics,a.qrels,a.language,a.output_dir,a.limit)))
if __name__=='__main__':main()
