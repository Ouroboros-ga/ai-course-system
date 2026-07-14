"""Storage design proposal for P1-09.

This file is a design proposal only -- P1-09 owns ORM/migration/endpoint
implementation.  It describes the recommended table structure, indexing,
and migration strategy for the education graph persistence layer.

Reference: R2D0 Storage and Migration plan SS2, SS5, SS6.
"""

STORAGE_PROPOSAL = """
# Education Graph Storage Proposal (for P1-09)

## Core Design Principles

1. GraphStore is the sole abstraction boundary. Domain code never imports ORM models.
2. Snapshots are immutable after creation. Active pointer can be rolled back.
3. Every accepted node/edge is traceable to P1-03 Evidence.
4. V2 shadow data is isolated from V1 tables.
5. Migration is reversible and versioned.

## Recommended Table Structure

### educational_unit
- unit_id (PK, stable UUIDv5 from document_id + type + ordinal)
- course_id (FK to course table)
- parent_id (nullable FK self-ref for hierarchy)
- unit_type (enum: course|chapter|section|page|source_block)
- ordinal (int, nullable)
- title (varchar)
- doc_id (varchar, nullable -- P1-01 DocumentIR document_id)
- block_refs (JSON array of stable block_ids)
- version (int, default 1)
- ontology_version (varchar, default 'edu-graph/1.0')
- properties (JSON)
- created_at, updated_at

Index: (course_id, parent_id), (doc_id), (unit_type, course_id)

### graph_node
- node_id (PK, stable UUIDv5 from type + canonical_key)
- snapshot_id (FK to graph_snapshot, nullable -- for snapshot membership)
- unit_id (FK to educational_unit)
- node_type (enum)
- canonical_key (varchar, unique within snapshot+type)
- label (varchar)
- aliases (JSON array of strings)
- properties (JSON)
- status (enum: proposed|accepted|rejected|needs_review|superseded)
- confidence (float, 0.0-1.0)
- ontology_version (varchar)
- created_at, updated_at

Unique constraint: (snapshot_id, node_type, canonical_key) -- but only for
accepted nodes in active snapshot. Proposed/rejected can have duplicates.

Index: (unit_id), (node_type), (status), (canonical_key)

### graph_relation
- relation_id (PK, stable UUIDv5 from source_id + type + target_id)
- snapshot_id (FK to graph_snapshot, nullable)
- source_id (FK to graph_node)
- target_id (FK to graph_node)
- relation_type (enum)
- directed (boolean, default true)
- properties (JSON)
- status (enum)
- confidence (float)

Unique constraint: (snapshot_id, source_id, relation_type, target_id)
Index: (source_id), (target_id), (source_id, relation_type)

### graph_evidence
- evidence_id (PK)
- bundle_id (varchar, stable)
- subject_kind (varchar: 'node' or 'relation')
- subject_id (varchar: node_id or relation_id)
- snapshot_id (FK, nullable)
- doc_id (varchar, P1-01 doc_id)
- block_id (varchar, P1-01 block_id)
- text_snippet (varchar, nullable)
- status (varchar: active|stale|suspended)
- source_run_id (varchar, nullable)
- created_at

Index: (subject_kind, subject_id), (bundle_id), (block_id)

### graph_snapshot
- snapshot_id (PK, UUIDv4/ULID)
- course_id (varchar, FK to course)
- ontology_version (varchar)
- label (varchar, nullable)
- metadata (JSON)
- status (varchar: active|archived)
- created_at

Unique constraint per course: at most one snapshot with status='active'
This can be enforced via partial index or application-level check.

### graph_review_decision
- decision_id (PK)
- snapshot_id (FK to graph_snapshot)
- target_kind (varchar: 'node' or 'relation')
- target_id (varchar)
- decision (varchar: accepted|rejected)
- reviewer (varchar)
- review_comment (text)
- evidence_bundle_id (varchar, nullable)
- created_at

## Snapshot Lifecycle

1. Create snapshot: INSERT into graph_snapshot + copy accepted nodes/relations
   into snapshot-scoped rows (snapshot_id populated).
2. Activate: UPDATE course_pointer_table SET active_snapshot_id = ?
3. Rollback: UPDATE course_pointer_table SET active_snapshot_id = ? (previous)
4. No in-place mutation of snapshot data.

## Migration Strategy

Phase 1 (shadow only, no V1 impact):
- Create all tables as described above.
- All inserts go to new tables only.
- No reads from V1 tables.

Phase 2 (active pointer):
- Add course_document_pipeline_state table with active_snapshot_id.
- Atomic switch via transaction.

Phase 3 (compatibility projection):
- Read from V2 graph, project to V1 KnowledgePoint/KnowledgeRelation.
- This is OPTIONAL and only for legacy API compatibility.

## Key Differences from R2D0 Storage Plan

1. Removed `graph_mention` table (merged into graph_evidence).
2. Added `graph_review_decision` table (teacher review audit trail).
3. Simplified `educational_unit` table (no separate run_id tracking).
4. Snapshot membership via FK rather than copy (simpler for in-memory, but
   production should snapshot-scope rows for immutability guarantees).
"""
