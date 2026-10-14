"""Direct-answer checks are independent of webpage and host relevance metrics."""
import math
from .util import iso_to_ts


def assess_answer(answer, expected, now):
    if not answer:
        return {"status": "unavailable", "correct": None, "failures": []}
    failures = []
    if answer.get('verification') == 'unverified':
        return {"status": "unverified", "correct": None, "failures": []}
    if expected.get('type') and answer.get('type') != expected['type']:
        failures.append('answer type')
    for key in ('symbol', 'currency', 'scope', 'entity'):
        if key in expected and answer.get(key) != expected[key]:
            failures.append(key)
    for key in ('price', 'change_pct'):
        if key in expected:
            actual = answer.get(key)
            if not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected[key], abs_tol=1e-5):
                failures.append(key)
    if answer.get('type') in ('stock_quote', 'stock_history'):
        ts = iso_to_ts(answer.get('as_of'))
        if ts is None or not now - expected.get('max_age_seconds', 7 * 86400) <= ts <= now + 300:
            failures.append('timestamp')
        if not answer.get('disclaimer'):
            failures.append('disclaimer')
    for key, value in expected.get('analysis', {}).items():
        actual = answer.get('analysis', {}).get(key)
        if not isinstance(actual, (int,float)) or not math.isfinite(actual) or not math.isclose(actual, value, abs_tol=1e-5):
            failures.append('analysis.' + key)
    if answer.get('type') == 'fact' and answer.get('verification') != 'corroborated':
        return {'status':'unverified','correct':None,'failures':failures}
    if answer.get('type') == 'fact' and not expected.get('fact_values'):
        return {'status':'unjudged','correct':None,'failures':failures}
    for prop, values in expected.get('fact_values', {}).items():
        actual = {v.get('text','').casefold() for f in answer.get('facts',[]) if f.get('property') == prop for v in f.get('values',[])}
        if actual != {v.casefold() for v in values}:
            failures.append('fact.' + prop)
    if not expected:
        return {"status": "unjudged", "correct": None, "failures": failures}
    return {"status": "incorrect" if failures else "correct", "correct": not failures, "failures": failures}
