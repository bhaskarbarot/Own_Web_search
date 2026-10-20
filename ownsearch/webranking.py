"""Small in-memory candidate ranking using OwnSearch's BM25 and feature weights.

These scores are ordering signals, never calibrated correctness probabilities.
"""
import math
import time
from collections import Counter
from urllib.parse import unquote, urlsplit

from .evidence import passages
from .intent import get_model, requested_format
from .quality import simhash, hamming
from .query import FILETYPE_ALIASES
from .ranking import FIELD_WEIGHTS, FIELD_B, K1, DEFAULT_WEIGHTS, linear_score
from .textproc import analyze, exact_tokens
from .util import iso_to_ts
from .webquery import literal_identifiers, literal_names, documentation_affinity, relation_terms


def _contains(text, tokens):
    return bool(tokens) and ' '+' '.join(tokens)+' ' in text


def constraints(item, q, final=True):
    host = urlsplit(item.url).hostname or ''
    if q.sites and not any(host == s or host.endswith('.'+s) for s in q.sites):
        return False
    if any(host == s or host.endswith('.'+s) for s in q.not_sites):
        return False
    text = item.title+' '+(item.content if item.fetch_status == 'fetched' else item.snippet)
    terms = set(analyze(text))
    exact = ' '+' '.join(exact_tokens(text))+' '
    if any(t in terms for t in q.excluded) or any(_contains(exact, p) for p in q.exact_excluded_phrases):
        return False
    if final and any(not _contains(exact, p) for p in q.exact_phrases):
        return False
    if q.intitle and not set(q.intitle) <= set(analyze(item.title)):
        return False
    if q.inurl and not set(q.inurl) <= set(analyze(unquote(item.url))):
        return False
    if q.alternatives and not set(q.alternatives) & terms:
        return False
    # A snippet can omit an acronym that the actual page explains. Defer that
    # check until after enrichment; invented alphanumeric identifiers stay strict.
    expanded_terms = terms | {term.lstrip('0123456789') for term in terms if term[:1].isdigit()}
    if any((final or any(ch.isdigit() for ch in ''.join(name)))
           and not _contains(exact, name) and not set(analyze(' '.join(name))) <= expanded_terms
           for name in literal_identifiers(q)):
        return False
    if final and q.intent == 'reference':
        facets = set(relation_terms(q))
        declared_focus = set(analyze(item.title+' '+item.snippet))
        if facets and not facets & declared_focus:
            return False
    if q.entities and not all(any(_contains(exact, exact_tokens(n)) for n in e.names) for e in q.entities):
        return False
    if q.lang:
        actual, wanted = (item.language or '').lower(), q.lang.lower()
        matches_language = actual == wanted or ('-' not in wanted and actual.startswith(wanted+'-'))
        if not matches_language and (final or item.language):
            return False
    if q.filetypes:
        ext = urlsplit(item.url).path.rsplit('.', 1)[-1].lower()
        ext = FILETYPE_ALIASES.get(ext, ext)
        kinds = ({'web' if item.detected_kind == 'html' else item.detected_kind}
                 if item.detected_kind else {'web' if item.kind == 'web' else item.kind, ext})
        if not set(q.filetypes) & kinds:
            return False
    stamp = iso_to_ts(item.published_at)
    if stamp is not None and stamp > time.time()+300:
        return False
    if q.after is not None or q.before is not None:
        if stamp is None:
            if final:
                return False
        elif (q.after is not None and stamp < q.after) or (q.before is not None and stamp > q.before):
            return False
    return True


def merge(candidates):
    """Canonicalize identities only when supported by a same-origin page canonical."""
    unique = {}
    for item in candidates:
        key = item.canonical or item.url
        if key not in unique:
            unique[key] = item
            continue
        prior = unique[key]
        # Prefer inspected evidence, retaining every contributing source.
        chosen, other = (item, prior) if item.fetch_status == 'fetched' and prior.fetch_status != 'fetched' else (prior, item)
        chosen.provenance = chosen.provenance + [p for p in other.provenance if p not in chosen.provenance]
        chosen.images = chosen.images + [i for i in other.images if i not in chosen.images]
        unique[key] = chosen
    return list(unique.values())


def rank(candidates, q, final=True):
    candidates = [i for i in merge(candidates) if constraints(i, q, final)]
    if not candidates:
        return []
    terms = list(dict.fromkeys(q.scoring_terms or q.entity_terms or analyze(q.raw)))
    fields = [[analyze(i.title), analyze(' '.join(i.headings)), analyze(unquote(urlsplit(i.url).path)), [],
               analyze(i.content if i.fetch_status == 'fetched' else i.snippet)] for i in candidates]
    df = Counter(t for f in fields for t in set(t for field in f for t in field))
    avg = [max(1, sum(len(f[j]) for f in fields)/len(fields)) for j in range(5)]
    idf = {t: math.log(1+(len(fields)-df[t]+.5)/(df[t]+.5)) for t in terms}
    raw_scores = []
    for f in fields:
        counters = [Counter(field) for field in f]
        score = 0
        for t in terms:
            tf = sum(FIELD_WEIGHTS[j]*counters[j][t]/(1-FIELD_B[j]+FIELD_B[j]*len(f[j])/avg[j]) for j in range(5))
            score += idf[t]*tf*(K1+1)/(K1+tf) if tf else 0
        raw_scores.append(score)
    best = max(raw_scores) or 1
    kept = []
    for item, f, bm25 in zip(candidates, fields, raw_scores):
        present = set(f[0]+f[1]+f[4])
        required = set(q.required or q.entity_terms or terms)
        coverage = len(required & present)/max(1, len(required))
        title = len(required & set(f[0]))/max(1, len(required))
        # An incidental body mention cannot make an unrelated page about the query.
        if not bm25 or coverage < .5 or (not title and coverage < .8):
            continue
        focus = ' '+' '.join(exact_tokens(item.title+' '+' '.join(item.headings)))+' '
        if any(not _contains(focus, name) for name in literal_names(q)):
            continue
        if q.intent == 'financial' and item.source_type != 'market_data':
            predicted, _ = get_model().classify(item.title)
            if predicted not in ('finance_quote', 'finance_history', 'financial'):
                continue
        if q.intent == 'tech_docs' and not (required & set(f[0]+f[2])):
            continue
        text = item.content if item.fetch_status == 'fetched' else item.snippet
        evidence_terms = list(dict.fromkeys(terms + relation_terms(q)))
        ps = passages(text, evidence_terms, q.surface, idf=idf, max_passages=3, scan_chars=60_000)
        item.evidence = [p for p in ps if p.get('matched_terms', 0)]
        exact_title = ' '+' '.join(exact_tokens(item.title))+' '
        phrase = max((float(_contains(exact_title, p)) for p in q.exact_phrases), default=0)
        subject = exact_tokens(' '.join(q.entity))
        exact_subject = float(_contains(exact_title, subject))
        stamp = iso_to_ts(item.published_at)
        freshness = math.exp(-max(0, time.time()-stamp)/(7*86400)) if stamp else 0
        features = {'bm25': bm25/best, 'coverage': coverage, 'title': title,
                    'url': len(required & set(f[2]))/max(1, len(required)),
                    'exact_title': max(phrase, .3*exact_subject), 'phrase': phrase,
                    'format': float(bool(q.result_format) and requested_format(item.title) == q.result_format),
                    'passage': min(1, max((p['score'] for p in item.evidence), default=0)/3),
                    'quality': float(len(text) > 100),
                    'same_language': float(bool(item.language) and item.language.split('-')[0] == q.language_info.get('language')),
                    'freshness': freshness if q.fresh_intent or q.freshness or q.intent == 'news' else 0}
        weights = dict(DEFAULT_WEIGHTS)
        if q.fresh_intent or q.freshness or q.intent == 'news':
            weights['freshness'] = .5
        # Source order is useful evidence after relevance checks, not a substitute for them.
        positions = [p.get('rank') for p in item.provenance if type(p.get('rank')) is int and p['rank'] > 0]
        features['retrieval_rank'] = 1/math.sqrt(min(positions)) if positions else 0
        weights['retrieval_rank'] = .25
        location = urlsplit(item.url)
        project_terms = required & set(analyze(location.hostname or ''))
        inspected_project = item.fetch_status == 'fetched' and coverage >= .8 and len(project_terms) >= min(2, len(required))
        if q.intent == 'tech_docs' and coverage >= .5 and (title > 0 or inspected_project):
            segments = location.hostname.split('.') + location.path.strip('/').split('/')[:2]
            features['documentation_structure'] = max((documentation_affinity(segment) for segment in segments if segment), default=0)
            weights['documentation_structure'] = 1.2
            features['project_host'] = len(required & set(analyze(location.hostname or '')))/max(1, len(required))
            weights['project_host'] = .4
        # Inspected page text is a small evidence signal; content relevance dominates.
        features['fetched_evidence'] = float(item.fetch_status == 'fetched' and coverage >= .8)
        weights['fetched_evidence'] = .2
        item.features = features
        item.score = linear_score(features, weights)
        kept.append(item)
    kept.sort(key=lambda i: (-i.score, i.url))
    seen_hashes, result = [], []
    for item in kept:
        if kept and item.score < kept[0].score*.3:
            continue
        tokens = analyze(item.content) if item.content else []
        fingerprint = simhash(tokens) if len(tokens) >= 40 else None
        duplicate = next((p for h, p in seen_hashes if fingerprint is not None and hamming(h, fingerprint) <= 3), None)
        if duplicate is not None:
            duplicate.provenance.extend(p for p in item.provenance if p not in duplicate.provenance)
            continue
        if fingerprint is not None:
            seen_hashes.append((fingerprint, item))
        result.append(item)
    return result
