# P1-09 G3A Delivery Report: Feature Flag Infrastructure

> Agent: P1-09 (executed by P1-00 as P1-09 dual-hat; no separate P1-09 subagent spawned due to G3A being the first shared-file gate and repeated subagent isolation failures)
> Date: 2026-07-14
> Baseline: `920459e` (G3A formal baseline; G2.1 freeze `d4894da` + ADR Accepted-G3A + P1-10 G2.1 verification)
> Branch: `agent/p1-09-integration` (worktree `ai-course-p1-09`)
> ADR: ADR-0006 (Accepted-G3A-only)

## 1. Scope (per authorization)

G3A modified ONLY:
- `backend/app/core/config.py` (modified: 7 flag fields + `@model_validator`)
- `backend/app/core/feature_flags.py` (new: flag logic, conflict rules, fail-closed helper)
- `backend/tests/feature_flags/` (new: local conftest + test_feature_flags.py)
- This delivery report

NOT modified (verified): main.py, router files, API endpoints, services (document_service/qa_service/progress/prerequisite), ORM/models, migrations/db_migrator, frontend (router/request/dashboards/player), public test infra (conftest.py/fakes.py), dependency/lock files. `backend/scripts/m7_preflight.ps1` UNCHANGED.

## 2. Implementation

### 2.1 Feature flags (`feature_flags.py`)

7 flags per ADR-0006 §3, with G3-legal values ONLY:

| Flag | Kind | Legal | Default | Upstream |
| --- | --- | --- | --- | --- |
| `DOCUMENT_PIPELINE_VERSION` | pipeline | v1_only/v2_shadow | v1_only | (root) |
| `KNOWLEDGE_GRAPH_PIPELINE_VERSION` | pipeline | v1_only/v2_shadow | v1_only | DOCUMENT_KG_RUNTIME_MODE |
| `DOCUMENT_KG_RUNTIME_MODE` | pipeline | v1_only/v2_shadow | v1_only | DOCUMENT_PIPELINE_VERSION |
| `EVIDENCE_CITATION_MODE` | pipeline | v1_only/v2_shadow | v1_only | DOCUMENT_KG_RUNTIME_MODE |
| `LEARNING_EVENT_MODE` | pipeline | v1_only/v2_shadow | v1_only | (root) |
| `STUDENT_MEMORY_MODE` | toggle | disabled/shadow | disabled | LEARNING_EVENT_MODE |
| `SAFETY_GOVERNANCE_MODE` | toggle | disabled/shadow | disabled | (root) |

`v2_preferred_with_v1_fallback` and `v2_only` are G6-reserved and NOT legal in G3.

### 2.2 Two-layer error handling

- **Startup fail-fast (config invalid)**: `Settings._validate_feature_flags` (`@model_validator(mode="after")`) raises `ValueError` -> pydantic `ValidationError` -> `Settings()` construction raises -> application refuses to start. Typos (`v2_shdaow`), G6 values, and cross-kind values (e.g. `v2_shadow` on a toggle flag) all rejected. NO silent fallback.
- **Business fail-closed (shadow runtime error)**: `shadow_runtime_fail_closed(flag, configured, reason)` returns an `EffectiveMode` downgraded to V1/disabled with `fallback_reason="shadow_runtime_error:<flag>:<reason>"`. Used when config is legal but V2 execution fails at runtime.

### 2.3 Aggregate vs module conflict rule

Dependency graph (DAG, verified acyclic by test):
```
DOCUMENT_PIPELINE_VERSION (root) -> DOCUMENT_KG_RUNTIME_MODE -> {EVIDENCE_CITATION_MODE, KNOWLEDGE_GRAPH_PIPELINE_VERSION}
LEARNING_EVENT_MODE (root) -> STUDENT_MEMORY_MODE
SAFETY_GOVERNANCE_MODE (root)
```

`resolve_effective_modes(configured)`: a module flag configured v2_shadow/shadow is downgraded to its V1/disabled baseline if its upstream is not effectively V2/shadow, with `fallback_reason="upstream_<upstream>_not_v2:<effective>"`. Memory/learning/safety are independent of the document aggregate (per ADR-0006 §3, not bundled with DOCUMENT_PIPELINE_VERSION).

## 3. Tests (`test_feature_flags.py`, 27 tests)

- Startup fail-fast: defaults clean; typo rejected; invalid rejected; G6-reserved rejected; cross-kind rejected; legal accepted (6 tests)
- Legal values / structure: pipeline/toggle modes, 7 flags, each has legal values, kind mapping (5 tests)
- Conflict rule: all-v2 no conflict; aggregate v1 downgrades module; chain cascade; module-v1 not downgraded (4 tests)
- Independent flags: learning/safety independent of doc aggregate; memory requires learning events; memory shadow when learning v2 (3 tests)
- Business fail-closed: runtime failure downgrades with reason; toggle flag; distinct from config error (3 tests)
- Helpers: all_default, is_configured_v2, upstream DAG acyclic, EffectiveMode frozen (5 tests)

Result: **27 passed**.

## 4. Exit Gate Verification

| Gate | Command | Result |
| --- | --- | --- |
| G3A tests | `pytest backend/tests/feature_flags/` | 27 passed |
| 682 Product 1 | `pytest <8 product1 dirs>` | 682 passed |
| 116 existing regression | `pytest <13 regression files>` | 116 passed, 0 failed |
| M7 functional smoke | `pytest test_m7_demo_flow.py` | 1 passed |
| Settings startup (defaults) | `from app.core.config import settings` | OK, all flags V1/disabled |
| Startup fail-fast (invalid) | `Settings(DOCUMENT_PIPELINE_VERSION='v2_shdaow')` | ValidationError (app refuses start) |
| Scope compliance | `git status` | only config.py/feature_flags.py/tests; no forbidden files |
| `git diff --check` | | clean (exit 0) |

**M7 preflight note**: `backend/scripts/m7_preflight.ps1` reports 2 environmental FAILs (backend `.venv` absent, frontend `npm build` - vite absent) because the worktree lacks the gitignored `.venv`/`node_modules`. These are NOT G3A regressions (the script runs in the main repo where those exist); `m7_preflight.ps1` itself is UNCHANGED. The actual M7 functional smoke (`test_m7_demo_flow.py`) passes.

## 5. Conflicts / Limitations

1. `feature_flags.py` defines flag logic but does NOT yet wire into any business path (G3B+). No V2 shadow runs yet; all flags default V1/disabled, so system behavior == M7 baseline.
2. `resolve_effective_modes` operates on plain dict input; G3B+ will pass the configured `Settings` values. The contract is stable.
3. Business fail-closed helper returns an `EffectiveMode` but does not itself log; G3B+ callers record `fallback_reason` into shadow telemetry.

## 6. Git Checks

```
git diff --check: exit 0 (no whitespace errors)
git diff --stat:
 backend/app/core/config.py | 38 +++++++++++++++++++++++++++
git status --short:
 M backend/app/core/config.py
?? backend/app/core/feature_flags.py
?? backend/tests/feature_flags/
```

## 7. External Services / Dependencies

None contacted. No dependencies installed. No ORM/migration. No real external services.

## 8. G3A Stop Point

G3A complete. **Not proceeding to G3B** (per authorization: G3A complete -> stop; G3B awaits human go). Committing G3A to `agent/p1-09-integration` and requesting P1-10 independent verification + human G3B go-ahead.
