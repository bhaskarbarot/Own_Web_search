"""Rule-based Indic romanization and phonetic keys (script grammar, not topic data)."""
import re
import unicodedata

_CONSONANTS='k kh g gh ng c ch j jh ny tt tth dd ddh nn t th d dh n p ph b bh m y r l ll v sh ss s h'.split()
# Unicode block offsets shared by Devanagari and Gujarati.
_VOWELS={0x05:'a',0x06:'aa',0x07:'i',0x08:'ii',0x09:'u',0x0a:'uu',0x0b:'r',0x0f:'e',0x10:'ai',0x13:'o',0x14:'au'}
_SIGNS={0x3e:'aa',0x3f:'i',0x40:'ii',0x41:'u',0x42:'uu',0x43:'r',0x44:'rr',0x47:'e',0x48:'ai',0x4b:'o',0x4c:'au'}


def romanize(text):
    out=[]
    for c in unicodedata.normalize('NFD',text.casefold()):
        cp=ord(c)
        base=0x0900 if 0x0900<=cp<=0x097f else 0x0a80 if 0x0a80<=cp<=0x0aff else None
        if base is None:
            if unicodedata.category(c).startswith('M'):
                continue
            out.append(c);continue
        offset=cp-base
        if offset in _VOWELS:
            out.append(_VOWELS[offset])
        elif 0x15<=offset<=0x39:
            # Some offsets in the Unicode block are reserved additional consonants.
            name=unicodedata.name(c,'').split(' LETTER ')[-1].lower()
            name={'ka':'k','kha':'kh','ga':'g','gha':'gh','nga':'ng','ca':'ch','cha':'chh','ja':'j','jha':'jh',
                  'nya':'ny','tta':'t','ttha':'th','dda':'d','ddha':'dh','nna':'n','ta':'t','tha':'th','da':'d',
                  'dha':'dh','na':'n','pa':'p','pha':'ph','ba':'b','bha':'bh','ma':'m','ya':'y','ra':'r',
                  'la':'l','lla':'l','va':'v','sha':'sh','ssa':'sh','sa':'s','ha':'h'}.get(name,name.rstrip('a'))
            out.append(name+'a')
        elif offset in _SIGNS or offset==0x4d:
            if out and out[-1].endswith('a'):
                out[-1]=out[-1][:-1]
            if offset!=0x4d:
                out.append(_SIGNS[offset])
        elif offset in (1,2):
            out.append('n')
        elif offset==3:
            out.append('h')
        elif offset==0x3c:
            pass
        else:
            out.append(' ')
    return ''.join(out).rstrip('a')


def key(text):
    value=romanize(text)
    value=value.replace('sh','s').replace('v','w').replace('ph','f')
    value=re.sub(r'[aeiou]','',value)
    return re.sub(r'(.)\1+',r'\1',value)


def alternatives(query, store, min_content_matches=2, deadline=None):
    from .textproc import tokenize, ALL_STOPWORDS, stopwords
    import time
    stop = min(deadline or float('inf'),time.monotonic()+.04)
    native={}; grammar={}; ambiguous=set()
    for lang in ('hi','gu'):
        for word in stopwords(lang):
            k=key(word)
            if k:grammar.setdefault(k,word)
    from .store import _decompress
    for row in store.db.conn().execute("SELECT title,body,lang FROM documents WHERE active=1 AND duplicate_of IS NULL AND (lang LIKE 'hi%' OR lang LIKE 'gu%') LIMIT 500"):
        if time.monotonic() >= stop: break
        if row['lang'].split('-')[0] not in ('hi','gu'):
            continue
        tokens=tokenize(row['title']+' '+_decompress(row['body'])[:20000])
        mapping={key(w):w for w in tokens if not w.isascii() and key(w) and w not in ALL_STOPWORDS and len(key(w))>=2}
        for k,v in mapping.items():
            if k in native and native[k]!=v: ambiguous.add(k)
            native[k]=v
    for k in ambiguous: native.pop(k,None)
    words=tokenize(query)
    matched=[w for w in words if w.isascii() and key(w) in native and len(key(w))>=2]
    if len(set(matched))<min_content_matches:
        return None
    return ' '.join(native.get(key(w),grammar.get(key(w),w)) if w.isascii() else w for w in words)
