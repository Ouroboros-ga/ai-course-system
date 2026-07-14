# P1-09 G3B Delivery Report: Document-Parse Shadow

> Agent: P1-09 (executed directly by P1-00 as P1-09 dual-hat; no subagent - G3B touches shared upload-chain files, subagents leaked 3x before)
> Date: 2026-07-14
> Baseline: `a77947d` (G3A merged); P1-09 worktree ff-forwarded to it
> Branch: `agent/p1-09-integration`
> ADR: ADR-0006 §G3B (human-authorized)

## 1. Scope (per ADR-0006 §G3B + authorization)

G3B modified (all P1-09-owned):
- `backend/app/services/document_service.py` (seam: +22 lines, 1 call in process_document return path)
- `backend/app/main.py` (+1 import, +1 include_router, independent prefix)
- `backend/app/api/v1/endpoints/document_v2.py` (new: independent shadow query router)
- `backend/app/platform/shadow/` (new: doc_shadow.py + __init__.py)
- `backend/tests/shadow/` (new: conftest + test_doc_shadow.py, 16 tests)
- This report

NOT modified (verified): `document.py` (V1 routes UNCHANGED), ORM/models, migrations, frontend, conftest.py/fakes.py, dependency/lock files. V1 parse/structure/script/RAG logic untouched - only a post-success seam call added.

## 2. Design

### 2.1 Commit-then-trigger seam
In `document_service.process_document`, AFTER V1 parsing/structure/script/rag/mindmap all succeed (line 1953 logger "文档处理完成"), BEFORE return: one call to `trigger_doc_shadow(...)`. Per ADR §G3B: V1 file stable on disk + V1 main-flow success determined before shadow. Shadow reads only `file_path` (on disk) + `parse_result` (already produced); does NOT read V1 DB or V1 tables.

Double safety: `trigger_doc_shadow` catches all errors internally (business fail-closed); the seam wraps it in a second try/except so V1 can NEVER be affected by shadow.

### 2.2 Shadow pipeline (`platform/shadow/doc_shadow.py`)
1. **Flag check (conflict-aware)**: `resolve_effective_modes` -> if DOCUMENT_PIPELINE_VERSION not effectively `v2_shadow`, no-op with `fallback_reason`. Default v1_only = no-op.
2. **Source checksum** -> idempotency key (sha256 + config version).
3. **Idempotency**: artifact exists -> skip (not error).
4. **Disk quota** (500MB) -> fail-closed if exceeded.
5. **Single-in-flight per course** (`_InflightTracker`, MAX_INFLIGHT_PER_COURSE=1) -> queue-full skips with fallback_reason (never blocks V1).
6. **Fake/offline V2 parse** (`_build_shadow_document_ir`): maps V1 parse_result into DocumentIR-shaped shadow artifact. NO real Docling/PaddleOCR (ADR: fake/offline; real quality = G5 canary).
7. **Timeout** (60s) + abandoned-on-interrupt.
8. **No M7 GPU/port contention** (FORBIDDEN_M7_PORTS = {7860, 8383}; shadow uses neither).

### 2.3 Artifact isolation
`ShadowArtifactStore` writes to `./p1_shadow_artifacts/` (or `P1_SHADOW_ARTIFACT_ROOT`), isolated from V1 Course/ScriptNode/KnowledgePageMap/V1 RAG registry/V1 task state. Path-traversal safe (hex-only keys), atomic (tmp+rename), checksummed, idempotent. Shadow artifact stores source_sha256 (NOT V1 course_id).

### 2.4 Independent router (`document_v2.py`)
- Prefix `/api/v1/document-v2`, tag `Product1-V2-shadow`, registered in main.py (1 line).
- `/artifact?source_sha256=...`: query shadow artifact summary (no raw file paths, no V1 identities).
- `/status`: effective mode + disk usage + artifact count.
- **503 + `SHADOW_FEATURE_DISABLED`** when flag not v2_shadow (NOT empty 200 - avoids caller mistaking absence for success).
- Does NOT touch V1 document.py routes.

## 3. Tests (16, all pass)

- Flag-gated: disabled no-trigger; v2_shadow triggers+writes; conflict downgrade no-trigger (3)
- Idempotency: same source skips; different source different artifact (2)
- Resource rules: queue-full skips; disk-quota fail-closed; runtime-error fail-closed (3)
- V1 isolation: shadow never raises into V1; artifact isolated from V1 (no course_id stored) (2)
- ShadowArtifactStore: path-traversal safe; atomic write; deterministic checksummed key (3)
- Shadow IR builder: DocumentIR shape; handles empty pages (2)
- Result frozen (1)

## 4. Exit Gate Verification

| Gate | Result |
| --- | --- |
| G3B shadow tests | 16 passed |
| G3A feature_flags tests | 27 passed (unchanged) |
| 682 Product 1 | passed |
| 116 existing regression | passed |
| M7 functional smoke (test_m7_demo_flow) | passed |
| Full combined | **825 passed, 0 failed** |
| Default v1_only no-op | confirmed: seam writes NO artifact, system == M7 baseline |
| Scope: document.py UNCHANGED | confirmed |
| document_service.py: seam only (+22 lines) | confirmed |
| main.py: +1 import +1 include_router | confirmed |
| `git diff --check` | clean (exit 0) |

## 5. Conflict/Fail-closed Semantics

- Flag v1_only (default) -> seam no-op, `fallback_reason="flag_not_v2_shadow"`, zero artifact, zero V1 impact.
- Flag v2_shadow + runtime error -> `fallback_reason="shadow_runtime_error:..."`, V1 continues, no artifact.
- Idempotent skip / queue-full / disk-quota -> `fallback_reason` set, `triggered=False`, V1 continues.
- Flag v2_shadow + success -> artifact written to isolated store; V1 response unchanged (shadow result not returned to upload caller).

## 6. Limitations / G3C prerequisites

1. Shadow V2 parse is fake/offline (V1 parse_result mapped to DocumentIR shape). Real P1-02 provider quality comparison is G5 canary. The G3B diff is a **contract/integration diff** (chain runs, artifact traceable, diff format generatable), NOT a quality comparison.
2. `_InflightTracker` is in-process (sufficient for single-process shadow; multi-worker shared store is G4+).
3. Shadow artifact lookup by source_sha256 uses computed key (sha256+config); a reverse index is G4+.
4. Shadow trigger is `sync=True` in the seam (small files); production `sync=False` (fire-and-forget) path exists but G3B tests use sync for determinism.
5. G3B does NOT wire Evidence/Citation (G3C), learning/memory/safety (G3D), graph (G3E).

## 7. Git Checks
```
git diff --check: exit 0
git status --short:
 M backend/app/main.py
 M backend/app/services/document_service.py
?? backend/app/api/v1/endpoints/document_v2.py
?? backend/app/platform/shadow/
?? backend/tests/shadow/
```

## 8. External Services / Dependencies
None. No real Docling/PaddleOCR/LLM. No dependencies installed. No ORM/migration. Shadow store is local JSON files.

## 9. G3B Stop Point
G3B complete. **NOT proceeding to G3C** (awaits human go). Committing to `agent/p1-09-integration` and requesting P1-10 independent verification + human G3C go-ahead.
