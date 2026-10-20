"""Spelling alternatives learned only from active indexed document vocabulary."""
import math
from collections import Counter, defaultdict
from .textproc import tokenize, stem, ALL_STOPWORDS


def distance(a, b, limit=2):
    if abs(len(a)-len(b)) > limit:
        return limit+1
    prior = list(range(len(b)+1))
    older = None
    for i, x in enumerate(a, 1):
        row = [i]
        for j,y in enumerate(b,1):
            value = min(row[-1]+1,prior[j]+1,prior[j-1]+(x!=y))
            if older is not None and i>1 and j>1 and a[i-2]==y and x==b[j-2]:
                value=min(value,older[j-2]+1)
            row.append(value)
        older,prior=prior,row
    return prior[-1]


class Vocabulary:
    def __init__(self, store, max_terms=50000, deadline=None, snapshot=None):
        self.frequency=Counter(); self.deletes=defaultdict(set)
        import time
        stop = min(deadline or float('inf'),time.monotonic()+.04)
        if snapshot:
            for reader in snapshot.readers:
                for term,entry in reader.iter_terms():
                    if time.monotonic()>=stop: break
                    if term.startswith('\x02e:'):
                        self.frequency[term[3:]]+=entry[0]
                    elif term > '\x02e;': break
        rows = () if self.frequency else store.db.conn().execute('SELECT title,body FROM documents WHERE active=1 AND duplicate_of IS NULL LIMIT 500')
        for row in rows:
            if time.monotonic() >= stop: break
            from .store import _decompress
            self.frequency.update(tokenize(row['title'])*3 + tokenize(_decompress(row['body'])[:60000]))
        self.frequency=Counter(dict(self.frequency.most_common(max_terms)))
        self.stems={stem(w) for w in self.frequency}
        build_until=min(deadline or float('inf'),time.monotonic()+.1)
        for word in self.frequency:
            if time.monotonic()>=build_until:break
            if 4<=len(word)<=40 and word.isalpha():
                self.deletes[word].add(word)
                for i in range(len(word)):
                    self.deletes[word[:i]+word[i+1:]].add(word)

    def suggest(self, word):
        if word in self.frequency or stem(word) in self.stems or word in ALL_STOPWORDS or not word.isalpha() or len(word)<4:
            return None
        deleted={word}|{word[:i]+word[i+1:] for i in range(len(word))}
        candidates=set()
        for key in deleted:
            candidates.update(self.deletes.get(key,()))
        if len(word)>=7:
            for key in list(deleted):
                for i in range(len(key)):
                    candidates.update(self.deletes.get(key[:i]+key[i+1:],()))
        scores=[]
        for candidate in candidates:
            d=distance(word,candidate)
            if d<= (2 if len(word)>=7 else 1):
                scores.append((d,-math.log1p(self.frequency[candidate]),candidate))
        scores.sort()
        if not scores:
            return None
        # Ties at the same distance need a clear frequency margin.
        if len(scores)>1 and scores[0][0]==scores[1][0] and self.frequency[scores[0][2]]<2*self.frequency[scores[1][2]]:
            return None
        return scores[0][2]

    def alternative(self, query, parsed):
        if parsed.phrases or parsed.exact_phrases or parsed.entities or parsed.excluded or parsed.excluded_phrases:
            return None,{}
        import re
        corrections={}
        def replace(match):
            value=match.group()
            if any(c in value for c in '_/:.0123456789') or value.isupper() or value.lower() in ALL_STOPWORDS:
                return value
            if stem(value.lower()) not in parsed.required:
                return value
            suggestion=self.suggest(value.lower())
            if suggestion:
                corrections[value]=suggestion
                return suggestion
            return value
        alternative=re.sub(r'[^\s]+',replace,query)
        return (alternative if corrections else None),corrections
