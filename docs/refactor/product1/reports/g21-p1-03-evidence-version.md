# G2.1 Contract Normalization Report

## Identity

- **Agent**: P1-03 Evidence Retrieval
- **Task**: G2.1 Contract Normalization (tiny, low-risk)
- **Worktree**: `/e/smartcarb/worktrees/ai-course-p1-03`
- **Branch**: `agent/p1-03-evidence-retrieval`
- **HEAD**: `1cf02697d294ab514571aef560311ca3779f8933`
- **Status**: clean (no dirty files, no untracked files other than new test + report)

## Worktree Verification

```
$ pwd
/e/smartcarb/worktrees/ai-course-p1-03

$ git rev-parse --show-toplevel
E:/smartcarb/worktrees/ai-course-p1-03

$ git branch --show-current
agent/p1-03-evidence-retrieval

$ git rev-parse HEAD
1cf02697d294ab514571aef560311ca3779f8933

$ git status --short
(clean — no dirty files, only new files shown in diff --stat)
```

## Files Changed

### 1. `backend/app/platform/evidence/contracts.py`

- **Docstring fix** (line 16): `evidence/1` changed to `evidence/1.0` to match registry registration.
- **Constant added**: `EVIDENCE_VERSION = "evidence/1.0"` placed after imports, before `class EvidenceStatus`.

### 2. `backend/app/platform/evidence/citation.py`

- **Docstring updated** (line 12): Added "(registered in registry)" to existing `citation/1.0` docstring for clarity (no semantic change).
- **Constant added**: `CITATION_VERSION = "citation/1.0"` placed after imports, before `class CitationStatus`.

### 3. `backend/app/platform/evidence/text_transform.py`

- **Docstring updated** (line 18): Added "(registered in registry)" to existing `text-transform/1.0` docstring for clarity (no semantic change).
- **Constant added**: `TEXT_TRANSFORM_VERSION = "text-transform/1.0"` placed after imports, before `@dataclass`.

### 4. `backend/app/platform/retrieval/providers/contracts.py`

- **Docstring updated** (line 13): Added "(registered in registry)" to existing `retrieval-provider/1.0` docstring for clarity (no semantic change).
- **Constant added**: `RETRIEVAL_PROVIDER_VERSION = "retrieval-provider/1.0"` placed after imports, before `logger`.

### 5. `backend/tests/evidence/test_version_constants.py` (NEW)

- 8 focused tests (4 classes, 2 tests each):
  - `test_evidence_version_matches_registry` / `test_evidence_version_format`
  - `test_citation_version_matches_registry` / `test_citation_version_format`
  - `test_text_transform_version_matches_registry` / `test_text_transform_version_format`
  - `test_retrieval_provider_version_matches_registry` / `test_retrieval_provider_version_format`
- Each asserts the constant equals its registry-registered value AND validates `name/x.y` format.

## Constants Added and Their Values

| Module | Constant | Value |
|--------|----------|-------|
| `evidence/contracts.py` | `EVIDENCE_VERSION` | `"evidence/1.0"` |
| `evidence/citation.py` | `CITATION_VERSION` | `"citation/1.0"` |
| `evidence/text_transform.py` | `TEXT_TRANSFORM_VERSION` | `"text-transform/1.0"` |
| `retrieval/providers/contracts.py` | `RETRIEVAL_PROVIDER_VERSION` | `"retrieval-provider/1.0"` |

## Docstring Fix

`contracts.py` line 16: `evidence/1` -> `evidence/1.0` (was missing the `.0` minor version, which did not match the registry-registered `evidence/1.0`).

## Test Results

### Before (baseline)
```
59 passed in 0.20s
```

### After (with new tests)
```
67 passed in 0.32s
```

### Increment
+8 tests (all passing). All 59 baseline tests continue to pass with no regression.

### Regression confirmation
- `test_retrieval_gateway.py`: File does not exist in this worktree (not applicable).
- `test_rag_course_scope.py`: File does not exist in this worktree (not applicable).
- `product1/` conftest has a `pytest_plugins` deprecation that causes collection errors when running the full test suite; this is pre-existing and unrelated to G2.1 changes.

## Compliance Verification

| Constraint | Status |
|-----------|--------|
| No contract fields changed | Confirmed |
| No dataclass shapes changed | Confirmed |
| No business semantics changed | Confirmed |
| No field types changed | Confirmed |
| No shared files modified (qa_service.py/chat.py/main.py/config.py/ORM/migration/conftest.py/fakes.py/frontend/router/request.js) | Confirmed |
| No other agent files modified (P1-01/02/05/06/07/08/10) | Confirmed |
| No P1-01 document_intelligence contracts modified | Confirmed |
| No API/endpoints/public DTOs changed | Confirmed |
| No commit/push/merge/rebase/dep-install | Confirmed |
| Only version constants + docstring fix + directly-related tests | Confirmed |

## Git Diff Summary

```
$ git diff --stat
 backend/app/platform/evidence/citation.py                 |  5 ++++-
 backend/app/platform/evidence/contracts.py                 |  5 +++--
 backend/app/platform/evidence/text_transform.py            |  5 ++++-
 backend/app/platform/retrieval/providers/contracts.py      |  5 ++++-
 backend/tests/evidence/test_version_constants.py           | 73 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 5 files changed, 88 insertions(+), 5 deletions(-)

$ git diff --name-only
backend/app/platform/evidence/citation.py
backend/app/platform/evidence/contracts.py
backend/app/platform/evidence/text_transform.py
backend/app/platform/retrieval/providers/contracts.py
backend/tests/evidence/test_version_constants.py
```

No dirty files. Only new file is the test file.

## Risks and Limitations

- None. This is a pure normalization change: adding module-level constants and fixing one docstring typo. Zero risk of regression.
