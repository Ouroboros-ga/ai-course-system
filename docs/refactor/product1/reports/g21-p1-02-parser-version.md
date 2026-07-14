# G2.1 Delivery Report — P1-02 Parser-Provider Contract Normalization

## Identity

| Field | Value |
|---|---|
| Agent | P1-02 (parser-quality) |
| Task | G2.1 Contract Normalization — add `PARSER_PROVIDER_VERSION` constant |
| Worktree | `/e/smartcarb/worktrees/ai-course-p1-02` |
| Branch | `agent/p1-02-parser-quality` |
| HEAD | `1cf02697d294ab514571aef560311ca3779f8933` |
| Pre-task status | Clean (no staged/unstaged/untracked files) |

## Files Changed

| File | Change |
|---|---|
| `backend/app/platform/document_intelligence/registry.py` | Added `PARSER_PROVIDER_VERSION = "parser-provider/1.0"` module-level constant + docstring |
| `backend/app/platform/document_intelligence/quality.py` | Imported `PARSER_PROVIDER_VERSION` from registry; added to `QualityScorer.evaluate()` details dict |
| `backend/tests/document_intelligence/providers/test_parser_provider_version.py` | **New file** — 4 focused tests |

### Changed: `registry.py`

- Added module-level constant:

  ```python
  PARSER_PROVIDER_VERSION: str = "parser-provider/1.0"
  ```

- Expanded module docstring to document this as the canonical source for the contract version, referencing `docs/refactor/product1/contracts/registry.md`.

### Changed: `quality.py`

- Added import: `from .registry import PARSER_PROVIDER_VERSION`
- The `QualityScorer.evaluate()` method now includes `"parser_provider_version": PARSER_PROVIDER_VERSION` in the `details` dict of every `QualityDecision`.
- The existing `scorer_version` field (`"quality/1.0.0"`) was **not** changed — it remains the sub-component version for the scoring engine. This was my explicit design choice per the task instructions ("Do NOT change `scorer_version` semantics").

### New: `test_parser_provider_version.py`

Four tests in `TestParserProviderVersion`:

| Test | What it verifies |
|---|---|
| `test_constant_defined` | `PARSER_PROVIDER_VERSION` is a non-empty string |
| `test_expected_value` | Equals `"parser-provider/1.0"` exactly |
| `test_format_two_part` | Follows `prefix/major.minor` format |
| `test_quality_scorer_exposes_constant` | `QualityScorer.evaluate()` details dict includes the contract version |

## Test Results

| Suite | Before | After | Delta |
|---|---|---|---|
| `backend/tests/document_intelligence/` | 233 passed | 237 passed | +4 |
| Contract tests (`test_contracts.py`) | 28 passed | 28 passed | No change |
| All providers + quality tests | 122 passed | 126 passed | +4 |

No regressions. All 237 tests pass (111 contracts + 122 baseline providers + 4 new).

## Compliance Confirmation

- [x] **No contract fields changed**: `ParserCapabilities`, `ParserOutput`, `ParserProvider` protocol, `ParsePlan`, `QualityDecision`, `FallbackReason`, `QualityVerdict` — untouched.
- [x] **No business semantics changed**: Version constants only; no field types, defaults, or logic changed.
- [x] **No shared files modified**: `main.py`, `config.py`, `document.py`, `document_service.py`, `qa_service.py`, `chat.py`, ORM, migrations, conftest.py, fakes.py, frontend — untouched.
- [x] **No other agent files modified**: P1-01/03/05/06/07/08/10 domains untouched.
- [x] **No API/endpoint/DTO changes**: No routes, no public DTOs.
- [x] **`scorer_version` semantics preserved**: Remains `"quality/1.0.0"` in `QualityScorer.__init__`; only the new `parser_provider_version` key was added alongside it.
- [x] **No commit/push/merge/rebase/dep-install**.

## Git Diff Summary

```
 backend/app/platform/document_intelligence/quality.py  |  2 ++
 backend/app/platform/document_intelligence/registry.py | 16 ++++++++++++++++
 2 files changed, 18 insertions(+)
```

```
M  backend/app/platform/document_intelligence/quality.py
M  backend/app/platform/document_intelligence/registry.py
?? backend/tests/document_intelligence/providers/test_parser_provider_version.py
```

No whitespace errors (`git diff --check` passes; CRLF warnings are platform artifacts, not errors).
