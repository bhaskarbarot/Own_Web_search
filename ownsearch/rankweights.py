"""Owned lexical scoring weights; scores are not truth probabilities."""
FIELD_WEIGHTS = (3.0, 1.8, 1.4, 2.2, 1.0, 0.05, 0.12, 0.12, 0.0)
FIELD_B = (0.40, 0.50, 0.30, 0.60, 0.75, 0.0, 0.5, 0.5, 0.0)
K1 = 1.2
CAND_LIMIT = 30000          # max postings scanned for the lead term before switching to champion lists
PHRASE_CHECK_LIMIT = 20000

DEFAULT_WEIGHTS = {
    "bm25": 1.00,            # normalised BM25F (score / best score in the candidate set)
    "coverage": 0.45,        # fraction of query terms matched
    "title": 0.35,           # fraction of query terms in the title
    "subject": 0.70,         # rarity-weighted, unstemmed subject names in title/URL
    "intent": 0.35,          # learned title phrasing when the subject is linked
    "entity_density": 0.60,  # linked subjects occupy the content, rather than appearing incidentally
    "authority": 0.40,       # entity-provided official URL scope, gated on content relevance
    "format": 0.60,          # requested list/output grammar in a content-matching title
    "url": 0.12,             # fraction of query terms in the URL
    "exact_title": 1.0,
    "same_language": 0.12,
    "ngram": 0.03, # secondary evidence only; never generates broad OR candidates
    "phrase": 0.30,          # whole query appears as a phrase
    "proximity": 0.30,       # 1 / (1 + extra words in the minimal window covering all terms)
    "passage": 0.25,         # best passage density
    "pagerank": 0.20,
    "quality": 0.18,
    "freshness": 0.05,       # multiplied up when the query wants fresh results
    "depth": 0.06,           # shallow URLs (home/section pages) for navigational queries
}

def linear_score(features, weights):
    return sum(weights.get(k, 0.0) * v for k, v in features.items())
