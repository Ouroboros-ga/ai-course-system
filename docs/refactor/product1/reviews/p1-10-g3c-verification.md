# P1-10 G3C Independent Verification Report

> Verifier: P1-10 (executed by P1-00 as P1-10 dual-hat)
> Date: 2026-07-14
> Subject: P1-09 G3C commit `e4335bc` (baseline `021c2c9`)
> Verdict: **PASS**. G3C meets its exit gate. Approved to merge.
> ADR: ADR-0006 §G3C

## 1. Scope compliance
- V1 `chat.py` + `document.py` + `database.py` + `conftest.py` + `fakes.py`: **UNCHANGED** (git diff empty 021c2c9..e4335bc).
- P1-09-owned files changed: qa_service.py (seam), new evidence_shadow.py, new test_evidence_shadow.py.
- Main workspace clean (direct execution, no subagent, no isolation failure).

## 2. No second LLM call (HARD CONSTRAINT)
- Seam is pre-LLM (after retrieve_rag_context, before llm_client.chat).
- `llm_calls == 0` verified in trace + result (tested: zero even on fail-closed).

## 3. V1 behavior unchanged
- V1 QA regression (m4b_main_flows + m7_demo_flow + retrieval + scope): passed.
- Shadow fail-closed; seam double try/except; V1 never affected.

## 4. Default == M7 baseline
Default v1_only: no trace written, no-op. V1 == M7.

## 5. Shadow semantics
- Flag-gated (conflict-aware); conflict downgrade no-trigger.
- RISK-03: missing course scope -> fail-closed, no global retrieval.
- No-evidence abstention (no fake citation key).
- Privacy: question stored as sha256, not raw.
- V1-vs-V2 contract/integration diff (not quality; no v2_answer field).

## 6. Regression
- G3C evidence tests: 15 passed
- Subset regression (shadow + product1 + m4b + m7 + retrieval): 791 passed, 0 failed
- Full combined (prior): 856 passed, 0 failed

## 7. Verdict
**PASS**. Recommend merge `e4335bc`. G3C complete. **G3D NOT authorized**.
