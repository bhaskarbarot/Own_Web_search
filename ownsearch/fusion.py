"""Provider-agnostic reciprocal rank fusion; never invents result content."""
from .util import normalize_url


def fuse(rankings, weights=None, k=60):
    scores={}; items={}; sources={}
    for index,ranking in enumerate(rankings):
        seen=set()
        for rank,item in enumerate(ranking,1):
            key=normalize_url(item['url']) or item['url']
            if key in seen:
                continue
            seen.add(key)
            scores[key]=scores.get(key,0)+(weights[index] if weights else 1)/(k+rank)
            if key not in items:
                items[key]=dict(item)
            sources.setdefault(key,set()).update(item.get('providers', [item.get('provider','local_index')]))
    result=[]
    for rank,key in enumerate(sorted(scores,key=lambda u:(-scores[u],u)),1):
        row=items[key];row.update(rank=rank,score=round(scores[key],8),providers=sorted(sources[key]))
        result.append(row)
    return result
