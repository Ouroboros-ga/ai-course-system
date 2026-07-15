# P1-10 G4 Independent Verification Report

> Verifier: P1-10 (P1-00 dual-hat)
> Date: 2026-07-15
> Subject: P1-09 G4 commit `226e042` (baseline `0a2f900`) - G4A DTO freeze + G4B Viewer mount
> Verdict: **PASS**. Approved to merge (already ff-merged).
> ADR: ADR-0006 §8 (G4A/G4B) + §9 (V2 router constraints)

## 1. Scope compliance
- Files changed `0a2f900..226e042`: 8 (evidence_v2.py new, main.py +7, test_internal_evidence_api.py new, internal-evidence-api.md new, registry.md 1 row, api/evidence.js 1 line, router/index.js +10, EvidenceViewerPage.vue new). All P1-09-owned.
- V1 shared + forbidden files **UNCHANGED** (12/12 verified): `config.py`, `feature_flags.py`, `qa_service.py`, `document_service.py`, `document.py`, `document_v2.py`, `chat.py`, `database.py`, `conftest.py`, `fakes.py`, `utils/request.js`, `SplitVideoPlayer.vue`.
- Main workspace clean throughout (direct execution, no isolation failure - pattern holds G3A..G4).

## 2. G4A - Evidence API DTO freeze (internal-evidence-api/1.0)
- **DTO frozen**: 5 endpoints under `/api/v1/evidence-v2`; Pydantic response models serialize snake_case, mirror P1-03 frozen contracts (evidence/1.0 + citation/1.0); match P1-04 frontend `contracts.js` parsers. Contract doc `internal-evidence-api.md` + registry row updated `draft -> frozen-major / internal-evidence-api/1.0 / G4 ✅`.
- **Admin-only (ADR §9)**: every endpoint `Depends(admin_only)` -> admin proceeds, student 403, no-token 401 (tested). Blocks students -> no cross-course Evidence read.
- **503 when flag off**: `EVIDENCE_CITATION_MODE` not v2_shadow -> 503 `SHADOW_FEATURE_DISABLED` (tested, incl. conflict downgrade when DOCUMENT_KG_RUNTIME_MODE=v1_only). NOT empty 200.
- **Desensitization**: no raw file paths / provider config in any response (tested).
- **G4 data**: empty/abstain responses (real data = G5/G6; G3C traces per-question not per-document). validate endpoint abstains `no_evidence` (no fake citation keys).
- **No ORM/migration**: DTO = JSON serialization of frozen P1-03 contracts; no new tables.
- Contract tests: **15 passed** (DTO shape, 503, admin_only, G4 responses, desensitization).

## 3. G4B - Evidence Viewer formal mount
- **Independent route**: `router/index.js` +1 admin-only route `/evidence-viewer/:documentId?` mounting `EvidenceViewerPage` (thin wrapper). Does NOT touch SplitVideoPlayer/TeacherDashboard/StudentDashboard/other routes.
- **API wiring**: `EvidenceViewerPage.vue` reads `:documentId`, fetches via `api/evidence.js` (Promise.allSettled, fail-closed), passes parsed data to `EvidenceViewerWithPanel`. RISK-02 coordinate fail-closed in `contracts.js` (parseBoundingBox/parsePolygon -> null on invalid).
- **api/evidence.js**: API_BASE `/api/v2/evidence` (G2 placeholder) -> `/api/v1/evidence-v2` (P1-04 deferred to P1-09). `utils/request.js` UNCHANGED (independent raw `fetch` per ADR G4B).
- **Frontend build**: `npm run build` EXIT=0 (success; only pre-existing Vite chunk-size warning, not a G4 regression).
- **P1-04 node tests**: 127 passed (contracts 65 + coordinateTransform 62), 0 failed - frontend contracts unbroken.

## 4. Backend regression
- G4A contract tests: 15 passed.
- Full backend regression: **996 passed**, 28 failed, 12 errors.
- Baseline `0a2f900` (G3E): 981 passed, 28 failed, 12 errors.
- **Delta: +15 passed, 0 new failures, 0 new errors.** The 28 failures + 12 errors are pre-existing (infrastructure-dependent integration tests requiring DB/external services + the pre-existing `product1/conftest.py` `pytest_plugins` collection issue from `abf4213`) - unchanged by G4.
- shadow + feature_flags + evidence combined: 159 passed (104 prior + 15 G4A + 40 evidence).

## 5. M7 preflight
- Offline regression (M4A/M4B/R1/R1D/R2/M7): PASS. Git whitespace + working tree clean: PASS.
- Frontend build: `npm run build` EXIT=0 directly. Preflight build-check reports false [FAIL] (pre-existing PS 5.1 + `ErrorActionPreference="Stop"` catching Vite chunk-size warning `markdown` 1271kB>1000kB on stderr) - NOT a G4 regression; `-SkipBuild` run PASSES.

## 6. Verdict
**PASS**. G4 (G4A DTO freeze + G4B Viewer mount) complete. Last unfrozen contract `internal-evidence-api/1.0` frozen; first frontend shared-file change (`router/index.js`) done within ADR G4B scope. Merged to integration `226e042`. **G5 NOT authorized** (canary awaits human go).
