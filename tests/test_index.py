"""Phase 3: incremental index — updates and deletes without full rebuilds, merges, crash recovery, reload."""
import os
import tempfile
import unittest

from ownsearch.indexer import IndexManager
from ownsearch.segments import decode_positions, encode_positions

from tests.helpers import make_engine


def fields(words):
    return {"title": words[:2], "body": words, "meta": ["\x01site:x.org"]}


class SegmentTests(unittest.TestCase):
    def test_positions_roundtrip(self):
        pos = [0, 1, 5, 130, 131, 70000, 70001]
        self.assertEqual(decode_positions(encode_positions(pos)), pos)

    def test_commit_delete_merge(self):
        d = tempfile.mkdtemp()
        im = IndexManager(d, merge_factor=3)
        with im.write_lock():
            for b in range(4):
                im.commit([(b * 10 + i, fields(["alpha", "beta", f"w{i}"]), 100) for i in range(10)], b + 1)
            im.commit([(3, None, 0), (12, fields(["zeta"]), 50)], 5)
            im.maybe_merge()
        snap = im.snapshot()
        self.assertEqual(snap.N, 39)
        self.assertEqual(snap.df("zeta"), 1)
        live = set()
        for ri, r in enumerate(snap.readers):
            p = snap.postings(ri, "alpha")
            if p:
                live.update(r.docids[x] for x in p.docs if not r.is_deleted(x))
        self.assertNotIn(3, live)
        self.assertNotIn(12, live)
        self.assertEqual(len(live), 38)
        self.assertEqual(IndexManager(d).doc_count, 39)       # persisted


class IncrementalTests(unittest.TestCase):
    def test_update_and_delete_are_incremental(self):
        e, _ = make_engine()
        for i in range(50):
            e.add_document(f"Doc {i}", f"common words plus unique{i}", f"local://d{i}", rebuild=False)
        e.rebuild_index()
        gen = e.index.generation
        segs_before = {s["name"] for s in e.index.manifest["segments"]}
        e.add_document("Doc 7", "completely new content kumquat", "local://d7")
        self.assertEqual(e.search("kumquat", 5)["results"][0]["url"], "local://d7")
        self.assertEqual(e.search("unique7", 5)["results"], [])
        self.assertGreater(e.index.generation, gen)
        self.assertTrue(segs_before & {s["name"] for s in e.index.manifest["segments"]},
                        "old segments must be reused, not rebuilt")
        e.store.deactivate(url="local://d8")
        e.rebuild_index()
        self.assertEqual(e.search("unique8", 5)["results"], [])
        self.assertEqual(e.index.doc_count, 49)

    def test_crash_recovery_reapplies_uncommitted_changes(self):
        e, tmp = make_engine()
        e.add_document("Persisted", "this was committed", "local://a")
        # simulate a crash: the store has changes the index never committed
        e.store.upsert("local://b", "Pending", "written but never indexed papaya")
        from ownsearch.engine import SearchEngine
        e2 = SearchEngine(settings=e.settings)               # restart
        self.assertEqual(len(e2.search("papaya", 5)["results"]), 1)

    def test_orphan_segment_files_are_cleaned(self):
        e, tmp = make_engine()
        e.add_document("A", "alpha text", "local://a")
        junk = os.path.join(e.settings.index_dir, "seg_99999999.post.tmp")
        with open(junk, "wb") as f:
            f.write(b"partial write")
        e.add_document("B", "beta text", "local://b")
        self.assertFalse(os.path.exists(junk))

    def test_second_process_sees_new_documents(self):
        e, tmp = make_engine()
        e.add_document("First", "first doc", "local://1")
        from ownsearch.engine import SearchEngine
        reader = SearchEngine(settings=e.settings)
        self.assertEqual(reader.index.doc_count, 1)
        e.add_document("Second", "second doc grapefruit", "local://2")
        reader.index._last_check = 0
        self.assertEqual(len(reader.search("grapefruit", 5, use_cache=False)["results"]), 1)


if __name__ == "__main__":
    unittest.main()
