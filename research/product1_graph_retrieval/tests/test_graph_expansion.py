from __future__ import annotations

import unittest

from src.graph_expansion import OneHopStructuralExpander


class GraphExpansionTests(unittest.TestCase):
    def test_expansion_is_one_hop_course_closed_active_and_cited(self) -> None:
        evidence = [
            {"research_evidence_id": "e1", "course_id": "C1", "status": "active", "citation_key": "c1", "artifact_id": "a", "block_id": "b1", "page_or_slide": 1},
            {"research_evidence_id": "e2", "course_id": "C1", "status": "active", "citation_key": "c2", "artifact_id": "a", "block_id": "b2", "page_or_slide": 1},
            {"research_evidence_id": "e3", "course_id": "C2", "status": "active", "citation_key": "c3", "artifact_id": "a", "block_id": "b3", "page_or_slide": 1},
        ]
        corpus = [
            {"research_chunk_id": "seed", "course_id": "C1", "block_id": "b1", "page_or_slide": 1, "research_evidence_ids": ["e1"]},
            {"research_chunk_id": "expanded", "course_id": "C1", "block_id": "b2", "page_or_slide": 1, "research_evidence_ids": ["e2"]},
            {"research_chunk_id": "other_course", "course_id": "C2", "block_id": "b3", "page_or_slide": 1, "research_evidence_ids": ["e3"]},
        ]
        nodes = [
            {"node_id": "slide", "node_type": "PPTSlide", "course_id": "C1", "source_id": "s", "properties": {"slide_number": 1}},
            {"node_id": "script", "node_type": "ScriptNode", "course_id": "C1", "source_id": "b2", "properties": {}},
            {"node_id": "bad_script", "node_type": "ScriptNode", "course_id": "C2", "source_id": "b3", "properties": {}},
        ]
        edges = [
            {"edge_id": "good", "subject_node_id": "slide", "object_node_id": "script", "course_id": "C1", "predicate": "MAPPED_TO", "source": "slide_block_structure", "status": "accepted", "research_evidence_ids": ["e2"]},
            {"edge_id": "bad", "subject_node_id": "slide", "object_node_id": "bad_script", "course_id": "C1", "predicate": "MAPPED_TO", "source": "slide_block_structure", "status": "accepted", "research_evidence_ids": ["e3"]},
        ]
        expander = OneHopStructuralExpander(corpus=corpus, evidence=evidence, nodes=nodes, edges=edges)
        query = {"research_query_id": "q", "course_id": "C1"}
        baseline = {"status": "ok", "hits": [{"research_chunk_id": "seed", "course_id": "C1", "page_or_slide": 1, "block_id": "b1", "research_evidence_ids": ["e1"], "score": 1.0, "rank": 1, "citations": []}]}
        result = expander.expand(query, baseline, seed_k=1, relation_budget_per_seed=5, graph_candidate_budget=5, final_candidate_k=5, score_decay=0.5)
        self.assertEqual([hit["research_chunk_id"] for hit in result["hits"]], ["seed", "expanded"])
        self.assertEqual(result["hits"][1]["citations"][0]["research_evidence_id"], "e2")
        self.assertEqual(result["hits"][1]["feature_trace"]["graph_edge_id"], "good")


if __name__ == "__main__":
    unittest.main()
