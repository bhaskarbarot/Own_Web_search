"""Near-duplicate fingerprints (SimHash) and static page-quality / spam signals."""
import hashlib
import math
import sys
from array import array
from collections import Counter

from .textproc import STOPWORDS
from .util import url_depth

MASK64 = (1 << 64) - 1


_TOKEN_HASH = {}
_P1, _P2, _P3 = 0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9


def _h64(s):
    h = _TOKEN_HASH.get(s)
    if h is None:
        h = int.from_bytes(hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(), "big")
        if len(_TOKEN_HASH) < 500_000:
            _TOKEN_HASH[s] = h
    return h


# bytes whose bit j is set; bytes.translate(None, delete) removes them, so len() difference = popcount column
_HAS_BIT = [bytes(v for v in range(256) if (v >> j) & 1) for j in range(8)]
_LITTLE = sys.byteorder == "little"


def simhash(tokens, shingle=3, max_features=4000):
    """64-bit SimHash over word 3-shingles. Returned signed so it fits in SQLite INTEGER.

    Word hashes are cached; a shingle hash is an order-sensitive combination of three uniformly random word
    hashes. Bit columns are counted in C: all feature hashes are packed into one byte string and each of the
    64 columns is counted with bytes.translate."""
    if not tokens:
        return 0
    hs = [_h64(t) for t in tokens[:max_features + shingle]]
    if len(hs) < shingle:
        feats = {sum(hs) & MASK64}
    else:
        feats = {((a * _P1) ^ (b * _P2) ^ (c * _P3)) & MASK64 for a, b, c in zip(hs, hs[1:], hs[2:])}
    raw = array("Q", feats).tobytes()
    n = len(feats)
    half = n / 2
    value = 0
    for k in range(8):
        column = raw[k::8] if _LITTLE else raw[7 - k::8]
        for j in range(8):
            if n - len(column.translate(None, _HAS_BIT[j])) > half:
                value |= 1 << (8 * k + j)
    return value - (1 << 64) if value >= (1 << 63) else value


def hamming(a, b):
    return bin((a ^ b) & MASK64).count("1")


def simhash_bands(value):
    """Four 16-bit bands: two fingerprints within Hamming distance 3 share at least one band."""
    v = value & MASK64
    return [(i, (v >> (16 * i)) & 0xFFFF) for i in range(4)]


def page_quality(title, tokens, url, n_links=0, hidden_chars=0, text_chars=0):
    """Static quality in [0, 1] from content length, structure, URL shape and spam signals."""
    words = len(tokens)
    if words == 0:
        return 0.05
    length = min(1.0, math.log1p(words) / math.log1p(800))
    score = 0.15 + 0.5 * length
    if title and 3 <= len(title) <= 200:
        score += 0.1
    depth = url_depth(url)
    score += 0.08 * (1.0 / (1 + max(0, depth - 2)))
    if len(url) < 120 and url.count("?") == 0:
        score += 0.05
    content = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    if len(content) > 80:
        top = Counter(content).most_common(1)[0][1] / len(content)
        if top > 0.08:                              # keyword stuffing
            score -= min(0.4, (top - 0.08) * 4)
    if words > 20:
        density = n_links / words
        if density > 0.35:                          # link farm / navigation-only page
            score -= min(0.3, (density - 0.35))
    if text_chars and hidden_chars / max(1, text_chars + hidden_chars) > 0.3:
        score -= 0.25                               # lots of hidden text
    if words < 30:
        score -= 0.15
    return max(0.0, min(1.0, score))
