# P1-10 G5A Independent Verification Report

> Verifier: P1-10 (P1-00 dual-hat)
> Date: 2026-07-15
> Subject: P1-09 G5A commit (baseline `5669b0e`) - quality-gate framework, no real services
> Verdict: **PASS**. Approved to merge.
> ADR: ADR-0006 §8A (G5A)

## 1. Scope compliance
- Files changed `5669b0e..(G5A)`: canary/ (new: __init__.py, quality_gate.py, canary_runner.py), canary_v2.py (new), test_quality_gate.py/test_canary_runner.py/test_canary_v2_endpoint.py (new), main.py +1/+1, .gitignore +p1_shadow_*, ADR +§8A, g5a report. All P1-09-owned.
- V1 shared + forbidden files **UNCHANGED**: config.py, feature_flags.py, qa_service.py, document_service.py, document.py, document_v2.py, evidence_v2.py, chat.py, conftest.py, fakes.py, utils/request.js. The 6 existing shadow modules UNCHANGED (canary imports+calls them, does not modify).
- Main workspace clean throughout (direct execution, no isolation failure - pattern holds G3A..G5A).

## 2. Scope decision verified
G5 real canary (real Docling/OCR/vector/LLM) confirmed NOT executable under CLAUDE.md (G2 = Protocol+Fakes only; V1 offline; real providers need deps+services). G5A (quality-gate framework, no real services) is the correct CLAUDE.md-compliant subset. G5B (real-provider canary) correctly deferred.

## 3. Hard constraints (ADR §8A G5A)
- **No real services**: canary_runner uses fake/fixture V1 inputs + direct trigger calls (no process_document, no llm_client). Tested: `llm_client.chat` never invoked; `real_services_called=False`.
- **Quality-gate correctness**: healthy traces -> PASS; each hard-constraint violation (llm>0, would_inject=True, v1_blocked=True, v1_tables_touched=True, accepted_traces_evidence=False, scope_leak) -> FAIL. Empty/missing -> vacuous PASS. citation_abstain is informational (not failure).
- **End-to-end canary**: all-flags-on (patches shadow flag-read fns, not real settings) -> 6 paths triggered, traces written, quality PASS.
- **Scope control**: course NOT in allowlist -> skipped; empty allowlist -> no run (overall_passed=False, no global canary).
- **canary_v2 endpoint**: admin_only (student 403, no-token 401); 503 SHADOW_FEATURE_DISABLED when flag off; /run requires course_ids (400); no raw paths.

## 4. Regression
- G5A tests: **24 passed** (quality_gate 10 + canary_runner 7 + canary_v2 endpoint 7).
- Worktree full regression: **1020 passed**, 28 failed, 12 errors.
- Baseline `5669b0e` (G4): 996 passed, 28 failed, 12 errors.
- **Delta: +24 passed, 0 new failures, 0 new errors.** Pre-existing 28 failures + 12 errors unchanged (infra-dependent integration tests + product1/conftest.py pytest_plugins collection issue).
- canary + shadow + feature_flags + evidence combined: 183 passed.

## 5. Artifacts
- p1_shadow_* trace stores are runtime artifacts (G3 shadow / G5A canary); now gitignored (.gitignore +rules). Cleaned from worktree before commit.

## 6. Verdict
**PASS**. G5A (quality-gate framework) complete - CLAUDE.md compliant (no real services). Merged to integration. **G5B (real-provider canary) NOT authorized** - needs CLAUDE.md constraint relaxation. **G6 (preferred) NOT authorized** - needs G5B.
