# P1-09 G3C Delivery Report: Evidence/Retrieval/Citation Shadow

> Agent: P1-09 (executed directly by P1-00 as P1-09 dual-hat; no subagent - continued direct-execution pattern, main repo stayed clean)
> Date: 2026-07-14
> Baseline: `021c2c9` (G3B merged); P1-09 worktree ff-forwarded
> Branch: `agent/p1-09-integration`
> ADR: ADR-0006 §G3C (human-authorized)

## 1. Scope

G3C modified (P1-09-owned):
- `backend/app/services/qa_service.py` (seam in ask_question_with_rag: after retrieve_rag_context, before V1 LLM call)
- `backend/app/platform/shadow/evidence_shadow.py` (new: V2 evidence/retrieval/citation shadow)
- `backend/tests/shadow/test_evidence_shadow.py` (new: 15 tests)
- This report

NOT modified (verified): `chat.py` (V1 QA routes UNCHANGED), `document.py`, ORM/models, migrations, frontend, conftest.py/fakes.py, dependency/lock files. V1 retrieve_rag_context / prompt builder / LLM call logic untouched - only a post-retrieve seam added.

## 2. Design

### 2.1 Seam location (no second LLM call)
In `qa_service.ask_question_with_rag`, AFTER `retrieve_rag_context` returns V1 `(rag_context, rag_sources)`, BEFORE the V1 `llm_client.chat` call: one call to `trigger_evidence_shadow(...)`. The seam is strictly pre-LLM, so V2 shadow never triggers a second generation. Double try/except: shadow catches all errors (business fail-closed); outer net ensures V1 never affected.

### 2.2 Evidence shadow (`platform/shadow/evidence_shadow.py`)
1. **Flag check (conflict-aware)**: EVIDENCE_CITATION_MODE must be effectively `v2_shadow` (requires DOCUMENT_KG_RUNTIME_MODE + DOCUMENT_PIPELINE_VERSION also v2_shadow, else conflict downgrade).
2. **RISK-03 course isolation**: if `course_id` is None -> fail-closed, NO V2 retrieval (would risk global leak). V2 retrieval is course-scoped (RetrievalScope.course).
3. **V2 candidate construction** (fake/offline): wraps V1 ragSources into P1-03 RetrievedChunk (with evidence fields) + EvidenceSpan + Citation (citation_key). No real vector model. No LLM.
4. **No-evidence abstention**: citations without block_id -> citation_key=None (no fake key); CitationValidationResult abstain=True when no evidence-backed citation.
5. **V1-vs-V2 diff trace**: compares V1 ragSources vs V2 candidates (retrieval/evidence layer), NOT two generated answers. `note: contract/integration diff (not quality comparison)`.
6. **HARD CONSTRAINT**: `llm_calls == 0` always (recorded in trace + result).
7. **Privacy**: trace stores `question_sha256`, NOT raw question text.
8. **Business fail-closed**: any shadow error -> V1 continues, fallback_reason set.

### 2.3 Trace isolation
`EvidenceTraceStore` writes to `./p1_shadow_evidence/`, isolated from V1 tables/RAG/QA responses. Path-traversal safe, atomic. Shadow results NOT returned to user (G6 preferred is when V2 feeds answer).

## 3. Tests (15, all pass)
- Flag-gated: disabled no-trigger; v2_shadow triggers+writes trace; conflict downgrade (3)
- No second LLM: llm_calls always 0; zero even on fail-closed (2)
- Course isolation: missing scope fail-closed; trace records scope isolated (2)
- No-evidence abstain: abstain when no content; no fake citation key; key present with evidence (3)
- Isolation: shadow never raises into V1; question sha256 not raw; trace isolated from V1 (3)
- Diff shape: contract/integration not quality; no v2_answer field (1)
- Result frozen (1)

## 4. Exit Gate
| Gate | Result |
| --- | --- |
| G3C evidence tests | 15 passed |
| Full regression | **856 passed** (27 G3A + 31 shadow + 682 product1 + 116 existing), 0 failed |
| Default v1_only no-op | confirmed: no trace written, V1 == M7 baseline |
| V1 chat.py / document.py UNCHANGED | confirmed |
| qa_service seam: pre-LLM, no second LLM | confirmed (llm_calls=0) |
| `git diff --check` | clean |

## 5. G3C Stop Point
G3C complete. **NOT proceeding to G3D** (awaits human go). Committing + P1-10 verification.

## 6. External Services / Dependencies
None. No LLM. No real vector model. No ORM/migration. Trace = local JSON.
