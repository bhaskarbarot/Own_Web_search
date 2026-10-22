"""Conservative live-query routing and literal identifiers, without topic dictionaries."""
import re
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .dates import parse_duration
from .intent import temporal_window
from .intent import get_model
from .textproc import STOPWORDS, analyze, exact_tokens, tokenize


def conservative_intent(q):
    """An uncertain intent may influence scoring; it must not restrict discovery."""
    confidence = q.intent_confidence
    best = max(q.intent_scores.values(), default=0)
    if (q.intent in ('news', 'financial') and confidence.get('status') != 'calibrated'
            and (best < .55 or confidence.get('margin', 0) < .15)):
        q.intent = 'general'
        if not q.explicit_date_filter:
            q.after = q.before = None
            q.freshness = 'recent' if q.fresh_intent else None
        q.intent_details = {'entity': ' '.join(q.entity)}
        q.intent_confidence = {**confidence, 'routing': 'general_due_to_low_confidence'}
    return live_dates(q)


def live_dates(q, now=None):
    """Explicit calendar/duration grammar; 'latest' alone is a ranking preference."""
    if q.explicit_date_filter:
        return q
    zone = ZoneInfo(q.temporal.get('timezone') or 'UTC')
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    match = re.search(r'\b(this|last|previous)\s+(week|month|year)\b', q.raw, re.I)
    begin = end = None
    if match:
        period, unit = (word.lower() for word in match.groups())
        previous = period != 'this'
        if unit == 'week':
            begin = midnight-timedelta(days=midnight.weekday()+7*previous)
            end = begin+timedelta(days=7)
        elif unit == 'month':
            begin = midnight.replace(day=1)
            if previous:
                begin = (begin-timedelta(days=1)).replace(day=1)
            end = begin.replace(year=begin.year+(begin.month == 12), month=begin.month % 12+1)
        else:
            begin = midnight.replace(year=now.year-previous, month=1, day=1)
            end = begin.replace(year=begin.year+1)
    elif re.search(r'\b(last|past|previous)\b', q.raw, re.I) and (days := parse_duration(q.raw)):
        begin, end = now-timedelta(days=days), now+timedelta(milliseconds=1)
    else:
        match = re.search(r'\b(?:published|released|announced)\s+in\s+([12][0-9]{3})(?:\s+(?:or|and|to|through)\s+([12][0-9]{3}))?\b', q.raw, re.I)
        if match:
            years = [int(year) for year in match.groups() if year]
            begin = midnight.replace(year=min(years), month=1, day=1)
            end = midnight.replace(year=max(years)+1, month=1, day=1)
    if begin is not None:
        q.after, q.before = begin.timestamp(), end.timestamp()-.001
        q.fresh_intent = True
        q.freshness = 'recent'
        q.temporal = {'windows': [{'after': q.after, 'before': q.before}], 'timezone': str(zone),
                      'ambiguous': False, 'parser': 'live_calendar_grammar'}
    elif q.intent == 'news' and temporal_window(q.raw, get_model()) is None:
        q.after = q.before = None
        q.freshness = 'recent'
    return q


def literal_identifiers(q):
    """Mixed-case API names, acronyms and alphanumeric names are literal evidence."""
    model = get_model()
    identifiers = []
    for value in q.entity:
        for word in re.findall(r'[^\W_]+', value, flags=re.UNICODE):
            if model.is_query_language(word) or word.lower() in STOPWORDS or word.lower() in ('url', 'uri', 'link', 'page', 'site', 'website', 'doc', 'docs', 'home', 'homepage'):
                continue
            letters = [ch for ch in word if ch.isalpha()]
            mixed_case = any(ch.isupper() for ch in word[1:]) and not word.isupper()
            acronym = len(letters) >= 2 and word.isupper()
            alphanumeric = bool(letters) and any(ch.isdigit() for ch in word)
            if mixed_case or acronym or alphanumeric:
                identifiers.append(tuple(exact_tokens(word)))
    return list(dict.fromkeys(identifiers))


def literal_names(q):
    # Existing subject extraction can join words across stopwords; only retain
    # a name phrase actually contiguous in the original query.
    raw = ' '+' '.join(exact_tokens(q.raw))+' '
    return [tuple(exact_tokens(name)) for name in q.named_phrases
            if ' '+' '.join(exact_tokens(name))+' ' in raw]


def discovery_text(request):
    """Emphasize the subject without deleting qualifiers, operators or request text."""
    text, q = request.query, request.parsed
    match = re.search(r'(?<![-\w:])"[^"\n]+"', text)
    if match and match.start() and not q.exact_excluded_phrases:
        return match.group()+' '+text
    first = next(re.finditer(r'\S+', text), None)
    if first is None or ':' in first.group() or first.group().startswith(('-', '"')):
        return text
    model = get_model()
    words = tokenize(first.group())
    if not words or not all(word in STOPWORDS or model.is_query_language(word) for word in words):
        return text
    subjects = [value for value in q.entity if value and value[0].isupper()] or q.entity
    if subjects and not text.lower().startswith(subjects[0].lower()):
        return subjects[0]+' '+text
    return text


def documentation_affinity(value):
    label, probabilities = get_model().classify(value)
    if label != 'tech_docs':
        return 0.0
    positive = probabilities.get('tech_docs', 0)
    other = max((p for name, p in probabilities.items() if name != 'tech_docs'), default=1)
    return min(1.0, max(0.0, math.log(max(positive, 1e-9)/max(other, 1e-9))/math.log(4)))


def relation_terms(q):
    model = get_model()
    return list(dict.fromkeys(term for word in q.context if model.cue_strength(word, q.intent) >= 3
                             for term in analyze(word)))
