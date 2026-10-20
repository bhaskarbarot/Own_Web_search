"""Optional CPU CrossEncoder. A budget expiration leaves the complete base order intact."""
class Reranker:
    name='reranker_local'
    def __init__(self,settings):self.settings=settings;self.model=None
    def search(self,payload,deadline):
        import time
        query,rows=payload
        if not self.settings.reranker_model_path:raise RuntimeError('No local reranker model configured')
        if self.model is None:
            from sentence_transformers import CrossEncoder
            self.model=CrossEncoder(self.settings.reranker_model_path,device='cpu',local_files_only=True,trust_remote_code=False)
        if time.monotonic()>=deadline:return []
        top=rows[:10]
        values=self.model.predict([(query,r['title']+' '+r.get('snippet','')) for r in top])
        if time.monotonic()>=deadline:return []
        # Reranking stays inside the selected lexical tier; exact-query/entity rows retain precedence.
        from ..query import parse_query
        from ..textproc import analyze
        q=parse_query(query)
        def tier(row):return int(set(q.required)<=set(analyze(row['title']+' '+row.get('snippet',''))))
        return [dict(row,rerank_score=float(value)) for row,value in sorted(zip(top,values),key=lambda pair:(tier(pair[0]),float(pair[1])),reverse=True)]+rows[10:]
