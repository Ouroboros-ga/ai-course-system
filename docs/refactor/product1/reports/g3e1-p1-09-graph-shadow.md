# P1-09 G3E1 Delivery Report: Knowledge-Graph Shadow

> Agent: P1-09 (executed directly, dual-hat; main repo clean)
> Date: 2026-07-15
> Baseline: `cae0a62` (G3D merged)
> ADR: ADR-0006 §G3E1 (human-authorized)

## 1. Scope
Modified (P1-09-owned):
- `services/document_service.py` (G3E1 seam in `process_document`, after V1 RAG retrieval / after G3B seam; `enable_rag`-guarded, double try/except)
- `platform/shadow/graph_shadow.py` (new, G3E1)
- `tests/shadow/test_graph_shadow.py` (new, 19 tests)
- This report

NOT modified (verified): `document.py` routes, `qa_service.py`, `chat.py`, `prerequisite_service.py`, `knowledge_service.py`, `knowledge.py` endpoints, `database.py`, `conftest.py`, `fakes.py`, frontend, ORM/migration, `main.py`, locks, `core/config.py`, `core/feature_flags.py`.

## 2. G3E1 Graph Shadow
- Seam: `document_service.process_document` AFTER `rag_processor.process` (V1 retrieval already done) and after the G3B doc-shadow seam, BEFORE `return DocumentProcessResult`. `enable_rag`-guarded. Double try/except: `trigger_graph_shadow` catches all errors internally (business-level fail-closed); outer try/except is a second safety net.
- `graph_shadow.py`: flag-gated `KNOWLEDGE_GRAPH_PIPELINE_VERSION` effectively `v2_shadow` (conflict-aware: requires `DOCUMENT_KG_RUNTIME_MODE` and `DOCUMENT_PIPELINE_VERSION` also v2_shadow via `resolve_effective_modes`).
- V2 candidates derived OFFLINE from V1 RAG knowledge points (`RAGProcessor._extract_knowledge_points` output — `id/title/content/path/level`). **No LLM call** (`llm_calls == 0` always). For each knowledge point: one P1-05 `EducationalUnit` (referencing synthesized DocumentIR block_ids) + one `GraphNode` (PROPOSED). Structural `CONTAINS` relations inferred from the knowledge-point path hierarchy (deterministic; no evidence needed). No semantic relations synthesized (they would need evidence).
- **Isolated shadow graph store**: an in-memory P1-05 `InMemoryGraphStore` serialized to an isolated JSON directory (`GraphShadowStore`, path-traversal safe, atomic write). **Never touches V1 `KnowledgePoint`/`KnowledgeRelation`** — never calls `KnowledgePointService`/`KnowledgeRelationService`/`session.add`. Trace records `v1_tables_touched: False`.
- **Accepted -> Evidence invariant**: a node is ACCEPTED only via `GraphStore.accept_node(node_id, evidence_bundle, ...)` which REQUIRES an `EvidenceBundle` and records its `bundle_id` in `node.evidence_ids`. In the default offline document-time scenario no evidence is available (`evidence_block_ids` empty) -> all candidates stay PROPOSED -> invariant holds vacuously (no accepts without evidence). With `evidence_block_ids` populated, matching nodes are ACCEPTED and each carries a non-empty `evidence_ids`. Trace records `accepted_traces_evidence` as a runtime self-check.
- **Graph failures must not break retrieval**: seam is post-retrieval; shadow is business fail-closed; V1 never affected.
- V1-vs-V2 trace = contract/integration diff (NOT quality comparison). No answer/quality fields.

## 3. Tests (19)
- Flag-gated (3): disabled no-trigger; v2_shadow triggers+writes; conflict downgrade no-trigger.
- No LLM (2): `llm_calls == 0` on success and on fail-closed.
- V1 isolation (3): never calls V1 knowledge service; never raises into V1; trace isolated from V1.
- Accepted -> Evidence (3): no-evidence all-PROPOSED; evidence-backed all-ACCEPTED with evidence_ids; partial-evidence partial-accept.
- Structural relations (2): CONTAINS from hierarchy (parent '力学' -> child '牛顿第二定律'); flat -> no relations.
- Diff shape (1): contract/integration, not quality; no answer/quality fields.
- Edge cases (2): empty knowledge points; None course_id (document-scoped).
- Store + result (3): path-traversal reject; atomic write (no .tmp); frozen result.

## 4. Exit Gate (ADR-0006 §G3E1)
| Gate | Result |
| --- | --- |
| G3E1 tests | 19 passed |
| V1 knowledge CRUD == M7 (seam no-op by default) | confirmed (default v1_only -> no-op, no trace) |
| V2 graph shadow traces to Evidence | confirmed (accept_node requires EvidenceBundle) |
| accepted nodes/edges MUST have Evidence | confirmed (invariant self-check `accepted_traces_evidence`) |
| close flag -> graph shadow stops | confirmed (flag-gated; disabled/v1_only -> no trigger) |
| graph failures don't break retrieval | confirmed (post-retrieval seam, double try/except, fail-closed) |
| V1 tables untouched | confirmed (`v1_tables_touched: False`; no KnowledgePointService calls) |
| `git diff --check` | clean |

## 5. Regression
- G3E1 tests: 19 passed.
- Worktree full regression (with G3E1): 981 passed, 28 failed, 12 errors.
- Baseline `cae0a62` full regression (without G3E1): 962 passed, 28 failed, 12 errors.
- **Delta: +19 passed, 0 new failures, 0 new errors.** The 28 failures + 12 errors are pre-existing at `cae0a62` (infrastructure-dependent integration tests requiring DB/external services + the pre-existing `product1/conftest.py` `pytest_plugins` collection issue from `abf4213`) — unchanged by G3E1. Matches G3D's "subset regression" exclusion of these.
- shadow + feature_flags combined: 104 passed (85 prior + 19 G3E1).

## 6. G3E1 Stop Point
G3E1 complete. **NOT proceeding to G3E2 or G4** (G3E2 awaits this exit; G4 awaits human go after G3E2).
