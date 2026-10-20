"""Offline-built FAISS + local e5 ONNX adapter. No downloads on a search request."""
import json
import time
from pathlib import Path

def model_fingerprint(model_path):
    import hashlib
    root=Path(model_path).resolve();digest=hashlib.sha256()
    if not root.is_dir():raise ValueError('Local model directory does not exist')
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(part.startswith('.') for part in path.relative_to(root).parts):continue
        digest.update(str(path.relative_to(root)).encode())
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

class SemanticProvider:
    name='semantic_local'
    accepts_language=True
    def __init__(self,engine):self.engine=engine;self.loaded=None
    def _load(self):
        if self.loaded:return self.loaded
        cfg=self.engine.settings
        if not cfg.embedding_model_path:raise RuntimeError('No local embedding_model_path configured; BM25 retained.')
        import faiss
        from sentence_transformers import SentenceTransformer
        root=self.engine.root/'vectors'
        manifest=json.loads((root/'manifest.json').read_text())
        if manifest['generation']!=self.engine.index.generation:raise RuntimeError('Vector index is stale; rebuild it offline.')
        if manifest['model_path']!=str(Path(cfg.embedding_model_path).resolve()):raise RuntimeError('Vector/model fingerprint mismatch.')
        if manifest.get('model_sha256')!=model_fingerprint(cfg.embedding_model_path):raise RuntimeError('Local model changed; rebuild vectors offline.')
        model=SentenceTransformer(cfg.embedding_model_path,backend='onnx',local_files_only=True,trust_remote_code=False)
        self.loaded=(model,faiss.read_index(str(root/manifest['index_file'])),manifest)
        return self.loaded
    def search(self,query,deadline):
        language=None
        if isinstance(query,tuple):query,language=query
        model,index,manifest=self._load()
        if manifest['generation']!=self.engine.index.generation:raise RuntimeError('Vector index generation changed; rebuild offline.')
        if time.monotonic()>=deadline:return []
        vector=model.encode(['query: '+query],normalize_embeddings=True,convert_to_numpy=True).astype('float32')
        scores,ids=index.search(vector,min(10,len(manifest['documents'])))
        # A calibrated margin is required for this model and language. No global cosine cutoff.
        from ..language import identify
        lang=language or identify(query)['language']
        calibration=manifest.get('margins',{}).get(lang)
        if not calibration or calibration.get('minimum_margin') is None:
            raise RuntimeError('No held-out semantic margin calibration for '+lang+'; BM25 retained.')
        margin=float(scores[0][0]-scores[0][1]) if len(scores[0])>1 else 0
        if margin<calibration['minimum_margin']:return []
        out=[]
        for score,position in zip(scores[0],ids[0]):
            if position<0 or time.monotonic()>=deadline:break
            doc=manifest['documents'][int(position)]
            current=self.engine.store.get(doc['id'],with_text=True)
            if not current or not current['active'] or current.get('duplicate_of') is not None:continue
            out.append({'id':doc['id'],'url':current['url'],'title':current['title'],'snippet':current['text'][:320],
                        'lang':current['lang'],'provider':self.name,'providers':[self.name],'semantic_score':float(score),
                        'published_at':current['published_at'],'fetched_at':current['fetched_at'],'source_type':current['source_type'],
                        'crawl_status':'indexed','calibration_margin':margin})
        return out


def build(engine,model_path,margins=None):
    """Explicit maintenance operation; build whole active corpus outside the search path."""
    import faiss
    from sentence_transformers import SentenceTransformer
    import os
    from uuid import uuid4
    from ..store import _decompress
    model=SentenceTransformer(model_path,backend='onnx',local_files_only=True,trust_remote_code=False)
    engine.index.maybe_reload();generation=engine.index.generation
    docs=[];index=None
    cursor=engine.store.db.conn().execute('SELECT id,url,title,body FROM documents WHERE active=1 AND duplicate_of IS NULL ORDER BY id')
    while True:
        batch=cursor.fetchmany(32)
        if not batch:break
        vectors=model.encode(['passage: '+r['title']+' '+_decompress(r['body'])[:12000] for r in batch],
                             normalize_embeddings=True,convert_to_numpy=True).astype('float32')
        if index is None:index=faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors);docs.extend({'id':r['id'],'url':r['url']} for r in batch)
    if not docs:raise ValueError('No active documents to embed')
    engine.index.maybe_reload()
    if generation!=engine.index.generation:raise RuntimeError('Index changed during vector build; retry on a stable snapshot.')
    root=engine.root/'vectors';root.mkdir(exist_ok=True)
    filename='index-'+uuid4().hex+'.faiss';faiss.write_index(index,str(root/filename))
    manifest={'generation':generation,'model_sha256':model_fingerprint(model_path),'model_path':str(Path(model_path).resolve()),'index_file':filename,'documents':docs,'margins':margins or {}}
    temp=root/'manifest.json.tmp';temp.write_text(json.dumps(manifest));os.replace(temp,root/'manifest.json')
    return {'documents':len(docs),'generation':generation,'calibrated_languages':sorted((margins or {}).keys())}
