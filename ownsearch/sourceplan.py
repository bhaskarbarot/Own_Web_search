"""User-owned source descriptions, ranked statistically without topic switches."""
from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
from urllib.parse import urlsplit
from .intent import get_model
from .textproc import analyze, tokenize, stem, ALL_STOPWORDS
from .webmodels import web_url

@dataclass(frozen=True)
class Source:
    url: str
    description: str = ''


def load_registry(path, extra=(), limit=2000):
    sources = []
    if path:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # TSV is configuration syntax. Descriptions never become query rules.
            url, _, description = line.partition('\t')
            sources.append(Source(url.strip(), description.strip()))
    sources.extend(Source(url) for url in extra)
    unique = {}
    for source in sources:
        unique.setdefault(source.url, source)
    return list(unique.values())[:limit]


def _cosine(a, b):
    dot = sum(value * b.get(key, 0) for key, value in a.items())
    size = math.sqrt(sum(v*v for v in a.values()) * sum(v*v for v in b.values()))
    return dot / size if size else 0.0


def plan_sources(query, sources):
    """TF-IDF plus a small learned intent distribution; low confidence keeps breadth.

    All sources remain eligible. Scores order starting roots; source categories
    never appear as code branches or a query-to-domain lookup table.
    """
    texts = [source.description or urlsplit(source.url).hostname or '' for source in sources]
    docs = [Counter(stem(t) for t in tokenize(text) if t.lower() not in ALL_STOPWORDS) for text in texts]
    query_terms = Counter(stem(t) for t in tokenize(query) if t.lower() not in ALL_STOPWORDS)
    if not query_terms:
        docs = [Counter(analyze(text)) for text in texts]
        query_terms = Counter(analyze(query))
    df = Counter(term for doc in docs for term in doc)
    weights = {term: 1 + math.log((1+len(docs))/(1+df[term])) for term in set(query_terms) | set(df)}
    vector = {term: count*weights[term] for term,count in query_terms.items()}
    model = get_model()
    _, query_probs = model.classify(query)
    # Center probabilities on a uniform prior so generic shared probability mass
    # does not make every source appear to have strong semantic similarity.
    prior = 1/max(1,len(query_probs))
    query_latent = {k:max(0,v-prior) for k,v in query_probs.items()}
    rows = []
    for position, (source, text, doc) in enumerate(zip(sources, texts, docs)):
        lexical = _cosine(vector, {term: count*weights[term] for term,count in doc.items()})
        _, probabilities = model.classify(text)
        latent = _cosine(query_latent, {k:max(0,v-prior) for k,v in probabilities.items()})
        # Uncalibrated learned similarity is a small scheduling preference only.
        score = lexical + .10*latent if (source.description and lexical > 0) else (0.02 * latent if source.description else lexical)
        rows.append({'url':source.url, 'description':source.description,'score':score,
                     'lexical_similarity':lexical,'learned_similarity':latent,
                     'position':position,'selection':'eligible'})
    return sorted(rows,key=lambda row:(-row['score'],row['position']))
