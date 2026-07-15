# P1-10 G3E Independent Verification Report

> Verifier: P1-10 (P1-00 dual-hat)
> Date: 2026-07-15
> Subject: P1-09 G3E1 commit `c714be2` (baseline `cae0a62`) + G3E2 diff report
> Verdict: **PASS**. Approved to merge.
> ADR: ADR-0006 §G3E1/G3E2

## 1. Scope compliance
- Files changed in `cae0a62..c714be2`: 4 (graph_shadow.py new, document_service.py +20 seam, test_graph_shadow.py new, g3e1 report new). All P1-09-owned.
- V1 shared files **UNCHANGED** (git diff empty `cae0a62..c714be2`): `document.py`, `qa_service.py`, `chat.py`, `prerequisite_service.py`, `knowledge_service.py`, `knowledge.py` endpoints, `database.py`, `conftest.py`, `fakes.py`, `main.py`, `core/config.py`, `core/feature_flags.py`. (12/12 verified.)
- Main workspace clean throughout (direct execution, no isolation failure - pattern holds G3A..G3E1).

## 2. Hard constraints (ADR §G3E1)
- **NEVER touches V1 KnowledgePoint/KnowledgeRelation**: `trigger_graph_shadow` uses only `InMemoryGraphStore` + isolated JSON; never calls `KnowledgePointService`/`KnowledgeRelationService`/`session.add`. Trace records `v1_tables_touched: false`. Tested (`test_never_calls_v1_knowledge_service` patches all 3 V1 service methods -> none called).
- **Accepted -> Evidence invariant**: `accept_node` requires an `EvidenceBundle`; accepted nodes carry non-empty `evidence_ids`. Self-check `accepted_traces_evidence` in trace. Tested: no-evidence -> all PROPOSED (0 accepted, invariant holds vacuously); evidence-backed -> all ACCEPTED with evidence_ids; partial -> partial.
- **Graph failures never break retrieval**: seam is post-retrieval (after `rag_processor.process`), `enable_rag`-guarded, double try/except, business fail-closed. Tested (`test_shadow_never_raises_into_v1`).
- **No LLM**: `llm_calls == 0` always (offline from V1 RAG knowledge points). Tested on success + fail-closed.
- **Conflict-aware flag gate**: `KNOWLEDGE_GRAPH_PIPELINE_VERSION` effective v2_shadow requires `DOCUMENT_KG_RUNTIME_MODE` + `DOCUMENT_PIPELINE_VERSION` v2_shadow. Tested (conflict downgrade -> no trigger).

## 3. Default == M7
`KNOWLEDGE_GRAPH_PIPELINE_VERSION` default `v1_only` -> seam no-op (no trace, no error). V1 == M7. Tested (`test_disabled_no_trigger`).

## 4. Regression
- G3E1 tests: **19 passed**.
- Worktree full regression (with G3E1): 981 passed, 28 failed, 12 errors.
- Baseline `cae0a62` full regression (without G3E1): 962 passed, 28 failed, 12 errors.
- **Delta: +19 passed, 0 new failures, 0 new errors.** The 28 failures + 12 errors are pre-existing at `cae0a62` (infrastructure-dependent integration tests requiring DB/external services + the pre-existing `product1/conftest.py` `pytest_plugins` collection issue from `abf4213`) - unchanged by G3E1.
- shadow + feature_flags combined: 104 passed.

## 5. G3E2 Shadow Diff Report
- `docs/refactor/product1/reports/g3e2-shadow-diff-report.json` (machine-readable, valid JSON).
- Covers all 6 shadow paths G3B..G3E1: G3B (doc parse), G3C (evidence/retrieval/citation), G3D1 (learning event), G3D2 (memory candidate), G3D3 (safety dry-run), G3E1 (graph).
- Each path records: flag, effective_requires, seam, v1_input, v2_output_contracts, diff_dimensions, invariants, llm_calls, isolation, default_mode, rollback.
- Diff type = contract/integration (NOT quality); quality deferred to G5 canary.
- Aggregate invariants: all_shadows_llm_calls_zero, all_shadows_default_noop, all_shadows_isolated_writes, all_shadows_business_fail_closed, all_shadows_close_flag_restores_v1, v1_tables_never_written_by_shadow, accepted_graph_elements_trace_to_evidence - all true.

## 6. Verdict
**PASS**. Recommend merge `c714be2` + G3E2 report. G3E (G3E1 + G3E2) complete. **G4 NOT authorized** (awaits human go; G4A = Evidence API DTO freeze `internal-evidence-api/1.0`).
