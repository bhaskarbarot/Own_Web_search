"""Text-only highlights: offsets into the actual snippet, with no injected HTML."""
from .textproc import tokenize

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
