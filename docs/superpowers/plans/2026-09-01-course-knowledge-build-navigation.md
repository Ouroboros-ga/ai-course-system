# Course Knowledge Build Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将教师端“知识”从课程顶部独立二级入口收敛为课程建设流程的一步，同时保留原有独立知识工作区和学生侧知识入口。

**Architecture:** 只调整 Vue 路由与导航视图模型，不复制、不嵌套、不重写 `KnowledgeLayout`。教师从 `BuildLayout` 的“知识”步骤跨布局跳转到 `/app/course/:courseId/knowledge/`；`CourseLayout` 对有 `course.edit` 能力的用户隐藏顶部“知识”，并把知识路径归入顶部“建设”的激活与返回语义。旧 `/build/drafts` 保留路由名但重定向至知识空间，题库审核服务与页面代码暂不删除。

**Tech Stack:** Vue 3、Vue Router、Node.js `node:test` 源码契约测试、Vite。

## Global Constraints

- 权限判断只使用 `courseContext.allowed['course.edit']`，不使用全局用户角色。
- 教师/课程所有者/有 `course.edit` 的助教不再看到顶部独立“知识”入口；无建设权限的学生仍保留顶部“知识”入口。
- 建设步骤固定为：课程资料 → 课程结构 → 知识 → 讲授脚本 → 教学 PPT 映射 → 媒体与数字人 → 检查 → 正式发布。
- 点击建设侧栏“知识”直接进入 `/app/course/:courseId/knowledge/`，卸载 `BuildLayout` 并进入既有 `KnowledgeLayout`。
- 知识空间既有 5 个教师功能保持不变：结构视图、原文引用、知识包审批、节点审核、版本记录。
- 不删除题库草稿审核后端、API 或数据模型；旧 `/build/drafts` 只做兼容重定向。
- 不修改课程发布版本、知识数据、后端 API、数据库或线上服务器状态。

---

## File Structure

- Modify: `frontend/src/app/pages/course/build/BuildLayout.vue` — 建设步骤顺序、跨布局目标地址与显示文案。
- Modify: `frontend/src/app/pages/course/CourseLayout.vue` — 顶部知识入口的能力分流、激活态和返回目标。
- Modify: `frontend/src/app/router.js` — 将旧题库审核地址改为兼容重定向。
- Modify: `frontend/src/api/__tests__/courseBuildContracts.test.cjs` — 锁定建设侧栏的新步骤顺序与目标。
- Modify: `frontend/src/api/__tests__/apiContracts.test.cjs` — 锁定角色导航、激活态、返回目标和旧路由兼容。
- Modify: `page-design.md` — 更新课程 L2 与教师建设 Local Rail 的现行信息架构。
- Modify: `design.md` — 更新建设路由/跨布局步骤和返回行为说明。
- Modify: `README.md` — 将教师 8 步工作台说明同步为包含知识治理、不再包含题库审核入口。
- Modify: `docs/phase1/功能现状审计表.md` — 记录题库审核入口下线但能力保留、知识入口重排的代码证据。
- Keep unchanged: `frontend/src/app/pages/course/knowledge/KnowledgeLayout.vue` 及其 5 个子页面。
- Keep unchanged: `frontend/src/app/pages/course/build/QuestionDraftReviewPage.vue` 及题库审核后端能力。

---

### Task 1: Lock the navigation contract with failing tests

**Files:**
- Modify: `frontend/src/api/__tests__/courseBuildContracts.test.cjs`
- Modify: `frontend/src/api/__tests__/apiContracts.test.cjs`

**Interfaces:**
- Consumes: `BuildLayout.vue` 的 `steps`/链接渲染，`CourseLayout.vue` 的 `navItems`/`activeKey`/`backTarget`，`router.js` 的课程子路由。
- Produces: 新信息架构的回归契约，后续实现必须使其通过。

- [ ] **Step 1: Add a failing construction-rail contract**

在 `courseBuildContracts.test.cjs` 增加断言，要求：

```js
test('course builder places knowledge governance after structure and removes the question-draft rail entry', () => {
  const layout = read('frontend/src/app/pages/course/build/BuildLayout.vue')
  const structureAt = layout.indexOf("key: 'structure'")
  const knowledgeAt = layout.indexOf("key: 'knowledge'")
  const scriptsAt = layout.indexOf("key: 'scripts'")

  assert.ok(structureAt >= 0 && knowledgeAt > structureAt && scriptsAt > knowledgeAt)
  assert.match(layout, /key:\s*['"]knowledge['"][\s\S]*?to:\s*`\/app\/course\/\$\{courseId\.value\}\/knowledge\/`/)
  assert.match(layout, /:to="step\.to"/)
  assert.doesNotMatch(layout, /key:\s*['"]drafts['"]|题库草稿审核/)
})
```

- [ ] **Step 2: Add failing course-navigation and compatibility contracts**

在 `apiContracts.test.cjs` 替换当前“始终启用知识导航”断言，锁定以下行为：

```js
test('CourseLayout.vue: builders enter knowledge through construction while learners retain the knowledge tab', () => {
  const src = read('frontend/src/app/pages/course/CourseLayout.vue')
  assert.match(src, /if\s*\(!allowed\.value\[['"]course\.edit['"]\]\)[\s\S]*?key:\s*['"]knowledge['"]/)
  assert.match(src, /route\.path\.includes\(['"]\/knowledge['"]\)[\s\S]*?allowed\.value\[['"]course\.edit['"]\][\s\S]*?['"]build['"][\s\S]*?['"]knowledge['"]/)
  assert.match(src, /route\.path\.includes\(['"]\/knowledge['"]\)[\s\S]*?allowed\.value\[['"]course\.edit['"]\]/)
})

test('router.js: the retired build drafts address redirects to the knowledge workspace', () => {
  const src = read('frontend/src/app/router.js')
  assert.match(src, /path:\s*['"]drafts['"][\s\S]*?name:\s*['"]app-course-build-drafts['"][\s\S]*?redirect:[\s\S]*?\/knowledge\//)
  assert.doesNotMatch(src, /path:\s*['"]drafts['"][\s\S]*?QuestionDraftReviewPage\.vue/)
})
```

- [ ] **Step 3: Run the focused tests and confirm the expected RED state**

Run:

```powershell
node --test frontend/src/api/__tests__/courseBuildContracts.test.cjs frontend/src/api/__tests__/apiContracts.test.cjs
```

Expected: the newly added navigation tests fail because `BuildLayout` still contains `drafts`, the teacher navigation still exposes `knowledge`, and the old route still renders `QuestionDraftReviewPage`.

---

### Task 2: Implement the cross-layout construction step

**Files:**
- Modify: `frontend/src/app/pages/course/build/BuildLayout.vue`
- Modify: `frontend/src/app/pages/course/CourseLayout.vue`
- Modify: `frontend/src/app/router.js`

**Interfaces:**
- Consumes: `courseId`, Course Access v1 的 `allowed['course.edit']`、现有 `/knowledge` 子路由。
- Produces: `steps[].to: string`；教师知识路径映射为顶部 `build` 激活态；旧题库地址重定向。

- [ ] **Step 1: Make every build step own its target URL**

将 `BuildLayout.vue` 的 `steps` 改为 `computed`，每一项显式提供 `to`，并把“知识”放在“课程结构”和“讲授脚本”之间：

```js
const steps = computed(() => [
  { key: 'materials', label: '课程资料', description: '上传并解析教学材料', icon: FileText, to: `/app/course/${courseId.value}/build/materials` },
  { key: 'structure', label: '课程结构', description: '组织目录与教学顺序', icon: ListTree, to: `/app/course/${courseId.value}/build/structure` },
  { key: 'knowledge', label: '知识', description: '审核知识结构与原文依据', icon: Network, to: `/app/course/${courseId.value}/knowledge/` },
  { key: 'scripts', label: '讲授脚本', description: '完善教学表达', icon: BookOpenCheck, to: `/app/course/${courseId.value}/build/scripts` },
  { key: 'mapping', label: '教学 PPT 映射', description: '关联教学演示页', icon: MonitorPlay, to: `/app/course/${courseId.value}/build/mapping` },
  { key: 'media', label: '媒体与数字人', description: '准备课堂媒体', icon: Video, to: `/app/course/${courseId.value}/build/media` },
  { key: 'validate', label: '检查', description: '查看正式发布前的问题', icon: ShieldCheck, to: `/app/course/${courseId.value}/build/validate` },
  { key: 'releases', label: '正式发布', description: '让学生看到这版课程内容', icon: Waypoints, to: `/app/course/${courseId.value}/build/releases` },
])
```

模板链接改为：

```vue
<RouterLink :to="step.to" ...>
```

`activeStep` 改为读取 `steps.value`。不要为知识页在 `BuildLayout` 中增加占位组件或嵌套 `router-view`。

- [ ] **Step 2: Split the course L2 navigation by course capability**

在 `CourseLayout.vue` 中只对没有 `course.edit` 能力的成员加入顶部“知识”项：

```js
if (!allowed.value['course.edit']) {
  base.push({
    key: 'knowledge',
    label: '知识',
    to: `/app/course/${courseId.value}/knowledge`,
    enabled: true,
  })
}
```

把实验任务、科研等后续条目在这一分支之后继续追加，保证学生导航顺序仍为“学习分析 → 知识 → 实验任务”。教师只保留“建设”，不再出现独立“知识”。

- [ ] **Step 3: Preserve construction context on the independent knowledge layout**

调整 `activeKey`：

```js
if (route.path.includes('/knowledge')) {
  return allowed.value['course.edit'] ? 'build' : 'knowledge'
}
```

调整 `backTarget`：

```js
if (
  route.path.includes('/build')
  || (route.path.includes('/knowledge') && allowed.value['course.edit'])
) return '/app/courses/building'
```

这样教师进入独立知识布局后，顶部仍明确显示自己处于建设流程；学生知识页保持原有知识激活态与“我学习的”返回目标。

- [ ] **Step 4: Redirect the retired question-draft URL**

保留旧路由名，取消页面组件加载：

```js
{
  path: 'drafts',
  name: 'app-course-build-drafts',
  redirect: (to) => `/app/course/${to.params.courseId}/knowledge/`,
},
```

不删除 `QuestionDraftReviewPage.vue`、`question_bank.js` 或后端题库审核 API；它们属于功能能力保留，只是不再作为课程建设 Local Rail 的产品入口。

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run:

```powershell
node --test frontend/src/api/__tests__/courseBuildContracts.test.cjs frontend/src/api/__tests__/apiContracts.test.cjs
```

Expected: both files pass with zero failures.

---

### Task 3: Synchronize the current architecture documentation

**Files:**
- Modify: `page-design.md`
- Modify: `design.md`
- Modify: `README.md`
- Modify: `docs/phase1/功能现状审计表.md`

**Interfaces:**
- Consumes: Task 2 的最终路由和能力分流。
- Produces: 与代码一致的教师/学生导航、建设步骤和兼容语义。

- [ ] **Step 1: Update the information architecture authority**

在 `page-design.md` 同步：

```text
学生：概览｜学习｜知识｜实验任务｜科研
教师：概览｜学习｜建设｜实验任务｜科研｜成员｜设置

建设 Local Rail：
课程资料 → 课程结构 → 知识 → 讲授脚本 → 教学 PPT 映射
→ 媒体与数字人 → 检查 → 正式发布
```

注明“知识”是跨布局步骤：点击后进入独立 `KnowledgeLayout`，其内部 Local Rail 不合并进 `BuildLayout`。

- [ ] **Step 2: Update visual routing facts without changing visual tokens**

在 `design.md` 的路由与建设布局章节补充：

- `/knowledge/*` 对建设者在顶部映射为“建设”激活态；
- 学生仍将 `/knowledge/*` 映射为“知识”激活态；
- 建设侧栏允许一个跨布局步骤，目标为 `/knowledge/`；
- 教师知识页返回“我建设的”，学生知识页返回“我学习的”；
- 旧 `/build/drafts` 是重定向兼容地址，不是可见入口。

- [ ] **Step 3: Update current status and audit evidence**

在 `README.md` 将“教师 8 步生产工作台”描述补充为“包含独立知识治理步骤”；在 `docs/phase1/功能现状审计表.md` 记录：

- 变更日期：2026-09-01；
- 变化原因：题库草稿审核不再属于教师日常课程建设主线，知识治理需要在脚本/媒体/发布前成为显式步骤；
- 代码证据：`BuildLayout.vue`、`CourseLayout.vue`、`router.js`；
- 保留边界：题库审核 API/页面代码未删除，旧 URL 重定向，不影响题库审批数据。

- [ ] **Step 4: Scan for stale current-state claims**

Run:

```powershell
rg -n "教师.*知识|题库草稿审核|build/drafts|七步建设|8 步生产工作台" README.md page-design.md design.md docs/phase1/功能现状审计表.md docs/phase1/统一课程建设与解析基线.md
```

Expected: 现行文档不再把题库草稿审核列为可见建设步骤；历史决策文档可以保留，但不得被改写为当前实现证据。

---

### Task 4: Verify, review, commit, rebase, and push

**Files:**
- Verify all modified files from Tasks 1–3.

**Interfaces:**
- Consumes: 完整前端导航改动与文档同步。
- Produces: 可构建、可回归、已正常推送的 `feature/xh202620` 提交。

- [ ] **Step 1: Run focused contract tests**

```powershell
node --test frontend/src/api/__tests__/courseBuildContracts.test.cjs frontend/src/api/__tests__/apiContracts.test.cjs
```

Expected: zero failures.

- [ ] **Step 2: Run the production frontend build**

```powershell
pnpm --dir frontend build
```

Expected: Vite exits with code 0. Generated `frontend/dist` files are verification artifacts and must not be staged unless already tracked and intentionally versioned by repository policy.

- [ ] **Step 3: Inspect the final diff for scope and generated artifacts**

```powershell
git status --short
git diff --check
git diff -- frontend/src/app/pages/course/build/BuildLayout.vue frontend/src/app/pages/course/CourseLayout.vue frontend/src/app/router.js frontend/src/api/__tests__/courseBuildContracts.test.cjs frontend/src/api/__tests__/apiContracts.test.cjs page-design.md design.md README.md docs/phase1/功能现状审计表.md
```

Expected: only the planned navigation/tests/docs are present; no secrets, dependency changes, unrelated user files, or generated bundles are staged.

- [ ] **Step 4: Commit the scoped change**

Stage the files by explicit path and commit:

```powershell
git add frontend/src/app/pages/course/build/BuildLayout.vue
git add frontend/src/app/pages/course/CourseLayout.vue
git add frontend/src/app/router.js
git add frontend/src/api/__tests__/courseBuildContracts.test.cjs
git add frontend/src/api/__tests__/apiContracts.test.cjs
git add page-design.md design.md README.md docs/phase1/功能现状审计表.md
git commit -m "refactor(course): move knowledge into build workflow"
```

- [ ] **Step 5: Rebase onto the latest remote branch without force**

```powershell
git fetch origin
git rebase origin/feature/xh202620
```

If a conflict occurs, resolve only the listed scope, rerun Steps 1–3, and do not use `git push --force`.

- [ ] **Step 6: Push normally and verify the remote SHA**

```powershell
git push origin feature/xh202620
git fetch origin
git rev-parse HEAD
git rev-parse origin/feature/xh202620
```

Expected: both SHA values are identical. This task does not deploy to `47.99.97.154` or run remote migrations/restarts.

---

## Acceptance Checklist

- [ ] 教师顶部课程导航不再显示独立“知识”。
- [ ] 学生顶部课程导航仍显示“知识”。
- [ ] 建设侧栏没有“题库草稿审核”。
- [ ] 建设侧栏第 03 步是“知识”，位于“课程结构”和“讲授脚本”之间。
- [ ] 点击“知识”后 URL 进入 `/app/course/:courseId/knowledge/graph`，页面使用独立 `KnowledgeLayout`。
- [ ] 知识空间的 5 个教师功能和已有数据保持不变。
- [ ] 教师在知识页看到顶部“建设”为激活态，返回按钮去“我建设的”。
- [ ] 学生在知识页看到顶部“知识”为激活态，返回按钮去“我学习的”。
- [ ] 直接访问旧 `/app/course/:courseId/build/drafts` 会进入知识空间，不显示废弃审核页。
- [ ] 题库草稿审核后端能力和数据未删除。
- [ ] 自动化测试与 production build 的实际结果被如实记录。
- [ ] 只普通推送，不 force push；不部署线上。
