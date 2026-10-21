"""Text-only highlights: offsets into the actual snippet, with no injected HTML."""
import re

from .textproc import analyze, tokenize


_SENTENCE_END = re.compile(r'''[.!?…。！？।]["'”’»\)\]]*(?=\s|$)''')
_WHITESPACE = re.compile(r'\s+')


def sentence_excerpt(text, max_len=600, query_terms=()):
    """A bounded source prefix, preferring complete sentences and then whole words.

    The ellipsis marks omitted source text. A token longer than the whole budget
    is omitted rather than changed into a different, partial identifier.
    """
    if max_len < 1:
        raise ValueError('Snippet length must be positive.')
    if len(text) <= max_len:
        return text
    budget = max_len - 1  # reserve one character for the truncation marker
    # Inspect one extra character so a decimal point/URL at the boundary is not
    # mistaken for punctuation followed by the end of the source.
    endpoints = [match.end() for match in _SENTENCE_END.finditer(text, 0, max_len)
                 if match.end() <= budget]
    word_end = max((match.start() for match in _WHITESPACE.finditer(text, 0, budget + 1)), default=0)
    end = endpoints[-1] if endpoints else word_end
    # A short introductory sentence must not displace the requested facet in a
    # longer following sentence. Preserve complete matching query words that
    # fit in the budget, using the whole-word fallback where needed.
    wanted = set(query_terms)
    if wanted and end < word_end:
        retained = wanted & set(analyze(text[:end]))
        available = wanted & set(analyze(text[:word_end]))
        if available - retained:
            end = word_end
    return text[:end].rstrip() + '…'


def highlights(text,query):
    wanted=set(tokenize(query)); spans=[]
    try:
        import regex
        matches=regex.finditer(r'[\p{L}\p{M}\p{N}]+',text)
    except ImportError:
        import re
        matches=re.finditer(r'[^\W_]+',text)
    for match in matches:
        if wanted.intersection(tokenize(match.group())):
            spans.append({'start':match.start(),'end':match.end(),'text':match.group()})
    return spans
