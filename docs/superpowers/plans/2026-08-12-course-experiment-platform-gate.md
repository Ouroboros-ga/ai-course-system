# Course Experiment Platform Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the teacher-controlled “实验平台（代码沙箱）” switch the single current gate for exposing the course experiment area, so an unsupported course never exposes an unusable experiment entry.

**Architecture:** The current platform only implements code-sandbox experiments. The capability update API therefore normalizes a disabled code sandbox to a disabled experiment platform, while the frontend uses one pure capability predicate for navigation visibility. The sandbox settings page owns the teacher-facing switch; future non-code experiment types can introduce their own capability without reusing this code-sandbox gate.

**Tech Stack:** FastAPI, SQLModel, Vue 3, Node built-in test runner, pytest.

## Global Constraints

- Do not enable the experiment platform for course 2; automotive engineering remains outside the current code-sandbox implementation.
- Do not read or log source code, sandbox tokens, or external-service credentials.
- Keep Course Access v1 as the only authorization path.
- Use `SfxButton` for settings actions and existing design tokens for state presentation.
- Preserve the existing `experiment` field for future non-code experiment expansion; current API normalization only prevents the unsupported `experiment=true, coding_sandbox=false` state.

---

### Task 1: Define the current platform-gate contract

**Files:**
- Create: `frontend/src/app/lib/courseExperimentPlatform.js`
- Create: `frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js`
- Modify: `frontend/src/app/pages/course/CourseLayout.vue`

**Interfaces:**
- Produces `isCodeSandboxExperimentPlatformEnabled(capabilities)` for all navigation consumers.
- Produces `withCodeSandboxExperimentPlatform(capabilities, enabled)` for the settings page API payload.

- [ ] **Step 1: Write the failing frontend test**

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isCodeSandboxExperimentPlatformEnabled,
  withCodeSandboxExperimentPlatform,
} from '../courseExperimentPlatform.js'

test('disabled code sandbox hides the current experiment platform', () => {
  assert.equal(isCodeSandboxExperimentPlatformEnabled({ experiment: true, coding_sandbox: false }), false)
})

test('switching the current code-sandbox platform changes both coupled flags', () => {
  assert.deepEqual(
    withCodeSandboxExperimentPlatform({ learning: true, experiment: true, coding_sandbox: true }, false),
    { learning: true, experiment: false, coding_sandbox: false },
  )
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js`

Expected: FAIL because `courseExperimentPlatform.js` does not exist.

- [ ] **Step 3: Implement the minimal pure helpers and consume the predicate in `CourseLayout.vue`**

```js
export function isCodeSandboxExperimentPlatformEnabled(capabilities = {}) {
  return Boolean(capabilities.experiment && capabilities.coding_sandbox)
}

export function withCodeSandboxExperimentPlatform(capabilities = {}, enabled) {
  return { ...capabilities, experiment: Boolean(enabled), coding_sandbox: Boolean(enabled) }
}
```

Set the `experiments` navigation item's `enabled` field from this predicate, not from a literal `true`.

- [ ] **Step 4: Run the frontend test to verify it passes**

Run: `node --test frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js`

Expected: PASS with both tests green.

### Task 2: Normalize capability updates in the server authority

**Files:**
- Modify: `backend/app/api/v1/endpoints/course_access.py`
- Modify: `backend/tests/test_course_access.py`

**Interfaces:**
- Consumes the existing complete `CapabilityUpdateRequest` payload.
- Produces persisted `experiment=false` and `coding_sandbox=false` whenever the current code-sandbox platform is disabled.

- [ ] **Step 1: Write the failing API test**

```python
def test_disabling_code_sandbox_also_hides_current_experiment_platform(client, session, teacher_user):
    course = _course(session, teacher_user.id)
    payload = _full_capability_payload(experiment=True, coding_sandbox=False)

    response = client.put(
        f"/api/v1/course-access/courses/{course.id}/capabilities",
        json=payload,
        headers=_auth(_token(teacher_user)),
    )

    assert response.status_code == 200
    assert response.json()["data"]["capabilities"]["experiment"] is False
    assert response.json()["data"]["capabilities"]["coding_sandbox"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_course_access.py -k disabling_code_sandbox -q`

Expected: FAIL because the endpoint currently persists the inconsistent payload unchanged.

- [ ] **Step 3: Implement the smallest normalization at the API boundary**

```python
values = payload.model_dump()
if not values["coding_sandbox"]:
    values["experiment"] = False
```

Apply the normalized `values` for both create and update paths and return them in the response.

- [ ] **Step 4: Run the targeted backend test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_course_access.py -k disabling_code_sandbox -q`

Expected: PASS.

### Task 3: Expose the teacher switch in sandbox settings

**Files:**
- Modify: `frontend/src/app/pages/course/settings/SettingsSandboxPage.vue`
- Modify: `frontend/src/api/course_access.js` only if the current client shape needs a typed convenience wrapper.

**Interfaces:**
- Consumes `getCourseCapabilities(courseId)` and `updateCourseCapabilities(courseId, fullPayload)`.
- Uses `withCodeSandboxExperimentPlatform` to produce a complete payload.
- Calls `courseContext.reload()` after a successful capability update so the secondary navigation changes immediately.

- [ ] **Step 1: Extend the failing pure helper test with preserving unrelated capabilities**

```js
test('platform switch preserves unrelated course capabilities', () => {
  assert.deepEqual(
    withCodeSandboxExperimentPlatform({ learning: true, knowledge_graph: true, experiment: false, coding_sandbox: false }, true),
    { learning: true, knowledge_graph: true, experiment: true, coding_sandbox: true },
  )
})
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run: `node --test frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js`

Expected: FAIL until the helper explicitly preserves unrelated flags.

- [ ] **Step 3: Add one explicit settings control**

Add a panel headed `实验平台（代码沙箱）`, with an enabled/disabled text state, an explanation that the current platform only supports code experiments, and a single `SfxButton` action. Disable the policy-editor controls when the platform is off. Do not add a second horizontal navigation row.

- [ ] **Step 4: Run the helper test and build**

Run: `node --test frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js && npm.cmd --prefix frontend run build`

Expected: helper tests pass and Vite completes successfully.

### Task 4: Verify and deploy deliberately

**Files:**
- Modify: `docs/phase1/功能现状审计表.md`

- [ ] **Step 1: Record the implemented semantics**

Document that current experiment navigation requires the enabled code-sandbox platform, while future non-code experiments require a distinct, explicitly implemented capability before exposure.

- [ ] **Step 2: Run final verification**

Run: targeted pytest, frontend helper test, and frontend build.

Expected: all commands exit zero.

- [ ] **Step 3: Browser acceptance after deployment**

For course 2, verify both teacher and student views omit `实验任务`. For a code course with the switch enabled, verify the navigation remains visible. Do not submit code during this navigation-only acceptance check.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/lib/courseExperimentPlatform.js
git add frontend/src/app/lib/__tests__/courseExperimentPlatform.test.js
git add frontend/src/app/pages/course/CourseLayout.vue
git add frontend/src/app/pages/course/settings/SettingsSandboxPage.vue
git add backend/app/api/v1/endpoints/course_access.py
git add backend/tests/test_course_access.py
git add docs/phase1/功能现状审计表.md
git add docs/superpowers/plans/2026-08-12-course-experiment-platform-gate.md
git commit -m "fix: gate course experiment navigation by sandbox platform"
```
