# P1-09 G5A Delivery Report: Quality-Gate Framework (Canary, no real services)

> Agent: P1-09 (executed directly, dual-hat; main repo clean)
> Date: 2026-07-15
> Baseline: `5669b0e` (G4 merged)
> ADR: ADR-0006 §8A (G5A, human-authorized after scope decision)

## 1. Scope decision
G5 Canary's ADR intent ("real V2 data flow + quality comparison": real Docling/PaddleOCR/vector/LLM vs V1, gold-standard QA semantic correctness) is NOT executable under CLAUDE.md: G2 built only Protocol interfaces + Fakes (real providers need dep install/model download/real services), and V1 itself is offline/local (TreeRAG + statistical keyword, no vector model). Real canary conflicts with CLAUDE.md ("no dep install", "no real paid services"). Per user decision, G5 split into G5A (quality-gate framework, no real services) + G5B (real-provider canary, deferred until constraint relaxation).

## 2. Scope
Modified (P1-09-owned):
- `main.py` (+1 import +1 include_router for canary_v2)
- `.gitignore` (+p1_shadow_* trace store rules - shadow/canary runtime artifacts)
- `docs/refactor/product1/adr/0006-...md` (+§8A G5A/G5B)
- This report

New (P1-09-owned):
- `platform/canary/__init__.py`, `platform/canary/quality_gate.py`, `platform/canary/canary_runner.py`
- `api/v1/endpoints/canary_v2.py`
- `tests/canary/test_quality_gate.py`, `test_canary_runner.py`, `test_canary_v2_endpoint.py`

NOT modified (verified): config.py, feature_flags.py, qa_service.py, document_service.py, document.py, document_v2.py, evidence_v2.py, chat.py, conftest.py, fakes.py, the 6 existing shadow modules (canary imports+calls them, does not modify), frontend, utils/request.js, ORM/migration.

## 3. G5A deliverables

### 3.1 quality_gate.py
Runtime aggregation of G3B..G3E1 shadow trace JSONs into structured quality metrics + PASS/FAIL verdict (upgrade of G3E2 static diff report -> runtime-computed).
- Per-path metrics: llm_calls_total (target 0); evidence scope_isolation_rate (target 1.0) + citation_abstain_rate (informational); memory would_inject_any (target False); safety v1_blocked_any (target False); graph accepted_traces_evidence_all (target True) + v1_tables_touched_any (target False).
- Aggregate invariants: all_llm_calls_zero, memory_never_injects, safety_never_blocks, v1_tables_never_touched, accepted_traces_evidence, evidence_scope_isolated, all_paths_passed.
- Verdict: PASS iff all invariants True. Empty/missing roots -> vacuous PASS (0 traces, no failures).
- write_report: atomic JSON.

### 3.2 canary_runner.py
End-to-end canary under all-flags-on (patches each shadow module's flag-read fn, NOT real settings) with fake/fixture V1 inputs.
- run_canary(CanaryConfig) -> CanaryRunResult: for each course in allowlist, calls 6 triggers in doc-processing order (doc->evidence->learning->memory->safety->graph) with fake inputs; collects trace paths; compute_quality.
- Scope control: only `course_ids` allowlist courses run (blast-radius limiter); empty allowlist -> no courses, overall_passed=False.
- NO real services: no process_document, no llm_client.chat (tested), no real Docling/OCR/vector. `real_services_called=False` always.

### 3.3 canary_v2.py endpoint
Admin-only (Depends(admin_only), ADR §9) `/api/v1/canary-v2/run` (POST, requires course_ids - scope control) + `/report` (GET). 503 SHADOW_FEATURE_DISABLED when EVIDENCE_CITATION_MODE not v2_shadow. No raw file paths. Registered in main.py under `/api/v1/canary-v2`.

## 4. Tests (24)
- test_quality_gate.py (10): healthy PASS; abstain informational; empty/missing vacuous PASS; llm>0/inject/block/v1_tables/accepted_not_traced/scope_leak FAIL; write_report round-trip.
- test_canary_runner.py (7): all-6-paths triggered + quality PASS; hard constraints hold; real_services_called=False; scope control (skipped/allowlist); llm_client never invoked.
- test_canary_v2_endpoint.py (7): 503 flag-off; admin_only (student 403/no-token 401); run requires course_ids (400); run verdict+no-real-services; report verdict+invariants; desensitization.

## 5. Exit Gate (ADR §8A G5A)
| Gate | Result |
| --- | --- |
| Quality-gate aggregation correct | confirmed (PASS healthy, FAIL on any hard-constraint violation) |
| End-to-end canary all-flags-on | confirmed (6 paths triggered, traces written, quality PASS) |
| Scope control (allowlist) | confirmed (empty->no run; only allowlisted run) |
| No real services | confirmed (llm_client.chat never called; real_services_called=False) |
| admin_only + 503 (canary_v2) | confirmed |
| V1/shared/shadow modules UNCHANGED | confirmed |
| `git diff --check` | clean |

## 6. Regression
- G5A tests: 24 passed.
- Worktree full regression (with G5A): 1020 passed, 28 failed, 12 errors.
- Baseline `5669b0e` (G4): 996 passed, 28 failed, 12 errors.
- **Delta: +24 passed, 0 new failures, 0 new errors.** Pre-existing 28 failures + 12 errors unchanged (infra-dependent integration tests + product1/conftest.py pytest_plugins collection issue).
- canary + shadow + feature_flags + evidence combined: 183 passed.

## 7. G5A Stop Point
G5A complete. **NOT proceeding to G5B (real-provider canary - needs CLAUDE.md constraint relaxation) or G6 (preferred - needs G5B).** Awaits human go.
