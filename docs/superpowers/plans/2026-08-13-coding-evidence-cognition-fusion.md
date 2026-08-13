# Coding Answer Evidence and Cognition Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `test-driven-development` to implement each task in order. Use `verification-before-completion` before reporting completion.

**Goal:** Allow CodingAgent to read only the currently authorized student's submitted source code for diagnosis, while making code-answer results and question-bank answers parallel, traceable inputs to EduAgent's cognition assessment without exposing source code to EduAgent.

**Architecture:** Add a CodingAgent-only `CodeSubmissionPort` that retrieves one scoped terminal `ExperimentRun` and returns source code only to the local response-generation call. Extend the existing diagnosis port with a source-free `CodingLearningSignal`. Persist one server-verified `coding_execution` evidence record per mapped knowledge node for a terminal graded experiment result, enqueue generic learning-projection outbox events after finalization, and reuse `CognitiveStateService` with an explicit weighted observation fusion model.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, Alembic, LangGraph, pytest, Vue (no public API contract change required).

## Global Constraints

- Source code is never added to LangGraph state, `CodingDiagnosisRecord`, `LearningEvidenceRecord`, agent traces, audit records, serialized CodingAgent output, or EduAgent prompts.
- `CodeSubmissionPort` is injected only into CodingAgent composition; EduAgent continues to receive only `CodingDiagnosisPort` and `StudentHistoryPort` data.
- Only a terminal Judge0 result in the recognized scored-outcome set can create cognitive evidence. `PENDING`, `SANDBOX_UNAVAILABLE`, and infrastructure failures create none.
- Knowledge-node mappings come solely from `ExperimentDefinition.knowledge_node_ids`; do not guess a release or outline-node identity when it is absent.
- Preserve the legacy `LearningProjectionOutbox.attempt_id` path for question attempts while adding generic source identity for code evidence.
- Preserve unrelated dirty worktree changes and do not commit them.

---

## Task 1: Add CodingAgent-only scoped source access

**Files:**

- Modify: `backend/app/platform/agents/contracts/sandbox.py`
- Modify: `backend/app/platform/agents/providers/sandbox/coding.py`
- Modify: `backend/app/platform/agents/providers/sandbox/__init__.py`
- Modify: `backend/app/platform/agents/coding/composition.py`
- Modify: `backend/app/platform/agents/coding/workflow.py`
- Modify: `backend/app/platform/agents/bootstrap.py`
- Test: `backend/tests/agents/test_coding_agent_privacy.py`
- Test: `backend/tests/agents/test_coding_eduagent_integration.py`

**Interfaces:**

```python
class CodeSubmissionPort(Protocol):
    async def get_submission_for_diagnosis(
        self, *, student_id: str, course_id: str, run_id: str
    ) -> Mapping[str, Any] | None: ...
```

The session-scoped provider verifies `ExperimentRun.run_id`, `student_id`, and `course_id`, requires a terminal run, and returns only `run_id`, `language`, and `source_code`. `CodingTools` accepts this optional port. `generate_diagnosis_response` obtains the source into a local variable immediately before the CodingAgent LLM call, passes it under `submission`, never returns or stores it, and rejects an LLM answer that repeats any non-empty full source or a normalized meaningful source line. The existing student-owned explanation endpoint invokes this scoped CodingAgent; teacher views remain source-free rules. EduAgent consumes a separate defensive whitelist of bounded structural signal fields and local safe action vocabulary.

### Step 1.1: Write failing boundary tests

Add tests proving:

1. CodingAgent's LLM context includes the scoped source and language for its own authorized terminal run.
2. It still excludes sandbox artifacts, full user messages, and unrelated runs.
3. Cross-student/cross-course/pending access returns `None`.
4. `CodingDiagnosisPort` / `StudentHistoryPort` output remains source-free, including after the new source port exists.

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\agents\test_coding_agent_privacy.py tests\agents\test_coding_eduagent_integration.py -q
```

Expected: FAIL because no source port is available to CodingAgent.

### Step 1.2: Implement the scoped port and ephemeral prompt use

Implement the protocol, provider, factory export, composition injection, bootstrap wiring for CodingAgent only, and the local-only workflow prompt context. Keep all diagnostic serialization source-free.

### Step 1.3: Re-run the focused tests

Run the same command. Expected: PASS.

---

## Task 2: Define the source-free Coding learning signal

**Files:**

- Modify: `backend/app/platform/agents/providers/sandbox/coding.py`
- Modify: `backend/app/platform/agents/edu/workflow.py`
- Test: `backend/tests/agents/test_coding_eduagent_integration.py`

**Interface:** Add the following nested object to diagnosis-port/history-port payloads, never to persisted diagnosis data:

```json
{
  "learning_signal": {
    "schema_version": "coding-learning-signal/1",
    "run_id": "...",
    "outcome": "RUNTIME_ERROR",
    "error_class": "runtime",
    "knowledge_node_ids": [101, 102],
    "repeated_error": {"recent_count": 2, "is_repeated": true},
    "recommended_actions": ["..."],
    "evidence_refs": ["experiment_run:..."]
  }
}
```

The provider derives node IDs only through the run → attempt → definition chain and derives repeated-error count from the student's recent diagnoses in the same course. `EduAgent.generate_response` continues to use diagnosis/history only; add an assertion that its LLM context has `learning_signal` but no source or sandbox artifacts.

### Step 2.1: Write failing signal/redaction tests

Test a mapped definition and repeated same error class. Assert the exact signal fields and source redaction in both direct diagnosis and learning history payloads.

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\agents\test_coding_eduagent_integration.py -q
```

Expected: FAIL because no learning signal exists.

### Step 2.2: Implement signal construction

Add a private provider helper; do not alter `CodingDiagnosisRecord` schema. Preserve existing payload fields for compatibility.

### Step 2.3: Re-run focused integration tests

Run the command above. Expected: PASS.

---

## Task 3: Persist server-verified per-node coding evidence

**Files:**

- Modify: `backend/app/models/knowledge_bundle_model.py`
- Modify: `backend/app/services/experiment_service.py`
- Test: `backend/tests/test_experiments.py`
- Test: `backend/tests/test_learning_evidence.py`

**Rules:**

- Add `EvidenceType.CODING_EXECUTION = "coding_execution"`.
- For each valid `ExperimentDefinition.knowledge_node_ids` member, write an idempotent `LearningEvidenceRecord` with source `experiment_finalize_service`, server-only score `1.0` or `0.0`, and the experiment attempt/run references.
- Write evidence for `ACCEPTED`, `WRONG_ANSWER`, `TIME_LIMIT_EXCEEDED`, `MEMORY_LIMIT_EXCEEDED`, `RUNTIME_ERROR`, and `COMPILATION_ERROR`; write none for unavailable/pending/infrastructure outcomes.
- Set `ExperimentAttempt.evidence_id` to the first deterministic record for compatibility; additional node evidence records remain independently queryable.
- Keep release/outline identity unknown unless the existing context resolver can prove it.

### Step 3.1: Write failing finalization tests

Add tests for:

1. Accepted mapped code run writes one node-specific `coding_execution` record with score `1.0`.
2. Verified failed mapped code run writes score `0.0`.
3. Sandbox-unavailable run writes no code cognition evidence.
4. Re-finalization remains idempotent.

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_experiments.py tests\test_learning_evidence.py -q
```

Expected: FAIL because current code only records successful course-level experiment completion evidence.

### Step 3.2: Implement finalization evidence

Refactor `ExperimentFinalizeService._write_formal_evidence` around deterministic evidence IDs and recognized outcomes. Validate each numeric node against the same course before writing it.

### Step 3.3: Re-run evidence tests

Run the command above. Expected: PASS.

---

## Task 4: Generalize the learning-projection outbox

**Files:**

- Modify: `backend/app/models/knowledge_bundle_model.py`
- Modify: `backend/app/services/learning_projection_outbox_service.py`
- Modify: `backend/app/platform/tasks/handlers.py`
- Create: `backend/alembic/versions/20260813_1200_0058_coding_evidence_cognition.py`
- Test: `backend/tests/learning/test_learning_projection_outbox.py` (or the existing matching test module)
- Test: `backend/tests/test_experiments.py`

**Model transition:**

```python
attempt_id: int | None                 # legacy question FK, retained
source_type: str = "question_attempt" # e.g. experiment_attempt
source_ref: str                        # stable external attempt identifier
UniqueConstraint("source_type", "source_ref", "student_id", "course_id", "knowledge_node_id")
```

The existing `enqueue_learning_projection(..., attempt_id=...)` stays callable and defaults to `source_type="question_attempt"`, `source_ref=str(attempt_id)`. Add a code-evidence enqueue helper. The worker behavior remains unchanged. The task handler creates outbox rows in the finalization transaction, commits them, then invokes the existing non-blocking dispatcher by event ID.

### Step 4.1: Write failing compatibility and code-event tests

Test legacy question enqueue idempotency, generic code enqueue idempotency, distinct-source separation, and post-finalization code event dispatch after commit.

Run the focused outbox and experiment tests. Expected: FAIL because outbox rows require `QuestionAttempt.id`.

### Step 4.2: Implement model/service/handler and migration

Write an Alembic migration that works on PostgreSQL and local SQLite test paths, backfills legacy source fields, makes `attempt_id` nullable, replaces the old unique constraint/index safely, and supplies a symmetric downgrade where feasible. Do not call application metadata creation.

### Step 4.3: Re-run focused outbox tests

Expected: PASS.

---

## Task 5: Reuse cognition assessment with explicit weighted fusion

**Files:**

- Modify: `backend/app/services/cognitive_service.py`
- Test: `backend/tests/test_cognitive_recommendation.py`
- Test: `backend/tests/test_learning_evidence.py`

**Fusion policy:**

| Input | Eligibility | Weight |
| --- | --- | ---: |
| `QuestionAttempt` server-scored result | Existing valid scored quiz attempt | 1.0 |
| `LearningEvidenceRecord(coding_execution)` | Recognized terminal Judge0 result, mapped knowledge node | 1.5 |

For a knowledge node, observed performance is `sum(score * weight) / sum(weight)`. Positive or negative performance conclusions require at least `3.0` effective sample weight. `sample_size` remains the number of raw observations; reason codes state which input sources participated and that weighted fusion was used. Hint-dependency remains quiz-only in this increment; error category/repeated-error signal is teaching context and not a score by itself.

### Step 5.1: Write failing cognition tests

Add tests that seed quiz and code evidence for one node and assert:

1. Numeric weighted performance uses 1.0/1.5 weights.
2. One code failure alone is insufficient to assert a mastery level.
3. Existing quiz-only cognitive outputs retain their former value/threshold behavior.
4. Evidence references and reason codes identify code evidence without exposing source.

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_cognitive_recommendation.py tests\test_learning_evidence.py -q
```

Expected: FAIL because cognition currently queries only `QuestionAttempt`.

### Step 5.2: Implement normalized scored observations

Introduce a private normalized observation structure/helper in `CognitiveStateService`; feed existing quiz observations and new coding evidence into the current performance/confusion calculations without changing public cognitive-state schemas.

### Step 5.3: Re-run cognition tests

Run the command above. Expected: PASS.

---

## Task 6: Synchronize current architecture documentation

**Files:**

- Modify: `docs/phase1/CodingEduAgent与EduAgent集成说明.md`
- Modify: `docs/phase1/统一学习进度认知推荐统计契约.md`
- Modify: `docs/phase1/实验室代码沙箱可信评测契约.md`
- Modify: `docs/DOCUMENTATION_INDEX.md` (only the relevant current-document status/index entry)
- Modify: `README.md` (only the current capability summary if an appropriate existing section exists)

Document the dated decision, strict source boundary, `CodingLearningSignal` shape, formal evidence eligibility, source/release identity limitations, 1.0/1.5 fusion policy, 3.0 effective threshold, and outbox dispatch semantics. Do not alter historical documents or claim deployment before it occurs.

### Step 6.1: Documentation consistency scan

Run:

```powershell
rg -n "不得接收源代码|不.*源代码|coding_execution|CodingLearningSignal|认知" README.md docs/phase1 docs/DOCUMENTATION_INDEX.md
```

Expected: no current document incorrectly states that CodingAgent can never read its authorized submission, and no document claims raw source reaches EduAgent.

---

## Task 7: Full verification, review, commit, push, and authorized deployment

1. Run focused regression suite for coding privacy/integration, experiment finalization, learning evidence/outbox, cognition, and run-id flow.
2. Run migration upgrade/downgrade checks against a disposable local database where the repository test setup supports it.
3. Inspect `git diff --check`, targeted `git diff`, and `git status --short`; stage only files created/modified by this feature.
4. Perform a code review focused on data leakage, authorization scope, idempotency, migration safety, fusion arithmetic, and post-commit dispatch.
5. Commit and push the scoped verified changes to the current confirmed branch/remote.
6. SSH to `root@120.26.104.247` for the mandated read-only preflight: repo/branch/status, service health, disk, and migration head. Redact any sensitive output.
7. Pull only the pushed commit, run the explicit migration, restart only the authorized application service if repository deployment conventions require it, and perform a non-sensitive health check plus the relevant API/smoke verification. Report exact deployed commit and any limitation.
