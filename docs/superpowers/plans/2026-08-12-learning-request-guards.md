# Learning Request Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the learning experience from issuing invalid visualization and evidence-image requests when it has only an outline-node ID or no document ID.

**Architecture:** Keep the backend contracts strict. Normalize the legacy integer visualization filter in its API client so every caller is protected. Route citation page-image loading through an API helper that permits document-scoped evidence-v2 only for its standalone viewer context; a course-scoped citation without an authorized render URL returns no image request.

**Tech Stack:** Vue 3, JavaScript ES modules, Node built-in test runner, Vite.

## Global Constraints

- Preserve the existing integer `VisualizationPlanRecord.node_id` and its FastAPI validation contract.
- Do not use the admin-only `evidence-v2` API from the learning page's course-scoped citation flow.
- Do not install dependencies, access production data, or commit changes without explicit authorization.
- Preserve unrelated worktree changes.

---

### Task 1: Visualization list-query guard

**Files:**
- Create: `frontend/src/api/visualizationRequestGuards.js`
- Modify: `frontend/src/api/visualization.js`
- Test: `frontend/src/api/__tests__/visualizationRequestGuards.test.js`

**Interfaces:**
- Produces: `sanitizePlanListParams(params)` from `visualizationRequestGuards.js`, returning a copy of the input with `node_id` omitted unless it is a positive safe integer.
- Consumes: `listPlans(courseId, params)` uses the sanitized query object for the GET request.

- [x] **Step 1: Write the failing test**

```js
assert.deepEqual(
  sanitizePlanListParams({ node_id: 'on_0b0ab2ff6f344c9ca0aa48f44d45cdcc', status: 'published' }),
  { status: 'published' },
)
```

- [x] **Step 2: Run test to verify it fails**

Run: `node --test src/api/__tests__/visualizationRequestGuards.test.js`

Expected: FAIL because `sanitizePlanListParams` is not exported.

- [x] **Step 3: Write minimal implementation**

```js
export function sanitizePlanListParams(params = {}) {
  const sanitized = { ...params }
  const nodeId = Number(sanitized.node_id)
  if (!Number.isSafeInteger(nodeId) || nodeId <= 0) delete sanitized.node_id
  else sanitized.node_id = nodeId
  return sanitized
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `node --test src/api/__tests__/visualizationRequestGuards.test.js`

Expected: PASS.

### Task 2: Citation page-image source guard

**Files:**
- Create: `frontend/src/api/evidenceRequestGuards.js`
- Modify: `frontend/src/api/evidence.js`
- Modify: `frontend/src/app/components/learn/CitationStage.vue`
- Test: `frontend/src/api/__tests__/evidenceRequestGuards.test.js`

**Interfaces:**
- Produces: `resolveCitationPageImageSource({ courseId, documentId, pageNumber, renderUrl })` from `evidenceRequestGuards.js`, plus `fetchCitationPageImage(...)` in `evidence.js`; together they resolve to an authorized protected image URL, a standalone document image URL, or `null` when an image is not available.
- Consumes: `CitationStage.toggleCitation(citation)` calls this helper instead of directly calling the document-scoped image endpoint.

- [x] **Step 1: Write the failing test**

```js
assert.equal(
  resolveCitationPageImageSource({ courseId: 2, documentId: null, pageNumber: 6, renderUrl: null }),
  null,
)
```

- [x] **Step 2: Run test to verify it fails**

Run: `node --test src/api/__tests__/evidenceRequestGuards.test.js`

Expected: FAIL because `resolveCitationPageImageSource` is not exported.

- [x] **Step 3: Write minimal implementation**

```js
if (renderUrl) return { kind: 'protected', url: renderUrl }
if (courseId != null && courseId !== '') return null
if (documentId == null || documentId === '') return null
return { kind: 'document', documentId, pageNumber }
```

- [x] **Step 4: Run test to verify it passes**

Run: `node --test src/api/__tests__/evidenceRequestGuards.test.js`

Expected: PASS.

### Task 3: Verification

**Files:**
- Verify: `frontend/src/api/__tests__/visualizationRequestGuards.test.js`
- Verify: `frontend/src/api/__tests__/evidenceRequestGuards.test.js`
- Verify: `frontend/src/api/__tests__/apiContracts.test.cjs`

- [x] **Step 1: Run targeted regression and route-contract tests**

Run: `node --test src/api/__tests__/visualizationRequestGuards.test.js src/api/__tests__/evidenceRequestGuards.test.js src/api/__tests__/apiContracts.test.cjs`

Expected: PASS with the invalid `on_...` filter omitted and a course citation lacking `renderUrl` unable to invoke evidence-v2.

- [x] **Step 2: Build the frontend**

Run: `npm.cmd run build`

Expected: Vite production build completes successfully.
