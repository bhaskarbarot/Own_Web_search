"""Calibrated multilingual intent using a local e5 ONNX model, loaded off request threads."""
import json
import time
from pathlib import Path

class EmbeddingIntent:
    name='intent_local'
    def __init__(self,settings):self.settings=settings;self.model=None;self.prototypes=None
    def _load(self):
        if self.model is not None:return
        if not self.settings.embedding_model_path:raise RuntimeError('No local ONNX embedding model configured')
        from sentence_transformers import SentenceTransformer
        from ..intent import _read,RESOURCE
        self.model=SentenceTransformer(self.settings.embedding_model_path,backend='onnx',local_files_only=True,trust_remote_code=False)
        rows=_read(RESOURCE)
        labels=[label for label,_ in rows]
        vectors=self.model.encode(['passage: '+text for _,text in rows],normalize_embeddings=True,convert_to_numpy=True)
        self.prototypes=(labels,vectors)
    def search(self,payload,deadline):
        query,language=payload
        self._load()
        if time.monotonic()>=deadline:return []
        path=self.settings.data_dir/'intent_margins.json'
        thresholds=json.loads(path.read_text()).get(language,{}) if path.exists() else {}
        threshold=thresholds.get('minimum_margin')
        if threshold is None:raise RuntimeError('Multilingual intent has no held-out margin calibration for '+language)
        vector=self.model.encode(['query: '+query],normalize_embeddings=True,convert_to_numpy=True)[0]
        labels,prototypes=self.prototypes;scores=prototypes@vector;best={}
        for label,score in zip(labels,scores):best[label]=max(best.get(label,-1),float(score))
        ordered=sorted(best,key=best.get,reverse=True)
        if not ordered:return []
        margin=best[ordered[0]]-best[ordered[1]] if len(ordered)>1 else 0
        label=ordered[0] if not thresholds.get('reject_all') and margin>=threshold else 'general'
        return [{'label':label,'margin':margin,'minimum_margin':threshold,'source':'calibrated_local_e5'}]
