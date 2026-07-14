# G2.1 Contract Normalization -- Mastery provider_version Unification

## Identity

- **Agent**: P1-07 (Learning & Cognition)
- **Task**: G2.1 Contract Normalization
- **Date**: 2026-07-14

## Worktree Verification

| Check | Expected | Actual | Status |
|---|---|---|---|
| `pwd` | `/e/smartcarb/worktrees/ai-course-p1-07` | `/e/smartcarb/worktrees/ai-course-p1-07` | PASS |
| `git rev-parse --show-toplevel` | `E:/smartcarb/worktrees/ai-course-p1-07` | `E:/smartcarb/worktrees/ai-course-p1-07` | PASS |
| `git branch --show-current` | `agent/p1-07-learning-cognition` | `agent/p1-07-learning-cognition` | PASS |
| `git rev-parse HEAD` | `1cf0269` | `1cf0269` | PASS |
| `git status --short` | (clean) | (clean before edits) | PASS |

## Problem

`provider_version` was inconsistent across the mastery module:

| Location | Value | Parts |
|---|---|---|
| `contracts.py:132` (default in `MasteryProviderResult`) | `"1.0"` | Two-part |
| `rule_baseline.py:208` (in `RuleBasedMasteryProvider.compute()`) | `"1.0.0"` | Three-part |

The learning contract version (`learning/1.0`) uses two-part style. For consistency, mastery `provider_version` should be two-part `"1.0"` everywhere.

## Changes Made

### 1. `backend/app/platform/mastery/contracts.py`

- Added module-level constant `MASTERY_PROVIDER_VERSION = "1.0"` at end of file (line 268)
- This provides a single source of truth for the mastery provider version string

**Before**: (no constant existed)

**After** (end of file):
```python
MASTERY_PROVIDER_VERSION = "1.0"
```

### 2. `backend/app/platform/mastery/rule_baseline.py`

- Import changed: added `MASTERY_PROVIDER_VERSION` from `.contracts`
- Changed `provider_version="1.0.0"` to `provider_version=MASTERY_PROVIDER_VERSION`

**Before** (line 16 import):
```python
from .contracts import MasteryProviderResult
```

**After**:
```python
from .contracts import MASTERY_PROVIDER_VERSION, MasteryProviderResult
```

**Before** (line 208):
```python
provider_version="1.0.0",
```

**After**:
```python
provider_version=MASTERY_PROVIDER_VERSION,
```

### 3. `backend/tests/learning/test_g21_mastery_provider_version.py` (new file)

Two focused tests:

1. `test_provider_version_constant_is_two_part` -- asserts `MASTERY_PROVIDER_VERSION == "1.0"` with exactly one dot
2. `test_rule_based_provider_returns_correct_version` -- constructs a `RuleBasedMasteryProvider`, calls `compute(student_id=1, course_id=1, metadata=...)` with sufficient evidence, and asserts `result.provider_version == "1.0"`

## grep Verification: No other `1.0.0` for mastery provider_version

- `backend/app/platform/mastery/` -- the only `1.0.0` in rule_baseline.py:208 was the one changed (now resolved). Other `1.0.0` matches are in BKT/IRT/DKT interface stubs and `provider.py` -- these are the `version: str = "1.0.0"` parameter defaults in `__init__` signatures of abstract base classes and stubs, not `provider_version` values returned in results. The scope of G2.1 is specifically `provider_version` (the version field in `MasteryProviderResult`), not every `"1.0.0"` string in the module.
- `backend/app/domain/learning/` -- no matches for `1.0.0`

## Test Results

| Suite | Before | After | Delta |
|---|---|---|---|
| `backend/tests/learning/ -q` | 106 passed | 108 passed | +2 (new tests) |
| `backend/tests/test_m4a_route_contract.py` | PASS | PASS | No regression |
| `backend/tests/test_m7_demo_flow.py` | PASS | PASS | No regression |

## Confirmation: No unintended changes

- No contract fields modified
- No `MasteryProviderResult` shape changed
- No business semantics changed (BKT/IRT/DKT remain interface-only stubs)
- No field types changed
- No shared files modified (progress_service.py, prerequisite_service.py, qa_service.py, chat.py, main.py, config.py, ORM, migrations, conftest.py, fakes.py, frontend)
- No other agent files modified
- No API/endpoints changed
- No commit/push/merge/rebase/dep-install performed

## git diff --stat

```
 backend/app/platform/mastery/contracts.py     | 2 ++
 backend/app/platform/mastery/rule_baseline.py | 4 ++--
 2 files changed, 4 insertions(+), 2 deletions(-)
```

(Plus new untracked test file `backend/tests/learning/test_g21_mastery_provider_version.py`)

## git diff --name-only

```
backend/app/platform/mastery/contracts.py
backend/app/platform/mastery/rule_baseline.py
```

(Plus new untracked file `backend/tests/learning/test_g21_mastery_provider_version.py`)

## git status --short

```
 M backend/app/platform/mastery/contracts.py
 M backend/app/platform/mastery/rule_baseline.py
?? backend/tests/learning/test_g21_mastery_provider_version.py
?? docs/refactor/product1/reports/
```
