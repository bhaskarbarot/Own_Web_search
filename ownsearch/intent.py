"""Query-intent classifier learned from data (multinomial naive Bayes over word unigrams and bigrams).

Training data lives in ``resources/intent_templates.tsv`` plus ``<data_dir>/intent_examples.tsv`` (examples
learned later, e.g. from agent feedback). Nothing about specific topics is written in code.

The same statistics separate *query-language* words from *subject* words: a word that appears in many
training queries ("give", "me", "latest", "price", "documentation") describes how people ask or what kind of
result they want; words that are rare in the training queries ("nvidia", "ashok", "inheritance") are the
subject of the query.
"""
import math
import os
import threading
from collections import Counter, defaultdict
from pathlib import Path

from .textproc import stem, tokenize

RESOURCE = Path(__file__).with_name("resources") / "intent_templates.tsv"
_models = {}
_lock = threading.Lock()


def _features(tokens):
    stems = [stem(t) for t in tokens]
    return stems + [a + "_" + b for a, b in zip(stems, stems[1:])]


def _read(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("#") or "\t" not in line:
                    continue
                label, text = line.rstrip("\n").split("\t", 1)
                out.append((label.strip(), text.replace("{subject}", "").strip()))
    except OSError:
        pass
    return out


class IntentModel:
    def __init__(self, examples):
        self.labels = sorted({lab for lab, _ in examples})
        self.class_docs = Counter(lab for lab, _ in examples)
        self.counts = defaultdict(Counter)
        self.doc_freq = Counter()                 # in how many training queries a stem appears
        self.label_spread = defaultdict(set)      # in which intents a stem appears
        for lab, text in examples:
            feats = _features(tokenize(text))
            self.counts[lab].update(feats)
            unigrams = set(f for f in feats if "_" not in f)
            self.doc_freq.update(unigrams)
            for f in unigrams:
                self.label_spread[f].add(lab)
        self.totals = {lab: sum(c.values()) for lab, c in self.counts.items()}
        self.vocab = set().union(*[set(c) for c in self.counts.values()]) if self.counts else set()
        self.n_docs = len(examples)

    def classify(self, text):
        """-> (label, {label: probability}). Unknown words carry no evidence."""
        feats = [f for f in _features(tokenize(text)) if f in self.vocab]
        if not feats or not self.labels:
            return "general", {}
        v = len(self.vocab)
        logp = {}
        for lab in self.labels:
            lp = math.log(self.class_docs[lab] / self.n_docs)
            c, tot = self.counts[lab], self.totals[lab]
            for f in feats:
                lp += math.log((c[f] + 1) / (tot + v))
            logp[lab] = lp
        m = max(logp.values())
        z = sum(math.exp(x - m) for x in logp.values())
        probs = {lab: math.exp(x - m) / z for lab, x in logp.items()}
        best = max(probs, key=probs.get)
        return best, probs

    def is_query_language(self, word, min_share=0.025):
        """True when a word is common in how queries are phrased (learned), i.e. not a subject word."""
        s = stem(word.lower())
        if self.n_docs == 0:
            return False
        # used in several different intents -> a phrasing word, not a topic ("give", "show", "about")
        return len(self.label_spread[s]) >= 2 or self.doc_freq[s] >= max(3, min_share * self.n_docs)

    def cue_strength(self, word, label):
        """How strongly a word indicates a label: P(word|label) / P(word)."""
        s = stem(word.lower())
        tot_all = sum(self.totals.values()) or 1
        p_all = sum(self.counts[l][s] for l in self.labels) / tot_all
        if p_all == 0:
            return 0.0
        return (self.counts[label][s] / (self.totals.get(label) or 1)) / p_all


def get_model(data_dir=None):
    key = str(data_dir or "")
    extra = Path(data_dir) / "intent_examples.tsv" if data_dir else None
    mtime = (os.path.getmtime(RESOURCE) if RESOURCE.exists() else 0,
             os.path.getmtime(extra) if extra and extra.exists() else 0)
    with _lock:
        hit = _models.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        examples = _read(RESOURCE) + (_read(extra) if extra else [])
        model = IntentModel(examples)
        _models[key] = (mtime, model)
        return model


def learn(data_dir, label, text):
    """Append a labelled example (e.g. from feedback); the model reloads automatically."""
    path = Path(data_dir) / "intent_examples.tsv"
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{label}\t{' '.join(text.split())}\n")


def temporal_window(text, model):
    """Date grammar from a resource, applied only to learned query-language words."""
    path = Path(__file__).with_name("resources") / "temporal_phrasing.tsv"
    rules = _read(path)
    words = set(tokenize(text))
    for window, phrase in rules:
        tokens = set(tokenize(phrase))
        if tokens <= words and all(model.is_query_language(w) for w in tokens):
            return window
    return None


def requested_format(text):
    """Recognize output grammar from data, independently of subject and topic."""
    tokens = tokenize(text)
    for form, phrase in _read(Path(__file__).with_name("resources") / "result_formats.tsv"):
        cue = tokenize(phrase)
        if cue and any(tokens[i:i + len(cue)] == cue for i in range(len(tokens) - len(cue) + 1)):
            return form
    return None
