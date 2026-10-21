"""Tests for inverted index, BM25 retrieval, filtering and media indexing."""
import unittest
from ownsearch.index import InvertedIndex
from ownsearch.webfetch import CrawledPage
from ownsearch.webmodels import WebCandidate
from ownsearch.query import parse_query

class TestInvertedIndex(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()

    def make_page(self, url, title, content, detected_kind='html', images=None, video=False):
        item = WebCandidate(title, url, content=content, detected_kind=detected_kind)
        item.fetch_status = 'fetched'
        if images:
            item.images = images
        item.video = video
        return CrawledPage(url, item=item, kind='html')

    def test_add_and_search_bm25(self):
        p1 = self.make_page('https://example.org/p1', 'Python Guide', 'Learn Python programming language tutorials.')
        p2 = self.make_page('https://example.org/p2', 'Rust Guide', 'Rust systems programming language.')
        self.index.add_page(p1)
        self.index.add_page(p2)

        q = parse_query('python programming')
        candidates = self.index.get_candidate_items(q)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'https://example.org/p1')

    def test_incremental_remove_and_prune(self):
        p1 = self.make_page('https://example.org/p1', 'Python Guide', 'Learn Python programming.')
        self.index.add_page(p1, expires_at=10.0)
        self.assertEqual(len(self.index), 1)

        self.index.prune(now=15.0)
        self.assertEqual(len(self.index), 0)

        q = parse_query('python')
        candidates = self.index.get_candidate_items(q)
        self.assertEqual(len(candidates), 0)

    def test_site_filter_applied_early(self):
        p1 = self.make_page('https://docs.python.org/tutorial', 'Python Tutorial', 'Official python documentation.')
        p2 = self.make_page('https://blog.example.com/python', 'Python Tutorial', 'Unofficial python blog.')
        self.index.add_page(p1)
        self.index.add_page(p2)

        q = parse_query('python tutorial site:docs.python.org')
        candidates = self.index.get_candidate_items(q)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'https://docs.python.org/tutorial')

    def test_filetype_filter_applied_early(self):
        p1 = self.make_page('https://example.org/doc.pdf', 'Python Manual', 'Python PDF specification.', detected_kind='pdf')
        p2 = self.make_page('https://example.org/doc.html', 'Python Manual', 'Python HTML manual.', detected_kind='html')
        self.index.add_page(p1)
        self.index.add_page(p2)

        q = parse_query('python manual filetype:pdf')
        candidates = self.index.get_candidate_items(q)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].url, 'https://example.org/doc.pdf')

    def test_dedicated_image_and_video_indexing(self):
        images = [{'image_url': 'https://example.org/logo.png', 'caption': 'Python Logo artwork', 'alt': 'Logo'}]
        p1 = self.make_page('https://example.org/media', 'Python Media', 'Media content.', images=images, video=True)
        p2 = self.make_page('https://example.org/text', 'Python Text', 'Plain text content.')
        self.index.add_page(p1)
        self.index.add_page(p2)

        # Video search
        q_video = parse_query('python')
        video_candidates = self.index.get_candidate_items(q_video, search_type='video')
        self.assertEqual(len(video_candidates), 1)
        self.assertEqual(video_candidates[0].url, 'https://example.org/media')

        # Image search
        q_img = parse_query('logo artwork')
        imgs = self.index.search_images(q_img)
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0]['image_url'], 'https://example.org/logo.png')

if __name__ == '__main__':
    unittest.main()
