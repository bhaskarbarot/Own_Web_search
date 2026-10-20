"""Text analysis: tokenizer (Latin, Indic, Arabic, CJK), accent folding, stopwords and a Porter stemmer."""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

# \w in Python's re does not include combining marks, which breaks Indic and Arabic words
# (e.g. Hindi vowel signs). Add the mark ranges explicitly.
_MARKS = ("̀-ͯ҃-҉֑-ׇؐ-ًؚ-ٰٟۖ-ۭ"
          "ऀ-෿฀-๿຀-໿ༀ-࿿က-႟ក-៿")
_WC = rf"(?:[^\W_]|[{_MARKS}])"
_TOKEN_RE = re.compile(rf"\d+(?:[.,]\d+)+|{_WC}+(?:['’]{_WC}+)*")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
# Devanagari (Hindi/Marathi/Nepali) and Gujarati Unicode ranges
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_GUJARATI_RE = re.compile(r"[઀-૿]")
MAX_TOKEN_LEN = 64


def _load_stopwords(lang):
    path = Path(__file__).with_name("resources") / f"stopwords_{lang}.txt"
    try:
        return frozenset(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.lstrip().startswith("#"))
    except OSError:
        return frozenset()


STOPWORDS = _load_stopwords("en")
STOPWORDS_HI = _load_stopwords("hi")
STOPWORDS_GU = _load_stopwords("gu")
ALL_STOPWORDS = STOPWORDS | STOPWORDS_HI | STOPWORDS_GU


def detect_script(text):
    """Return the dominant script of the text: 'devanagari', 'gujarati', 'latin', 'cjk', or 'mixed'."""
    if not text:
        return "latin"
    deva = len(_DEVANAGARI_RE.findall(text))
    guj = len(_GUJARATI_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    counts = {"devanagari": deva, "gujarati": guj, "cjk": cjk, "latin": latin}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return "latin"
    # If more than one script has significant presence, call it mixed
    second = sorted(counts.values(), reverse=True)[1]
    if second > 0 and counts[best] / (second + counts[best]) < 0.7:
        return "mixed"
    return best


def detect_language(text):
    """Best-effort language detection from script. Returns a 2-letter ISO code or 'unk'."""
    script = detect_script(text)
    if script == "devanagari":
        return "hi"
    if script == "gujarati":
        return "gu"
    if script == "cjk":
        return "ja"
    return "en"


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


# ------------------------------------------------------------------ Hindi light stemmer

# Common Hindi grammatical suffixes (longest first). These are inflectional markers,
# not topic-specific, so stripping them improves recall without harming precision.
_HI_SUFFIXES = [
    "करने", "करना", "करके", "करकर", "करते", "करती", "करता",
    "वालों", "वाला", "वाली", "वाले", "वाले",
    "ों", "एं", "ां", "ों", "ाँ",
    "ने", "ना", "नी", "ने",
    "कर", "कार",
    "ा", "ी", "े", "ि", "ु", "ू",
]
_HI_SUFFIXES.sort(key=len, reverse=True)


def _stem_hindi(word):
    """Light stemmer for Devanagari (Hindi/Marathi/Nepali). Strips grammatical suffixes."""
    if not _DEVANAGARI_RE.search(word):
        return word
    for suf in _HI_SUFFIXES:
        if word.endswith(suf) and len(word) > len(suf) + 1:
            return word[: -len(suf)]
    return word


@lru_cache(maxsize=200_000)
def stem(word):
    w = word
    if len(w) <= 2:
        return w
    if not w.isascii():
        # Non-ASCII: try Hindi light stemming; leave other scripts untouched
        if _DEVANAGARI_RE.search(w):
            return _stem_hindi(w)
        return w
    if not w.isalpha():
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
    """[(surface, term, is_stopword)] in order. Stopwords checked across all supported languages."""
    return [(t, stem(t), t in ALL_STOPWORDS) for t in tokenize(text)]
