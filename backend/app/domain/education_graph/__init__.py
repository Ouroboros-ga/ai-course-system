"""P1-05 Education Graph domain models.

Contracts owned by P1-05 (per plan SS5 and contract registry):
- EducationalUnit: deterministic Course/Chapter/Section/Page/SourceBlock hierarchy
- GraphNode / GraphRelation: evidence-backed graph nodes and edges
- GraphSnapshot: immutable snapshot with active pointer (can roll back)
- ReviewStatus state machine: candidate -> accepted | needs_review -> accepted | rejected

Consumed contracts (frozen):
- P1-01 document-ir/1.0: DocumentIR stable IDs (doc_, unit_, blk_ prefixes)
- P1-03 evidence/1.0: EvidenceSpan, EvidenceBundle

Design invariants:
1. Every accepted node/edge MUST resolve to valid P1-03 Evidence.
2. LLM output is CANDIDATE data, never accepted truth.
3. Graph failures must NOT break document retrieval.
4. Neo4j/GraphRAG is NOT the default path (later comparison trial only).
"""
