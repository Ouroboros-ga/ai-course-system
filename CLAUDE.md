# Product 1 Multi-Agent Development Rules

## Required reading

Before planning or editing, read:

- docs/refactor/产品一多CodingAgent并行开发任务分配方案.md
- docs/产品一-泛雅AI互动智课平台.md
- docs/refactor/document_kg_v2/

Do not infer that a feature is implemented from documentation alone.
Verify conclusions against actual code, registered routes, models, services, and tests.

## Repository protection

- Do not modify `refactor/codemind-v3` or the M7 maintenance baseline.
- Do not restore, pop, drop, or modify any existing stash.
- Do not touch unrelated untracked files.
- Do not commit, push, merge, rebase, or create a pull request unless the user explicitly authorizes it.
- Do not install, remove, or upgrade dependencies without explicit approval.
- Do not access production databases, production credentials, or real paid services in automated tests.
- Do not call the real Fanya platform in automated tests.
- Do not weaken, skip, delete, or rewrite existing tests merely to make them pass.

## File ownership

- P1-09 is the sole owner of shared production integration files, including:
  - backend/app/main.py
  - backend/app/core/config.py
  - backend/app/models/
  - migrations
  - public API schemas and endpoints
  - backend/app/api/v1/endpoints/document.py
  - backend/app/services/document_service.py
  - backend/app/services/qa_service.py
  - backend/app/api/v1/endpoints/chat.py
  - frontend/src/router/index.js
  - frontend/src/utils/request.js
  - existing dashboard and player mounting files

- P1-10 is the sole owner of:
  - backend/tests/conftest.py
  - backend/tests/fakes.py
  - shared Product 1 quality-gate infrastructure

- Other agents must remain inside the directories and files assigned by their task card.
- When work requires a file owned by another agent, write an integration proposal instead of modifying that file.
- Do not create duplicate competing implementations inside another agent's domain.

## Compatibility rules

- Preserve existing public API paths, request fields, response fields, startup commands, and current M7 behavior.
- New capabilities must default to disabled or shadow-only unless explicitly approved.
- Shadow execution must not overwrite V1 tables, indexes, task states, or user-visible behavior.
- Missing scope, evidence, permissions, or unsupported schema versions must fail closed.
- Do not present fake or contract tests as proof of real model quality.

## Agent startup requirements

Before editing, every agent must report:

1. Agent identity.
2. Current branch.
3. Current commit SHA.
4. Worktree path.
5. `git status --short`.
6. Exact allowed files and forbidden files.
7. Contracts and documents read.
8. Concrete implementation plan.

Stop and report instead of editing when:

- the worktree is unexpectedly dirty;
- the required change belongs to another Owner;
- a dependency or public contract is not frozen;
- the task requires installing a dependency;
- the task requires production data or credentials;
- the task conflicts with the M7 baseline.

## Completion report

Every agent must finish with:

1. Files changed.
2. Contracts implemented or consumed.
3. Commands executed.
4. Exact test results.
5. Tests not run and reasons.
6. External services contacted, normally none.
7. Remaining risks and limitations.
8. `git diff --check`.
9. `git diff --stat`.
10. `git diff --name-only`.
11. `git status --short`.

A business agent cannot declare its own release gate passed.
P1-10 provides the independent quality result.
P1-00 reviews contract, ownership, and merge readiness.