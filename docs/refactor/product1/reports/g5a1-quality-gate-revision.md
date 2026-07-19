# P1-09 G5A.1 Delivery Report: Quality-Gate Semantic Revision (G5A FREEZE)

> Agent: P1-09 (executed directly, dual-hat; main repo clean)
> Date: 2026-07-15
> Baseline: `4b2bafd` (G5A)
> ADR: ADR-0006 §8A G5A.1 (human-directed revision before G5A freeze)

## 1. Why
G5A (`4b2bafd`) had 3 semantic defects the human review caught:
1. Empty/zero-sample/zero-denominator -> vacuous PASS ("no data" reads as "passed"). Misleading.
2. Single PASS/FAIL verdict conflates execution safety, contract integrity, and model quality. Model quality cannot be evaluated in G5A (no real model) but was not surfaced.
3. `real_services_called = False` hardcoded, not auditable.

## 2. Scope (P1-09-owned, 6 code files + 5 G5B-0 docs)
Modified:
- `platform/canary/quality_gate.py` (rewritten): MetricStatus enum {pass/fail/not_evaluated/insufficient_data}; QualityMetric.dimension; DimensionVerdict (3 dimensions); empty/zero-denominator/missing -> INSUFFICIENT_DATA; model_quality dimension always NOT_EVALUATED in G5A; 4-state verdict.
- `platform/canary/canary_runner.py`: ProviderCallRecord + derive_real_services_called(log); CanaryRunResult.provider_call_log; real_services_called log-derived.
- `api/v1/endpoints/canary_v2.py`: response +dimensions + model_quality_status.
- 3 test files rewritten.

New (G5B-0, docs only - no production code):
- `docs/refactor/product1/canary/`: gold-standard-dataset-spec.md, metric-thresholds.md, provider-compatibility-matrix.md, isolation-environment-plan.md, g5b-rollout-order.md.

NOT modified: config.py, feature_flags.py, qa_service.py, document_service.py, document.py, evidence_v2.py, conftest.py, fakes.py, the 6 shadow modules, main.py (canary_v2 registration unchanged), frontend, ORM/migration.

## 3. G5A.1 semantics
- THREE dimensions: execution_safety (V1 isolation: llm/would_inject/v1_blocked/v1_tables_touched), contract_integrity (citation/evidence invariants: accepted_traces_evidence/scope_isolation/citation_abstain), model_quality (real model - NOT_EVALUATED in G5A, always surfaced).
- Status: PASS / FAIL / NOT_EVALUATED / INSUFFICIENT_DATA. Empty/zero-sample/zero-denominator/missing -> INSUFFICIENT_DATA (NOT vacuous PASS). Even llm_calls_total with 0 traces -> INSUFFICIENT_DATA (no sample to prove "no LLM").
- Per-dimension verdict + overall 4-state verdict.
- model_quality dimension ALWAYS present with NOT_EVALUATED (explicit, per directive).
- real_services_called = derive_real_services_called(provider_call_log); empty log (G5A, no real providers) -> False. Derivation proven by test (log with invoked_real=True -> True).

## 4. Tests (31)
- test_quality_gate (14): healthy PASS; empty/missing NOT_PASS + contract INSUFFICIENT_DATA; zero-denominator INSUFFICIENT_DATA; each hard-constraint FAIL; 3 dimensions present; model_quality always NOT_EVALUATED; write_report.
- test_canary_runner (9): all-6-paths triggered + verdict pass; hard constraints; model_quality not_evaluated; real_services log-derived empty->False; log-with-real->True (derivation); scope control.
- test_canary_v2_endpoint (8): 503; admin_only; run requires course_ids; verdict pass + dimensions + model_quality not_evaluated; report; desensitization.

## 5. Regression
- G5A.1 tests: 31 passed (was 24 in G5A; +7 new for G5A.1 semantics).
- Worktree full regression: 1027 passed, 28 failed, 12 errors.
- Baseline 4b2bafd (G5A): 1020 passed, 28 failed, 12 errors.
- Delta: +7 passed, 0 new failures, 0 new errors. Pre-existing 28 failures + 12 errors unchanged.

## 6. G5B-0 (preparation, no execution)
5 spec docs under docs/refactor/product1/canary/: gold-standard dataset spec, metric thresholds (proposed, uncalibrated), provider compatibility matrix, isolation environment plan (restates CLAUDE.md constraints), G5B rollout order (Docling->PaddleOCR->Embedding->Reranker->LLM, per-item human gate). All PLAN/SPEC only - no deps, no services, no production code.

## 7. G5A Freeze
G5A + G5A.1 complete. P1-10 verification PASS (separate report). **G5A FROZEN.** Not proceeding to G5B-N (N>=1) - needs CLAUDE.md constraint relaxation + per-item human gate per fixed order.
