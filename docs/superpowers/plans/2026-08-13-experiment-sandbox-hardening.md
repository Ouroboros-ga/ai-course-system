# Experiment Sandbox Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` task-by-task. No production behavior is changed before a focused failing test demonstrates the required contract.

**Goal:** Provide a course-gated programming-experiment loop in which only a server-owned asynchronous Judge0 result can finalize an ACM/ICPC grade and produce a lab record.

**Architecture:** Free sandbox execution remains a non-scoring, quota-limited port. Formal runs create a durable `TaskRecord` and an idempotent `ExperimentRun`; the worker holds a database lease while it evaluates Judge0 cases, then finalizes the attempt and projects a read-only lab record. Coding feedback consumes only a compact diagnosis record; TeachingAgent dispatch creates a teacher-approved recommendation and never a run.

**Tech Stack:** FastAPI, SQLModel, Alembic, existing `TaskService`/local worker, Judge0, Vue 3.

## Global Constraints

- Course Access v1 is the only authorization path.
- Student code only executes through Judge0; no code, Judge0 credentials, hidden input/output, or complete artifacts enter an LLM context.
- ACM/ICPC formal grades are exactly `1.0/true` for all tests accepted and `0.0/false` otherwise.
- A disabled course experiment capability rejects experiment reads, dispatches, and executions.
- New frontend controls use `SfxButton`; no dependency is added.
- Migration revision 0055 includes a batch marker, an idempotent upgrade, and an explicit downgrade.

## Tasks

### Task 1: Establish the trusted finalization boundary

**Files:**
- Modify: `backend/tests/test_experiments.py`, `backend/tests/test_labs.py`
- Modify: `backend/app/api/v1/endpoints/experiments.py`, `backend/app/api/v1/endpoints/labs.py`
- Modify: `backend/app/services/experiment_service.py`, `backend/app/services/resource_service.py`

- [ ] Add RED tests proving that `/submit`, `/finalize`, and `/lab/{lab_id}/records` are absent; a formal run without `Idempotency-Key` is rejected; a run request returns HTTP 202 and task/run IDs.
- [ ] Implement the new route contract: formal submission owns the `submitted` transition and always creates/returns the persisted task.
- [ ] Remove legacy public lab writes and legacy independent lab mutations; preserve only the projection read endpoints.
- [ ] Run the focused endpoint tests.

### Task 2: Make grade and projection server-owned

**Files:**
- Modify: `backend/tests/test_experiments.py`
- Modify: `backend/app/models/experiment_model.py`, `backend/app/models/resource_model.py`
- Modify: `backend/app/services/experiment_service.py`, `backend/app/services/resource_service.py`

- [ ] Add RED tests for full-AC and non-full-AC finalization, terminal-attempt idempotency, and one trusted record per terminated attempt.
- [ ] Implement binary grading, only worker-owned finalization, and validated projection of course, experiment, student, score, status, evidence, and return anchor.
- [ ] Keep free execution out of attempts, evidence, and records.
- [ ] Run the service tests.

### Task 3: Add durable execution controls and recovery

**Files:**
- Modify: `backend/tests/test_experiments.py`, `backend/tests/test_tasks.py`
- Modify: `backend/app/models/experiment_model.py`, `backend/app/models/platform_admin_model.py`
- Modify: `backend/app/services/experiment_service.py`, `backend/app/services/platform_task_concurrency_service.py`
- Modify: `backend/app/platform/tasks/worker.py`, `backend/app/platform/tasks/handlers.py`

- [ ] Add RED tests for replayed idempotency keys, one held database lease, unavailable sandbox retry semantics, and cancellation without finalization.
- [ ] Add the run key, lease, quota window, and `sandbox_execution` policy; make worker acquire local and database limits, renew around each test, and recover expired leases.
- [ ] Mark judge unavailability retryable while compile/runtime/wrong-answer results finish the task normally.
- [ ] Run focused task and experiment tests.

### Task 4: Validate publish and teacher preview

**Files:**
- Modify: `backend/tests/test_experiments.py`
- Modify: `backend/app/services/experiment_service.py`, `backend/app/api/v1/endpoints/experiments.py`

- [ ] Add RED tests for a non-1.0 passing score, unlocked version, invalid test weights, and missing preview verification.
- [ ] Add `ExperimentPublishValidator` and a transient reference-solution preview endpoint; retain only its verified timestamp, never its source.
- [ ] Enforce a locked, active default version with valid limits, language whitelist, at least one test, weights totaling one, and capability/Judge0 readiness before publication.
- [ ] Run publish validation tests.

### Task 5: Restrict agents and dispatch recommendations

**Files:**
- Modify: `backend/tests/test_p1_7_judge0_sandbox_port.py` and focused agent tests
- Modify: `backend/app/services/coding_eduagent_service.py`, `backend/app/platform/agents/contracts/experiment.py`
- Modify: `backend/app/platform/agents/providers/experiment/experiment.py`, `backend/app/platform/agents/bootstrap.py`
- Create: experiment dispatch provider/handler tests as needed

- [ ] Add RED tests that diagnostic/LLM payloads exclude source, hidden tests, stdout/stderr, and credentials; CodingAgent registers without TeachingAgent LLM; an unapproved proposal cannot create a recommendation.
- [ ] Implement a diagnosis-only explanation endpoint and rule fallback, plus a governed `ExperimentDispatchPort` that only resolves published locked experiments from the current course.
- [ ] On teacher approval revalidate membership, course capability, version, and node; create one recommendation and never create an attempt/run.
- [ ] Run focused agent tests.

### Task 6: Replace frontend submission and lab entry points

**Files:**
- Modify: `frontend/src/api/experiments.js`, `frontend/src/api/labs.js`
- Modify: `frontend/src/app/pages/course/CourseExperimentsPage.vue`, `frontend/src/app/components/course/TeacherExperimentPanel.vue`
- Modify: lab pages that consume independent lab creation/enrollment APIs
- Test: existing frontend API contract tests plus new node tests

- [ ] Add RED API-client contract tests for the header, 202 polling route, 429 retry time, and read-only lab projection links.
- [ ] Replace synchronous run/finalize calls with create-attempt, async submit, task polling, terminal run result, and diagnosis explanation flow.
- [ ] Turn teacher editing into definition, limits, version/tests, preview, lock, publish stages using `SfxButton`; remove independent lab creation/publish/enroll actions.
- [ ] Run node tests and frontend build.

### Task 7: Ship schema and documentary contract together

**Files:**
- Create: `backend/alembic/versions/20260813_0900_0055_experiment_sandbox_reliability.py`
- Modify: `backend/app/models/database.py`, `README.md`, `docs/phase1/*`, `docs/DOCUMENTATION_INDEX.md`

- [ ] Add migration tests for upgrade/downgrade and partial unique indexes.
- [ ] Add all persisted fields and tables with an explicit `experiment_sandbox_reliability_v1` marker and an inverse downgrade.
- [ ] Record that legacy lab records are unverified and hidden from formal views, and that lab write routes are removed.
- [ ] Verify Alembic upgrade/downgrade, targeted pytest, backend compilation, frontend build, and contract tests before reporting status.
