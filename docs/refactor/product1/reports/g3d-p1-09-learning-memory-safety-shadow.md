# P1-09 G3D Delivery Report: Learning/Memory/Safety Shadow

> Agent: P1-09 (executed directly, dual-hat; main repo clean)
> Date: 2026-07-14
> Baseline: `be78413` (G3C merged)
> ADR: ADR-0006 §G3D1/D2/D3 (human-authorized, three batches connected)

## 1. Scope
Modified (P1-09-owned):
- `prerequisite_service.py` (G3D1 seam in create_jump_record, post-commit)
- `qa_service.py` (G3D2 + G3D3 seams in ask_question_with_rag; +optional student_id param, backward-compatible)
- `platform/shadow/learning_shadow.py` (new, G3D1)
- `platform/shadow/memory_candidate_shadow.py` (new, G3D2)
- `platform/shadow/safety_dryrun_shadow.py` (new, G3D3)
- 3 test files (27 tests)
- This report

NOT modified (verified): chat.py, document.py, progress.py, prerequisite.py endpoints, database.py, conftest.py, fakes.py, frontend, ORM/migration, locks.

## 2. G3D1 LearningEvent Shadow
- Seam: `prerequisite_service.create_jump_record` after session.commit (commit-then-trigger).
- `learning_shadow.py`: flag-gated LEARNING_EVENT_MODE (root independent); maps V1 jump -> P1-07 LearningEvent (PREREQ_JUMP_STARTED); idempotent (event_type+student+course+sequence -> event_id); append-only store; missing student/course -> fail-closed. No LLM.

## 3. G3D2 Memory Candidate Shadow (NOT injected into QA)
- Seam: `qa_service.ask_question_with_rag` after retrieval, before LLM.
- HARD CONSTRAINT: candidate memory NOT injected into QA prompt (`would_inject=False` always). V1 answer unchanged.
- `memory_candidate_shadow.py`: flag-gated STUDENT_MEMORY_MODE=shadow (requires LEARNING_EVENT_MODE v2_shadow); builds candidate MemoryEntry from V1 rag_sources (evidence_refs + generation_reason, NOT chat summary as truth); records would-inject context for offline comparison. RISK-05: missing student/course -> fail-closed. Question stored as sha256.

## 4. G3D3 Safety Dry Run (never blocks V1)
- Seam: `qa_service.ask_question_with_rag` (question + course_id).
- HARD CONSTRAINT: `v1_blocked=False` always. Records would_allow/would_refuse + reason_code only.
- `safety_dryrun_shadow.py`: flag-gated SAFETY_GOVERNANCE_MODE=shadow (root independent); runs P1-08 SafetyEvaluator with platform-default PolicySet; does NOT block V1. Question stored as sha256 (audit minimization).

## 5. Tests (27)
- G3D1: 10 (flag-gate, idempotency, scope, isolation, append-only)
- G3D2: 10 (flag-gate, NOT-injected, no-chat-summary, scope, isolation, sha256)
- G3D3: 7 (flag-gate, never-blocks, records-decision, isolation, sha256)

## 6. Exit Gate
| Gate | Result |
| --- | --- |
| G3D tests | 27 passed |
| Full regression | **883 passed** (27 G3A + 58 shadow + 682 product1 + 116 existing), 0 failed |
| V1 chat/document/progress/prerequisite UNCHANGED | confirmed |
| Default all-disabled no-op | confirmed (all 3 flags default disabled/v1_only) |
| `git diff --check` | clean |

## 7. G3D Stop Point
G3D1+D2+D3 complete. **NOT proceeding to G3E** (awaits human go).
