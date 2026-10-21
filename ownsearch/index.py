"""High-performance in-memory inverted index and BM25 candidate retrieval.

Maintains term postings across title, headings, URL path, and content fields,
with dedicated indices for image and video metadata. Supports incremental
indexing, fast hard-constraint filtering, and sub-millisecond candidate ranking.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math
import threading
import time
from urllib.parse import unquote, urlsplit

from .rankweights import FIELD_WEIGHTS, FIELD_B, K1
from .textproc import analyze, exact_tokens
from .webranking import constraints, rank, merge
from .webmodels import WebCandidate

@dataclass
class ImageEntry:
    image_id: int
    image_url: str
    page_url: str
    caption: str
    alt: str
    doc_id: int

@dataclass
class DocEntry:
    doc_id: int
    url: str
    item: WebCandidate
    field_lens: tuple          # (title_len, headings_len, path_len, 0, content_len)
    all_terms: set
    title_terms: set
    path_terms: set
    expires_at: float
    has_images: bool
    has_video: bool
    image_ids: list = field(default_factory=list)


class InvertedIndex:
    def __init__(self):
        self.lock = threading.RLock()
        self.doc_counter = 0
        self.image_counter = 0
        self.docs = {}                 # doc_id -> DocEntry
        self.url_to_id = {}            # url -> doc_id
        self.postings = defaultdict(dict)  # term -> {doc_id: (tf_title, tf_heading, tf_path, tf_content)}
        self.total_field_lens = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.image_postings = defaultdict(list) # term -> [image_id, ...]
        self.image_entries = {}        # image_id -> ImageEntry
        self.video_docs = set()        # set of doc_id

    def __len__(self):
        with self.lock:
            return len(self.docs)

    def _avg_lens(self):
        n = max(1, len(self.docs))
        return [max(1.0, total / n) for total in self.total_field_lens]

    def add_page(self, page, expires_at=None):
        """Incrementally index a CrawledPage."""
        if not page or not page.item:
            return None
        item = page.item
        now = time.monotonic()
        expires = expires_at if expires_at is not None else (now + 3600.0)

        with self.lock:
            # If already present, remove old version first
            if item.url in self.url_to_id:
                self.remove_url(item.url)

            self.doc_counter += 1
            doc_id = self.doc_counter

            # Tokenize fields
            t_tokens = analyze(item.title)
            h_tokens = analyze(' '.join(item.headings))
            p_tokens = analyze(unquote(urlsplit(item.url).path))
            c_text = item.content if item.fetch_status == 'fetched' else item.snippet
            c_tokens = analyze(c_text)

            t_len = len(t_tokens)
            h_len = len(h_tokens)
            p_len = len(p_tokens)
            c_len = len(c_tokens)
            field_lens = (t_len, h_len, p_len, 0, c_len)

            t_counts = Counter(t_tokens)
            h_counts = Counter(h_tokens)
            p_counts = Counter(p_tokens)
            c_counts = Counter(c_tokens)

            all_terms = set(t_counts) | set(h_counts) | set(p_counts) | set(c_counts)

            # Insert postings
            for term in all_terms:
                tf_t = t_counts.get(term, 0)
                tf_h = h_counts.get(term, 0)
                tf_p = p_counts.get(term, 0)
                tf_c = c_counts.get(term, 0)
                self.postings[term][doc_id] = (tf_t, tf_h, tf_p, tf_c)

            # Update total lengths
            for i in range(5):
                self.total_field_lens[i] += field_lens[i]

            # Index images
            image_ids = []
            for img in item.images:
                self.image_counter += 1
                img_id = self.image_counter
                caption = img.get('caption', '')
                alt = img.get('alt', '')
                entry = ImageEntry(img_id, img.get('image_url', ''), item.url, caption, alt, doc_id)
                self.image_entries[img_id] = entry
                image_ids.append(img_id)
                img_terms = set(analyze(caption + ' ' + alt + ' ' + item.title))
                for term in img_terms:
                    self.image_postings[term].append(img_id)

            has_video = bool(item.video)
            if has_video:
                self.video_docs.add(doc_id)

            doc_entry = DocEntry(
                doc_id=doc_id,
                url=item.url,
                item=item,
                field_lens=field_lens,
                all_terms=all_terms,
                title_terms=set(t_counts),
                path_terms=set(p_counts),
                expires_at=expires,
                has_images=bool(image_ids),
                has_video=has_video,
                image_ids=image_ids
            )
            self.docs[doc_id] = doc_entry
            self.url_to_id[item.url] = doc_id
            return doc_id

    def remove_url(self, url):
        """Remove a URL from the index."""
        with self.lock:
            doc_id = self.url_to_id.pop(url, None)
            if doc_id is None:
                return False
            entry = self.docs.pop(doc_id, None)
            if not entry:
                return False

            # Remove from postings
            for term in entry.all_terms:
                posting = self.postings.get(term)
                if posting:
                    posting.pop(doc_id, None)
                    if not posting:
                        del self.postings[term]

            # Subtract lengths
            for i in range(5):
                self.total_field_lens[i] = max(0.0, self.total_field_lens[i] - entry.field_lens[i])

            # Remove images
            for img_id in entry.image_ids:
                img_entry = self.image_entries.pop(img_id, None)
                if img_entry:
                    img_terms = set(analyze(img_entry.caption + ' ' + img_entry.alt + ' ' + entry.item.title))
                    for term in img_terms:
                        p = self.image_postings.get(term)
                        if p:
                            try:
                                p.remove(img_id)
                                if not p:
                                    del self.image_postings[term]
                            except ValueError:
                                pass

            # Remove video
            self.video_docs.discard(doc_id)
            return True

    def prune(self, now=None):
        """Remove expired documents."""
        now = now or time.monotonic()
        with self.lock:
            expired = [entry.url for entry in self.docs.values() if entry.expires_at <= now]
            for url in expired:
                self.remove_url(url)
            return len(expired)

    def clear(self):
        """Clear the entire index."""
        with self.lock:
            self.docs.clear()
            self.url_to_id.clear()
            self.postings.clear()
            self.total_field_lens = [0.0, 0.0, 0.0, 0.0, 0.0]
            self.image_postings.clear()
            self.image_entries.clear()
            self.video_docs.clear()

    def get_candidate_items(self, q, search_type='web', limit=100):
        """Retrieve pre-filtered candidate WebCandidate objects matching q using the index."""
        with self.lock:
            if not self.docs:
                return []

            terms = list(dict.fromkeys(q.scoring_terms or analyze(q.raw)))

            if not terms:
                # Browse / filter-only query without lexical terms
                candidates = []
                for entry in self.docs.values():
                    if search_type == 'images' and not entry.has_images:
                        continue
                    if search_type == 'video' and not entry.has_video:
                        continue
                    if constraints(entry.item, q, final=False):
                        candidates.append(entry.item)
                        if len(candidates) >= limit:
                            break
                return candidates

            # Term-matching candidates: gather doc_ids matching any query term
            matched_doc_counts = Counter()
            candidate_ids = set()
            for term in terms:
                posting = self.postings.get(term)
                if posting:
                    for did in posting:
                        candidate_ids.add(did)
                        matched_doc_counts[did] += 1

            if not candidate_ids:
                return []

            # If q has required terms or entities, require minimum term overlap
            required = set(q.required or q.entity_terms)
            num_req = len(required)

            # Filter candidates with hard constraints & required terms
            filtered_entries = []
            for did in candidate_ids:
                entry = self.docs.get(did)
                if not entry:
                    continue
                if search_type == 'images' and not entry.has_images:
                    continue
                if search_type == 'video' and not entry.has_video:
                    continue
                if num_req and len(required & entry.all_terms) < min(1, num_req):
                    continue
                if not constraints(entry.item, q, final=False):
                    continue
                filtered_entries.append(entry)

            if not filtered_entries:
                return []

            # Compute fast BM25 score for surviving candidates
            avg_lens = self._avg_lens()
            num_docs = len(self.docs)
            scored = []

            for entry in filtered_entries:
                did = entry.doc_id
                lens = entry.field_lens
                bm25_score = 0.0
                for term in terms:
                    posting = self.postings.get(term)
                    if not posting or did not in posting:
                        continue
                    tf_t, tf_h, tf_p, tf_c = posting[did]
                    df = len(posting)
                    idf = math.log(1.0 + (num_docs - df + 0.5) / (df + 0.5))

                    # Field-weighted TF:
                    # fields: 0=title, 1=heading, 2=path, 3=unused, 4=content
                    tf = (
                        FIELD_WEIGHTS[0] * tf_t / (1.0 - FIELD_B[0] + FIELD_B[0] * lens[0] / avg_lens[0]) +
                        FIELD_WEIGHTS[1] * tf_h / (1.0 - FIELD_B[1] + FIELD_B[1] * lens[1] / avg_lens[1]) +
                        FIELD_WEIGHTS[2] * tf_p / (1.0 - FIELD_B[2] + FIELD_B[2] * lens[2] / avg_lens[2]) +
                        FIELD_WEIGHTS[4] * tf_c / (1.0 - FIELD_B[4] + FIELD_B[4] * lens[4] / avg_lens[4])
                    )
                    if tf > 0:
                        bm25_score += idf * tf * (K1 + 1.0) / (K1 + tf)

                entry.item.score = bm25_score
                scored.append(entry.item)

            scored.sort(key=lambda item: (-getattr(item, 'score', 0.0), item.url))
            top_candidates = scored[:limit * 3]
            return rank(top_candidates, q, final=True)[:limit]

    def search(self, q, limit=10, search_type='web'):
        """Search the inverted index and return fully ranked results."""
        return self.get_candidate_items(q, search_type=search_type, limit=limit)

    def search_images(self, q, limit=20):
        """Retrieve ranked image results directly from the image index."""
        with self.lock:
            terms = list(dict.fromkeys(q.scoring_terms or analyze(q.raw)))
            if not terms:
                # Return newest indexed images
                results = []
                seen_urls = set()
                for entry in reversed(list(self.image_entries.values())):
                    if entry.image_url not in seen_urls:
                        seen_urls.add(entry.image_url)
                        results.append({
                            'image_url': entry.image_url,
                            'page_url': entry.page_url,
                            'caption': entry.caption or entry.alt,
                            'provider': 'indexed_cache'
                        })
                        if len(results) >= limit:
                            break
                return results

            # Score matching images
            scored_images = Counter()
            for term in terms:
                matches = self.image_postings.get(term, [])
                for img_id in matches:
                    scored_images[img_id] += 1

            results = []
            seen_urls = set()
            for img_id, _ in scored_images.most_common(limit * 2):
                entry = self.image_entries.get(img_id)
                if not entry or entry.image_url in seen_urls:
                    continue
                seen_urls.add(entry.image_url)
                results.append({
                    'image_url': entry.image_url,
                    'page_url': entry.page_url,
                    'caption': entry.caption or entry.alt,
                    'provider': 'indexed_cache'
                })
                if len(results) >= limit:
                    break
            return results

    def stats(self):
        """Index status metrics."""
        with self.lock:
            return {
                'indexed_documents': len(self.docs),
                'indexed_terms': len(self.postings),
                'indexed_images': len(self.image_entries),
                'indexed_videos': len(self.video_docs)
            }
