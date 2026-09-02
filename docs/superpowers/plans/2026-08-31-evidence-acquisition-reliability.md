# Evidence Acquisition Reliability Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use test-driven-development to execute this plan task-by-task and verification-before-completion before reporting success.

**Goal:** Prevent non-educational fragments from entering evidence, retrieval, and graph-candidate projections, and prevent stale or filtered spans from being promoted to formal course evidence.

**Architecture:** Keep every parsed block in immutable Canonical DocumentIR for auditability, but route every query-facing consumer through one deterministic, reason-coded eligibility classifier. Apply the same classifier at projection, graph construction, teacher listing, and final confirmation; use the active retrieval snapshot as the default review boundary while preserving explicit run/history access.

**Tech Stack:** Python 3.11, FastAPI, SQLModel, pytest, Canonical DocumentIR.

---

### Task 1: Specify the educational-fragment gate

**Files:**
- Modify: `backend/tests/document_intelligence/canonical/test_block_noise.py`
- Modify: `backend/app/platform/document_intelligence/canonical/block_noise.py`

- [x] Add failing tests for Roman numeral page markers, private-use glyph fragments, decorative marketing lines, and isolated formula residue.
- [x] Add preservation tests for short Chinese teaching titles, code, and real formulas with at least two meaningful operands.
- [x] Run the focused classifier tests and record the expected RED result.
- [x] Implement a deterministic reason-coded classification API while keeping `detect_noise_block_ids` and `filter_noise_blocks` compatible.
- [x] Re-run the focused tests and record GREEN.

### Task 2: Enforce one gate across projections and graph candidates

**Files:**
- Modify: `backend/tests/test_p0_4_document_parse_pipeline.py`
- Modify: `backend/app/platform/document_intelligence/canonical/projector.py`
- Modify: `backend/app/services/document_parse_pipeline.py`

- [x] Add failing projection tests proving fragment blocks remain auditable as `DocumentBlock` but never produce anchor/span/chunk rows, and that quality records reason counts.
- [x] Add a failing graph-candidate test proving filtered titles and sources cannot enter node or relation candidates.
- [x] Reuse the shared classifier in the projector and graph builder.
- [x] Sanitize legacy graph-batch teacher projections without rewriting their stored audit payloads.
- [x] Re-run the focused projection and graph tests.

### Task 3: Harden review and confirmation boundaries

**Files:**
- Modify: `backend/tests/test_document_parse.py`
- Modify: `backend/app/services/document_parse_service.py`
- Modify: `backend/app/api/v1/endpoints/document_parse.py`

- [x] Add failing tests proving stale spans and non-educational fragments cannot be confirmed.
- [x] Add a failing list test proving the default review view uses the active IR and removes deterministic noise, while explicit `run_id` access remains available for reparse review/history.
- [x] Restrict confirmation to candidate spans whose backing block passes the shared gate.
- [x] Add `include_history` to the teacher list endpoint; default to the active IR when available and exclude filtered fragments.
- [x] Re-run the focused service/API tests.

### Task 4: Synchronize current documentation

**Files:**
- Modify: `docs/phase1/统一课程建设与解析基线.md`
- Modify: `docs/phase1/2026-08-31_证据生成链路审计与改进方案.md`
- Modify: `docs/phase1/功能现状审计表.md`

- [x] Document the shared reason-coded gate, active-IR default list behavior, explicit history access, and confirmation defense-in-depth.
- [x] Keep reparse adoption explicitly teacher-controlled; do not describe un-applied candidate IR as live evidence.

### Task 5: Verify the evidence chain

**Files:**
- Test: `backend/tests/document_intelligence/canonical/test_block_noise.py`
- Test: `backend/tests/test_document_parse.py`
- Test: `backend/tests/test_p0_4_document_parse_pipeline.py`
- Test: `backend/tests/test_step3_combo_parse.py`

- [x] Run the focused classifier, projector, service, pipeline, and reparse-adoption tests with the repository virtual environment.
- [x] Run a broader document-intelligence regression if the focused suite is green.
- [x] Inspect `git diff --check` and scoped `git status`; report verification limits honestly.

## Verification Evidence

- RED: classifier suite failed because `classify_noise_blocks` did not exist.
- RED: pipeline suite failed because reason counts were absent; service/API suite showed stale and fragment confirmations returned 200 and default listing mixed IR versions.
- GREEN: `test_document_parse.py` — 36 passed.
- GREEN: `test_p0_4_document_parse_pipeline.py` — 4 passed.
- GREEN: `backend/tests/document_intelligence` — 242 passed, 1 skipped.
- GREEN: `test_step3_combo_parse.py` — 16 passed.
- GREEN: scoped Ruff fatal-error rules and `git diff --check` passed; repository-wide Ruff remains noisy with pre-existing style findings and was not used as a completion claim.
