"""Text analysis: tokenizer (Latin, Indic, Arabic, CJK), accent folding, stopwords and a Porter stemmer."""
import re
import unicodedata
from functools import lru_cache

# \w in Python's re does not include combining marks, which breaks Indic and Arabic words
# (e.g. Hindi vowel signs). Add the mark ranges explicitly.
_MARKS = ("̀-ͯ҃-҉֑-ׇؐ-ًؚ-ٰٟۖ-ۭ"
          "ऀ-෿฀-๿຀-໿ༀ-࿿က-႟ក-៿")
_WC = rf"(?:[^\W_]|[{_MARKS}])"
_TOKEN_RE = re.compile(rf"\d+(?:[.,]\d+)+|{_WC}+(?:['’]{_WC}+)*")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
MAX_TOKEN_LEN = 64

STOPWORDS = frozenset("""
a about above after again against all am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here
here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself
let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves
out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the their
theirs them themselves then there there's these they they'd they'll they're they've this those through
to too under until up very was wasn't we we'd we'll we're we've were weren't what what's when when's
where where's which while who who's whom why why's with won't would wouldn't you you'd you'll you're
you've your yours yourself yourselves dont doesnt didnt isnt arent wasnt werent cant couldnt wont
wouldnt shouldnt hasnt havent hadnt im ive id youre theyre thats whats lets also just will shall may
""".split())


def _fold(tok):
    """Remove accents from Latin letters only (keeps Indic/Arabic combining marks intact)."""
    if tok.isascii():
        return tok
    out = []
    for ch in unicodedata.normalize("NFD", tok):
        if unicodedata.combining(ch) and out and ord(out[-1]) < 0x250:
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def tokenize(text):
    """Lowercased surface tokens (no stemming). Possessive 's and apostrophes removed; CJK split per char."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    out = []
    has_cjk = _CJK_RE.search(text) is not None
    for tok in _TOKEN_RE.findall(text):
        if "'" in tok or "’" in tok:
            tok = tok.replace("’", "'")
            if tok.endswith("'s"):
                tok = tok[:-2]
            tok = tok.replace("'", "")
        if has_cjk and _CJK_RE.search(tok):
            buf = ""
            for ch in tok:
                if _CJK_RE.match(ch):
                    if buf:
                        out.append(_fold(buf))
                        buf = ""
                    out.append(ch)
                else:
                    buf += ch
            if buf:
                out.append(_fold(buf))
        elif tok:
            out.append((tok if tok.isascii() else _fold(tok))[:MAX_TOKEN_LEN])
    return out


# ------------------------------------------------------------------ Porter stemmer (1980)

def _cons(w, i):
    c = w[i]
    if c in "aeiou":
        return False
    if c == "y":
        return i == 0 or not _cons(w, i - 1)
    return True


def _measure(stem):
    n, i, length = 0, 0, len(stem)
    while i < length and _cons(stem, i):
        i += 1
    while True:
        while i < length and not _cons(stem, i):
            i += 1
        if i >= length:
            return n
        while i < length and _cons(stem, i):
            i += 1
        n += 1
        if i >= length:
            return n


def _has_vowel(stem):
    return any(not _cons(stem, i) for i in range(len(stem)))


def _double_cons(w):
    return len(w) >= 2 and w[-1] == w[-2] and _cons(w, len(w) - 1)


def _cvc(w):
    return (len(w) >= 3 and _cons(w, len(w) - 3) and not _cons(w, len(w) - 2)
            and _cons(w, len(w) - 1) and w[-1] not in "wxy")


_STEP2 = [("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"),
          ("bli", "ble"), ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
          ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"),
          ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
          ("logi", "log")]
_STEP3 = [("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"),
          ("ful", ""), ("ness", "")]
_STEP4 = ["al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion",
          "ou", "ism", "ate", "iti", "ous", "ive", "ize"]
_STEP2.sort(key=lambda x: -len(x[0]))
_STEP3.sort(key=lambda x: -len(x[0]))
_STEP4.sort(key=len, reverse=True)


@lru_cache(maxsize=200_000)
def stem(word):
    w = word
    if len(w) <= 2 or not w.isascii() or not w.isalpha():
        return w
    # step 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # step 1b
    flag = False
    if w.endswith("eed"):
        if _measure(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _has_vowel(w[:-2]):
        w, flag = w[:-2], True
    elif w.endswith("ing") and _has_vowel(w[:-3]):
        w, flag = w[:-3], True
    if flag:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _double_cons(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _measure(w) == 1 and _cvc(w):
            w += "e"
    # step 1c
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # step 2
    for suf, rep in _STEP2:
        if w.endswith(suf):
            if _measure(w[:-len(suf)]) > 0:
                w = w[:-len(suf)] + rep
            break
    # step 3
    for suf, rep in _STEP3:
        if w.endswith(suf):
            if _measure(w[:-len(suf)]) > 0:
                w = w[:-len(suf)] + rep
            break
    # step 4
    for suf in _STEP4:
        if w.endswith(suf):
            base = w[:-len(suf)]
            if _measure(base) > 1 and (suf != "ion" or base.endswith(("s", "t"))):
                w = base
            break
    # step 5
    if w.endswith("e"):
        base = w[:-1]
        m = _measure(base)
        if m > 1 or (m == 1 and not _cvc(base)):
            w = base
    if w.endswith("ll") and _measure(w) > 1:
        w = w[:-1]
    return w


def analyze(text):
    """Index/query terms: tokenize + stem."""
    return [stem(t) for t in tokenize(text)]


def analyze_query_words(text):
    """[(surface, term, is_stopword)] in order."""
    return [(t, stem(t), t in STOPWORDS) for t in tokenize(text)]
