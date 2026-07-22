from __future__ import annotations

import sys
import unittest
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT))

from src.rrf import fuse


class RrfTests(unittest.TestCase):
    def test_rrf_preserves_course_evidence_and_has_stable_tie_break(self):
        def hit(chunk, rank):
            return {"research_chunk_id": chunk, "course_id": "C1", "rank": rank, "research_evidence_ids": ["rev_" + chunk], "citations": [{"research_evidence_id": "rev_" + chunk, "citation_key": chunk}]}
        sparse = {"status": "ok", "hits": [hit("b", 1), hit("a", 2)]}
        dense = {"status": "ok", "hits": [hit("a", 1), hit("b", 2)]}
        fused = fuse("rq", "C1", sparse, dense, k=60, sparse_weight=1, dense_weight=1, top_k=2)
        self.assertEqual([row["research_chunk_id"] for row in fused["hits"]], ["a", "b"])
        self.assertEqual(fused["hits"][0]["research_evidence_ids"], ["rev_a"])


if __name__ == "__main__": unittest.main()
