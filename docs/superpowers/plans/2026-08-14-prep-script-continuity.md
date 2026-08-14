# Prep Script Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure both selected-script and one-click script preparation see each script's place in the editable course sequence and generate one continuous lecture rather than repeated standalone openings.

**Architecture:** Build a compact, deterministic sequence from the editable outline tree and its scripts, then send it alongside the existing per-call source context.  Full script bodies remain limited to the selected batch; the sequence contains only stable position and neighbouring titles, so batches retain their bounded prompt size while the model receives the complete course order.  The canonical action prompt and direct-client fallback will apply the same continuity rules.

**Tech Stack:** Python 3, SQLModel course-outline models, Pydantic structured LLM plans, pytest.

## Global Constraints

- No new dependencies or external paid-service calls in tests.
- Preserve Course Access v1 and locked-node exclusions; context never grants a target write permission.
- Retain locked scripts as opaque sequence boundaries for ordering, but do not expose their IDs, source text, or titles as editable context.
- Keep the complete-course script-body payload bounded to the active batch.
- Reject a course whose compact sequence itself exceeds the script-planning context budget before any batch starts.
- Do not commit, push, or modify unrelated workspace files.

---

## File Structure

- Modify: `backend/app/services/course_prep_agent_service.py` — derive and attach the canonical lecture sequence for selected and batch script actions.
- Modify: `backend/app/platform/agents/prep/prompts.py` — make the structured action planner enforce the supplied sequence's opening, transition, and closing semantics.
- Modify: `backend/tests/test_course_prep_agent.py` — exercise real planning payloads for selected and multi-batch script optimization.

### Task 1: Expose Course Position to Script Planning

**Files:**

- Modify: `backend/tests/test_course_prep_agent.py`
- Modify: `backend/app/services/course_prep_agent_service.py`

**Interfaces:**

- Produces: `CoursePrepAgentService._lecture_sequence(outline, scripts) -> list[dict[str, object]]`.
- Produces: `payload["course_context"]["lecture_sequence"]`, with `index`, `total`, `title`, `previous_title`, and `next_title` for each editable script in deterministic outline-tree order.

- [ ] **Step 1: Write the failing payload tests**

```python
assert payload["course_context"]["lecture_sequence"] == [
    {"index": 1, "total": 3, "title": "汽车的定义", "previous_title": None, "next_title": "汽车的分类"},
    {"index": 2, "total": 3, "title": "汽车的分类", "previous_title": "汽车的定义", "next_title": "发动机基础"},
    {"index": 3, "total": 3, "title": "发动机基础", "previous_title": "汽车的分类", "next_title": None},
]
```

Test a selected middle script and every one-click batch; the selected script must retain the same index and neighbours even though only its own body is editable in that request.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd backend; python -m pytest tests/test_course_prep_agent.py -k "lecture_sequence" -q`

Expected: FAIL because `course_context` does not yet contain `lecture_sequence`.

- [ ] **Step 3: Implement the minimum context builder**

```python
@staticmethod
def _lecture_sequence(outline, scripts):
    # Traverse the editable outline tree in sibling (order_index, id) order,
    # retain nodes owning a supplied script, then annotate adjacent titles.
    ...
```

Pass complete editable outline and script lists as sequence-only context for both selected-script and one-click paths.  Keep `course_context["scripts"]` restricted to the active selected/group scripts.

For traversal, use the full draft tree and script list so a locked opening or closing cannot cause an editable script to become sequence-first or sequence-last.  Emit locked items as opaque `已锁定讲解` boundaries without a target ID.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd backend; python -m pytest tests/test_course_prep_agent.py -k "lecture_sequence" -q`

Expected: PASS.

- [ ] **Step 5: Guard locked boundaries and sequence capacity**

Write a nested-outline test proving that an editable child of a locked opening remains the second sequence item and sees `已锁定讲解` as its predecessor.  Add a capacity test with 200 long titles; it must fail closed before grouped requests start.  Then implement the opaque boundary entries and bounded sequence preflight, and rerun both tests to green.

### Task 2: Constrain Generated Script Openings and Transitions

**Files:**

- Modify: `backend/tests/test_course_prep_agent.py`
- Modify: `backend/app/platform/agents/prep/prompts.py`
- Modify: `backend/app/services/course_prep_agent_service.py`

**Interfaces:**

- Consumes: `course_context.lecture_sequence` from Task 1.
- Produces: `prep.action_planner` prompt version with a continuity contract used by `PrepLLMAdapter.plan_incremental()`.

- [ ] **Step 1: Write the failing prompt-contract test**

```python
assert "lecture_sequence" in PREP_ACTION_PLANNER_PROMPT.system_template
assert "只有序列首项" in PREP_ACTION_PLANNER_PROMPT.system_template
assert "不得把每个讲稿写成独立开场" in PREP_ACTION_PLANNER_PROMPT.system_template
```

The expected behaviour is that a middle script may connect to its predecessor but may not use a fresh greeting, while only the final script may provide a course-level closing.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd backend; python -m pytest tests/test_course_prep_agent.py -k "continuity_prompt" -q`

Expected: FAIL because the canonical action prompt has no explicit `lecture_sequence` contract.

- [ ] **Step 3: Implement the minimum prompt changes**

```text
For script actions, `course_context.lecture_sequence` is the canonical course order.
Only sequence index 1 may greet; middle items begin with a concise transition;
only the final item may close the whole course. Do not turn every script into
an independent opening or closing, and use neighbours only as discourse links.
```

Increment the semantic version of `PREP_ACTION_PLANNER_PROMPT`; mirror these constraints in the direct-client batch system prompt so both supported planner integrations have the same behaviour.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `cd backend; python -m pytest tests/test_course_prep_agent.py -k "lecture_sequence or continuity_prompt" -q`

Expected: PASS.

### Task 3: Verify the Affected Prep Paths

**Files:**

- Verify: `backend/tests/test_course_prep_agent.py`
- Verify: `backend/tests/test_prep_intent_routing.py`
- Verify: `backend/tests/test_controlled_prep_workflow.py`

- [ ] **Step 1: Run targeted backend regression coverage**

Run: `cd backend; python -m pytest tests/test_course_prep_agent.py tests/test_prep_intent_routing.py tests/test_controlled_prep_workflow.py -q`

Expected: PASS; no real LLM provider is invoked.

- [ ] **Step 2: Check the patch is syntactically and mechanically clean**

Run: `python -m compileall -q backend/app/services/course_prep_agent_service.py backend/app/platform/agents/prep/prompts.py; git diff --check`

Expected: both commands exit 0.

## Self-Review

- Spec coverage: Task 1 makes selected and one-click preparation aware of course position without exposing unrelated full script bodies; Task 2 prevents repeated greetings and enforces transitions; Task 3 checks both the focused contract and existing Prep workflows.
- Placeholder scan: no implementation step depends on an unspecified external type or dependency.
- Type consistency: the payload addition is a JSON list of primitive fields, consumed only by the LLM prompt; it does not alter PatchProposal or persistence schemas.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-14-prep-script-continuity.md`.  The requested adjustment will be executed inline in this session using the red-green-refactor steps above.
