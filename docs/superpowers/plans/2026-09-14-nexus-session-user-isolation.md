# Nexus Session User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate Nexus browser-cached conversations by authenticated user and migrate the legacy shared cache exclusively to `teacherDEMO`.

**Architecture:** Keep server-side `X-Nexus-User-Id` namespacing unchanged because runtime threads are already owner-scoped. Add a small pure frontend storage module that derives a key from the server-refreshed numeric user ID, freezes the current bearer token as a memory-only auth epoch, performs a one-time `teacherDEMO` legacy takeover, and never seeds Demo content in real mode. Wire `NexusPage.vue` through the adapter and verify both local migration and the deployed multi-account flow.

**Tech Stack:** Vue 3, browser localStorage, Node.js built-in test runner, Vite, FastAPI/Nexus Runtime, PostgreSQL.

## Global Constraints

- Do not expose conversation bodies, tokens, passwords, or environment values in logs or fixtures.
- Preserve unrelated dirty-worktree files and do not commit or push without explicit authorization.
- The legacy shared cache belongs only to username `teacherDEMO` (case-insensitive) after migration.
- Server-side data is not bulk-reassigned unless ownership evidence shows it belongs to the legacy shared cache.

---

### Task 1: User-scoped browser session storage

**Files:**
- Create: `frontend/src/app/pages/nexus/sessionStorageIsolation.js`
- Create: `frontend/src/app/pages/nexus/__tests__/sessionStorageIsolation.test.js`
- Modify: `frontend/src/api/nexusAdapter.js`

**Interfaces:**
- Consumes: server-refreshed `/user/me` identity, a memory-only bearer-token epoch, and legacy key `nexus_demo_sessions_v1`.
- Produces: `loadNexusSessions({ storage, demoSeed })` and `saveNexusSessions(sessions, { storage })`.

- [ ] Write tests proving two users get different keys, non-`teacherDEMO` cannot read the legacy cache, `teacherDEMO` atomically takes it over, and real mode has no Demo seed.
- [ ] Run the focused Node test and confirm it fails because the storage module does not exist.
- [ ] Implement the pure storage module and route adapter load/save through it.
- [ ] Run the focused test and frontend unit suite.

### Task 2: Anonymous server-thread migration

**Files:**
- Create outside repository: a timestamped SQL backup/export and a reversible migration script on the server.

**Interfaces:**
- Consumes: the single `nexus_threads.user_id = ''` row and `teacherDEMO.id = 2`.
- Produces: a namespaced `user-2:nexus-session-*` thread only if there is no destination collision.

- [ ] Inspect checkpoint table references and collision counts without reading message content; require a synthetic smoke-test identifier or another verifiable ownership link, otherwise stop without migration.
- [ ] Back up exactly the affected thread metadata/checkpoint rows.
- [ ] Rename the anonymous thread key across Nexus tables and set its owner to `2` in one transaction.
- [ ] Verify anonymous count becomes zero and the destination thread is readable only as user `2`.

### Task 3: Build, deploy, and browser acceptance

**Files:**
- Modify deployed frontend only through the repository release workflow.

**Interfaces:**
- Consumes: the tested frontend change and the deployed release symlink.
- Produces: `/app/nexus` showing only the active account's scoped local cache plus its server-owned threads.

- [ ] Build the frontend and run targeted backend/Nexus identity tests.
- [ ] Create a release, verify the exact SHA/source and built `frontend/dist`, switch the release symlink, and restart only required services.
- [ ] In the existing browser, verify `studentDEMO` no longer sees the legacy shared cache; then verify `teacherDEMO` takes over it when that account is available.
- [ ] Check page identity, non-blank render, console health, and account-switch isolation.
