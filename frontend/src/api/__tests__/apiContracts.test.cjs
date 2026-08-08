/**
 * P0 前端 API 契约测试（批次3/4）
 *
 * 目的：锁定 frontend/src/api/{graph,cognitive,visualization}.js 中每个函数
 *       生成的 URL 路径与方法，与 backend/app/api/v1/endpoints/ 中真实注册
 *       的 FastAPI 路由一一对应，避免前端调用 404。
 *
 * 设计：
 * - 不依赖运行时 mock，直接读取 API client 源码做正则契约锁定；
 * - 同时读取后端路由文件，验证对应路由确实注册；
 * - 任一端漂移即测试失败。
 *
 * 运行：node --test frontend/src/api/__tests__/apiContracts.test.cjs
 */
const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..', '..', '..', '..')
const FRONTEND_API = path.join(ROOT, 'frontend', 'src', 'api')
const BACKEND_EP = path.join(ROOT, 'backend', 'app', 'api', 'v1', 'endpoints')

test('avatar.js: uploadAvatarSourceMedia 分支支持 PUT 与 presigned POST fields', () => {
  const src = read('frontend/src/api/avatar.js')
  assert.match(src, /const method = String\(options\.method \|\| ['"]PUT['"]\)\.toUpperCase\(\)/)
  assert.match(src, /if \(method === ['"]POST['"]\)/)
  assert.match(src, /Object\.entries\(options\.fields \|\| \{\}\)/)
  assert.match(src, /form\.append\(['"]file['"], file\)/)
  assert.match(src, /request\.put\(relativeUrl, file/)
})

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8')
}

/** 从源码中提取某个函数体内的第一个 request 调用 URL 模板。
 *  支持反引号模板字符串与单引号字符串；支持默认参数中的花括号。 */
function extractFirstPath(src, fnName) {
  // 用 [^)]* 匹配参数列表（允许花括号出现，因为默认值如 payload = {} 不含括号）
  const re = new RegExp(
    `function\\s+${fnName}\\s*\\([^)]*\\)\\s*\\{[\\s\\S]*?(['\\\`'])([^'\\\`]+)\\1`,
  )
  const m = src.match(re)
  assert.ok(m, `未在源码中找到函数 ${fnName} 的路径模板字符串`)
  return m[2]
}

test('courses.js: deleteCourse 使用 DELETE body 精确确认课程名称', () => {
  const src = read('frontend/src/api/courses.js')
  const p = extractFirstPath(src, 'deleteCourse')
  assert.equal(p, '/document/course/${courseId}')
  assert.match(src, /function deleteCourse[\s\S]*?request\.delete[\s\S]*?confirmation_title:\s*confirmationTitle/)
})

test('SettingsProfilePage.vue: 删除入口由课程 owner 权限共同控制', () => {
  const src = read('frontend/src/app/pages/course/settings/SettingsProfilePage.vue')
  assert.match(src, /courseContext\.courseRole\.value\s*===\s*['"]owner['"]/)
  assert.match(src, /courseContext\.allowed\.value\?\.\[['"]course\.delete['"]\]/)
  assert.match(src, /v-if="canDelete"/)
  assert.doesNotMatch(src, /localStorage\.getItem\(['"]userRole['"]\)/)
})

// ============================================================================
// graph.js ↔ graph_production.py 契约
// ============================================================================

test('graph.js: getCourseSnapshot 调用 GET /graph/course/{courseId}/snapshot', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'getCourseSnapshot')
  assert.equal(p, '/graph/course/${courseId}/snapshot')
})

test('graph.js: getNodePrerequisites 调用 prerequisites（不是 neighbors）', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'getNodePrerequisites')
  assert.equal(p, '/graph/course/${courseId}/nodes/${nodeId}/prerequisites')
  // 关键防回归：禁止再使用 neighbors
  assert.doesNotMatch(p, /\/neighbors\b/)
})

test('graph.js: transitionReview 调用 reviews/{id}/transition（不是 candidates/{id}/transition）', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'transitionReview')
  assert.equal(p, '/graph/course/${courseId}/reviews/${reviewId}/transition')
  assert.doesNotMatch(p, /\/candidates\//)
})

test('graph.js: publishSnapshot 调用 /publish（不是 /snapshots/publish）', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'publishSnapshot')
  assert.equal(p, '/graph/course/${courseId}/publish')
  assert.doesNotMatch(p, /\/snapshots\/publish/)
})

test('graph.js: rollbackSnapshot 调用 /rollback/{snapshotId}（不是 /snapshots/{id}/rollback）', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'rollbackSnapshot')
  assert.equal(p, '/graph/course/${courseId}/rollback/${snapshotId}')
  assert.doesNotMatch(p, /\/snapshots\/[^$]+\}\/rollback/)
})

test('graph.js: markEvidenceStale 调用 /mark-stale（不是 /evidence/{id}/stale）', () => {
  const src = read('frontend/src/api/graph.js')
  const p = extractFirstPath(src, 'markEvidenceStale')
  assert.equal(p, '/graph/course/${courseId}/mark-stale')
  assert.doesNotMatch(p, /\/evidence\/[^$]+\}\/stale/)
})

test('backend: graph_production.py 注册所有对应路由', () => {
  const src = read('backend/app/api/v1/endpoints/graph_production.py')
  assert.match(src, /@router\.get\(["']\/course\/\{course_id\}\/snapshot["']\)/)
  assert.match(src, /@router\.get\(["']\/course\/\{course_id\}\/nodes\/\{node_id\}\/prerequisites["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/reviews\/\{review_id\}\/transition["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/publish["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/rollback\/\{snapshot_id\}["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/mark-stale["']\)/)
})

// ============================================================================
// cognitive.js ↔ cognitive_recommendation.py 契约
// ============================================================================

test('cognitive.js: getCognitiveState 调用 /state，并按需传 student_id/node_id', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'getCognitiveState')
  assert.equal(p, '/cognitive/course/${courseId}/state')
  assert.doesNotMatch(p, /\/students\//)
  // 学生视角可省略 student_id，由 JWT 决定；教师/节点详情可显式传入两个查询参数。
  assert.match(src, /const params = \{\}/)
  assert.match(src, /if \(studentId != null\) params\.student_id = studentId/)
  assert.match(src, /if \(nodeId != null\) params\.node_id = nodeId/)
})

test('LearningTrack.vue: 学习轨道公开双层状态、详情入口与知识依据跳转事件', () => {
  const src = read('frontend/src/app/components/learn/LearningTrack.vue')
  assert.match(src, /已掌握/)
  assert.match(src, /待掌握/)
  assert.match(src, /未学习/)
  assert.match(src, /学习中/)
  assert.match(src, /需要更多证据/)
  assert.match(src, /认知暂不可用/)
  assert.match(src, /暂不可分析/)
  assert.match(src, /emit\(\s*['"]inspect['"]\s*,\s*node\.outlineNodeId/)
  assert.match(src, /emit\(\s*['"]open-knowledge['"]\s*,\s*knowledgeNodeId\(node\)/)
  assert.match(src, /:title="`\$\{displayState\(node\)\.label\}/)
  assert.match(src, /evidence_count|sample_size/)
  assert.match(src, /cognition\?\.node_key/)
})

test('LearnPage.vue: 学习轨道可进入当前知识点的知识图谱依据', () => {
  const src = read('frontend/src/app/pages/learn/LearnPage.vue')
  assert.match(src, /useRouter\(\)/)
  assert.match(src, /knowledge\/graph\//)
  assert.match(src, /@open-knowledge="handleOpenKnowledge"/)
})

test('LearnPage.vue: 推荐动作复用 PracticePanel 并消费推荐', () => {
  const page = read('frontend/src/app/pages/learn/LearnPage.vue')
  const track = read('frontend/src/app/components/learn/LearningTrack.vue')
  assert.match(page, /consumeRecommendation/)
  assert.match(page, /recommendation_consumed/)
  assert.match(page, /handleDockAction\(\{ id: 'practice'/)
  assert.match(track, /recommendation-action/)
  assert.match(track, /去练习/)
})

test('cognitive.js: computeCognitiveState 调用 /compute（不是 /students/{id}/compute）', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'computeCognitiveState')
  assert.equal(p, '/cognitive/course/${courseId}/compute')
  assert.doesNotMatch(p, /\/students\//)
})

test('cognitive.js: generateRecommendation 调用 /recommend（不是 /recommendations/generate）', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'generateRecommendation')
  assert.equal(p, '/cognitive/course/${courseId}/recommend')
  assert.doesNotMatch(p, /\/recommendations\/generate/)
})

test('cognitive.js: consumeRecommendation 使用单数 /recommendation/{id}/consume', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'consumeRecommendation')
  assert.equal(p, '/cognitive/recommendation/${recommendationId}/consume')
  assert.doesNotMatch(p, /\/recommendations\//)
})

test('cognitive.js: lockRecommendation 使用单数 /recommendation/{id}/lock', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'lockRecommendation')
  assert.equal(p, '/cognitive/recommendation/${recommendationId}/lock')
})

test('cognitive.js: unlockRecommendation 使用单数 /recommendation/{id}/unlock', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'unlockRecommendation')
  assert.equal(p, '/cognitive/recommendation/${recommendationId}/unlock')
})

test('backend: cognitive_recommendation.py 注册所有对应路由', () => {
  const src = read('backend/app/api/v1/endpoints/cognitive_recommendation.py')
  assert.match(src, /@router\.get\(["']\/course\/\{course_id\}\/state["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/compute["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/recommend["']\)/)
  assert.match(src, /@router\.get\(["']\/course\/\{course_id\}\/recommendations["']\)/)
  assert.match(src, /@router\.post\(["']\/recommendation\/\{recommendation_id\}\/consume["']\)/)
  assert.match(src, /@router\.post\(["']\/recommendation\/\{recommendation_id\}\/lock["']\)/)
  assert.match(src, /@router\.post\(["']\/recommendation\/\{recommendation_id\}\/unlock["']\)/)
})

// ============================================================================
// visualization.js ↔ visualization.py 契约
// ============================================================================

test('visualization.js: listAlgorithms 调用 /visualization/algorithms', () => {
  const src = read('frontend/src/api/visualization.js')
  const p = extractFirstPath(src, 'listAlgorithms')
  assert.equal(p, '/visualization/algorithms')
})

test('visualization.js: createPlan 调用 POST /visualization/course/{courseId}/plan', () => {
  const src = read('frontend/src/api/visualization.js')
  const p = extractFirstPath(src, 'createPlan')
  assert.equal(p, '/visualization/course/${courseId}/plan')
})

test('visualization.js: listPlans 调用 GET /visualization/course/{courseId}/plans', () => {
  const src = read('frontend/src/api/visualization.js')
  const p = extractFirstPath(src, 'listPlans')
  assert.equal(p, '/visualization/course/${courseId}/plans')
})

test('visualization.js: getPlan 调用 GET /visualization/{planId}', () => {
  const src = read('frontend/src/api/visualization.js')
  const p = extractFirstPath(src, 'getPlan')
  assert.equal(p, '/visualization/${planId}')
})

test('visualization.js: publishPlan 调用 POST /visualization/course/{courseId}/{planId}/publish', () => {
  const src = read('frontend/src/api/visualization.js')
  const p = extractFirstPath(src, 'publishPlan')
  assert.equal(p, '/visualization/course/${courseId}/${planId}/publish')
})

test('backend: visualization.py 注册所有对应路由', () => {
  const src = read('backend/app/api/v1/endpoints/visualization.py')
  assert.match(src, /@router\.get\(["']\/algorithms["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/plan["']\)/)
  assert.match(src, /@router\.get\(["']\/course\/\{course_id\}\/plans["']\)/)
  assert.match(src, /@router\.get\(["']\/\{plan_id\}["']\)/)
  assert.match(src, /@router\.post\(["']\/course\/\{course_id\}\/\{plan_id\}\/publish["']\)/)
})

test('visualization.py: _serialize_plan 同时返回 id 和 plan_id（前端必须使用 plan_id）', () => {
  const src = read('backend/app/api/v1/endpoints/visualization.py')
  // 后端确实同时返回两种 ID
  assert.match(src, /["']id["']:\s*record\.id/)
  assert.match(src, /["']plan_id["']:\s*record\.plan_id/)
  // get_plan 按 plan_id 查询（不是数据库行 id）
  const getPlanMatch = src.match(/async def get_plan[\s\S]*?select\(VisualizationPlanRecord\)\.where\(\s*VisualizationPlanRecord\.(\w+)\s*==\s*plan_id/)
  assert.ok(getPlanMatch, 'get_plan 必须按 plan_id 查询')
  assert.equal(getPlanMatch[1], 'plan_id', 'get_plan 必须按 plan_id（UUID）查询，不能按数据库行 id')
  // publish_plan 同样按 plan_id 查询
  const publishMatch = src.match(/async def publish_plan[\s\S]*?select\(VisualizationPlanRecord\)\.where\(\s*VisualizationPlanRecord\.(\w+)\s*==\s*plan_id/)
  assert.ok(publishMatch, 'publish_plan 必须按 plan_id 查询')
  assert.equal(publishMatch[1], 'plan_id', 'publish_plan 必须按 plan_id（UUID）查询')
})

// ============================================================================
// 前端组件使用 plan_id（UUID）而非 id（数据库行）契约
// ============================================================================

test('VisualizationView.vue: playPlan/publishOne 使用 plan.plan_id（不是 plan.id）', () => {
  const src = read('frontend/src/views/VisualizationView.vue')
  // playPlan 必须使用 plan.plan_id 调用 getPlan
  // 注意：if 条件中可能包含 || 短路（如 || publishingId.value），故 [^)]* 允许任意非 ) 字符
  assert.match(src, /async function playPlan[\s\S]*?if \(!plan\?\.plan_id[^)]*\)[\s\S]*?await getPlan\(plan\.plan_id\)/)
  // publishOne 必须使用 plan.plan_id
  assert.match(src, /async function publishOne[\s\S]*?if \(!plan\?\.plan_id[^)]*\)[\s\S]*?publishingId\.value\s*=\s*plan\.plan_id[\s\S]*?await publishPlan\(courseId\.value,\s*plan\.plan_id\)/)
  // 列表 :key 必须使用 plan.plan_id
  assert.match(src, /v-for="plan in filteredPlans"[\s\S]*?:key="plan\.plan_id"/)
  // 禁止使用 plan.id 调用 API（防回归）
  assert.doesNotMatch(src, /await getPlan\(plan\.id\)/)
  assert.doesNotMatch(src, /await publishPlan\(courseId\.value,\s*plan\.id\)/)
})

test('VisualizationStage.vue: playPlan 使用 plan.plan_id（不是 plan.id）', () => {
  const src = read('frontend/src/app/components/learn/VisualizationStage.vue')
  assert.match(src, /async function playPlan[\s\S]*?if \(!plan\?\.plan_id[^)]*\)[\s\S]*?await getPlan\(plan\.plan_id\)/)
  assert.match(src, /v-for="plan in visiblePlans"[\s\S]*?:key="plan\.plan_id"/)
  // 禁止使用 plan.id 调用 API（防回归）
  assert.doesNotMatch(src, /await getPlan\(plan\.id\)/)
})

// ============================================================================
// P1-1: CognitiveDashboard.vue 六维 null 语义契约
// ============================================================================

test('CognitiveDashboard.vue: 保留 null 语义，禁止 Number(null)=0 与默认 confidence=1', () => {
  const src = read('frontend/src/components/cognitive/CognitiveDashboard.vue')
  // 禁止 Number(raw?.value ?? raw) 这种会把 null 强制为 0 的写法
  assert.doesNotMatch(src, /Number\(raw\?\.value \?\? raw\)/)
  // 禁止默认 confidence=1（会把「未知」误报成「100% 置信」）
  assert.doesNotMatch(src, /raw\?\.confidence \?\? raw\?\.confidence_score \?\? 1/)
  // 必须显式保留 null：value 与 confidence 为 null 时不再强制转数值
  assert.match(src, /rawValue == null \|\| rawValue === '' \? null : Number\(rawValue\)/)
  assert.match(src, /rawConfidence == null \|\| rawConfidence === ''/)
  // insufficient 必须在 value/confidence 缺失时为 true（注意：实际代码使用 = 而非 :）
  // 代码跨多行：abstain || \n value == null，需用 [\s\S]*? 允许换行
  assert.match(src, /insufficient\s*=\s*abstain \|\|[\s\S]*?value == null/)
  // confidence == null 与 !Number.isFinite(confidence) 也跨行，用 \s+ 允许换行+缩进
  assert.match(src, /confidence == null \|\|\s+!Number\.isFinite\(confidence\)/)
})

// ============================================================================
// P1-2: StudentGraphPanel.vue 快照字段契约（relations，不是 edges）
// ============================================================================

test('StudentGraphPanel.vue: 快照使用 relations/relation_count（不是 edges）', () => {
  const src = read('frontend/src/features/student-graph/StudentGraphPanel.vue')
  // 禁止读取 snapshot.edges
  assert.doesNotMatch(src, /snapshot\.value\.edges/)
  // 必须读取 snapshot.relations（优先）或 relation_count（兜底）
  assert.match(src, /snapshot\.value\.relations/)
  assert.match(src, /snapshot\.value\.relation_count/)
})

test('StudentGraphPanel.vue: 快照不读取 policy_version（policy_version 属于推荐上下文）', () => {
  const src = read('frontend/src/features/student-graph/StudentGraphPanel.vue')
  // 快照元信息中禁止读取 snapshot.value.policy_version（后端 GraphSnapshot 不含此字段）
  // 注意：recommendationContext.policy_version 是合法的，不算违规
  // 这里只检查对 snapshot.value 的 policy_version 属性访问
  const snapshotMetaMatch = src.match(/const snapshotMeta = computed\(\(\) => \{[\s\S]*?\}\)/)
  assert.ok(snapshotMetaMatch, '必须存在 snapshotMeta computed')
  // 禁止 snapshot.value.policy_version 形式的属性访问
  assert.doesNotMatch(snapshotMetaMatch[0], /snapshot\.value\.policy_version/)
  // snapshotMeta 必须包含 ontology_version 与 snapshot.value.version（快照版本）
  assert.match(snapshotMetaMatch[0], /ontology_version/)
  assert.match(snapshotMetaMatch[0], /snapshot\.value\.version/)
})

test('backend: graph_production_service.py serialize_snapshot 返回 relations 与 version/ontology_version', () => {
  const src = read('backend/app/services/graph_production_service.py')
  // 必须返回 relations（不是 edges）
  assert.match(src, /["']relations["']:\s*snapshot\.relations/)
  // 必须返回 version 与 ontology_version
  assert.match(src, /["']version["']:\s*snapshot\.version/)
  assert.match(src, /["']ontology_version["']:\s*snapshot\.ontology_version/)
  // 必须返回 relation_count
  assert.match(src, /["']relation_count["']:\s*snapshot\.relation_count/)
  // 禁止返回 edges 字段
  assert.doesNotMatch(src, /["']edges["']:\s*snapshot\.edges/)
})

// ============================================================================
// P1-3: 课程知识空间入口契约（路由 + 页面 + 导航）
// ============================================================================

test('router.js: 注册 /app/course/:courseId/knowledge/graph/:nodeId? 路由', () => {
  const src = read('frontend/src/app/router.js')
  // 必须注册 knowledge 结构视图路由（含可选 nodeId）
  assert.match(src, /path:\s*['"]graph\/:nodeId\?['"]/)
  assert.match(src, /name:\s*['"]app-course-knowledge['"]/)
  // 必须指向 KnowledgeGraphPage（知识空间 Local Rail 下的结构视图）
  assert.match(src, /knowledge\/KnowledgeGraphPage\.vue/)
  // 知识空间必须具备治理子路由：原文引用 / 候选审核 / 版本记录
  assert.match(src, /knowledge\/KnowledgeEvidencePage\.vue/)
  assert.match(src, /knowledge\/KnowledgeReviewsPage\.vue/)
  assert.match(src, /knowledge\/KnowledgeSnapshotsPage\.vue/)
})

test('CourseLayout.vue: 启用"知识"导航项（不再 disabled）', () => {
  const src = read('frontend/src/app/pages/course/CourseLayout.vue')
  // knowledge 导航项必须 enabled: true（不再 disabled）
  // 同时必须提供 to（指向 /knowledge）
  assert.match(
    src,
    /key:\s*['"]knowledge['"][^}]*label:\s*['"]知识['"][^}]*to:\s*`\/app\/course\/\$\{courseId\.value\}\/knowledge`[^}]*enabled:\s*true/,
  )
  // activeKey 必须识别 knowledge 路径
  assert.match(src, /route\.path\.includes\(['"]\/knowledge['"]\)/)
})

test('KnowledgeGraphPage.vue: 集成 StudentGraphPanel + CognitiveDashboard + RecommendationCard', () => {
  const src = read('frontend/src/app/pages/course/knowledge/KnowledgeGraphPage.vue')
  // 必须集成三块组件
  assert.match(src, /import\s+StudentGraphPanel\s+from\s+['"]@\/features\/student-graph\/StudentGraphPanel\.vue['"]/)
  assert.match(src, /import\s+CognitiveDashboard\s+from\s+['"]@\/components\/cognitive\/CognitiveDashboard\.vue['"]/)
  assert.match(src, /import\s+RecommendationCard\s+from\s+['"]@\/features\/student-learning\/components\/RecommendationCard\.vue['"]/)
  // 必须使用真实 API（不是 mock）
  assert.match(src, /import\s+\{[\s\S]*?consumeRecommendation[\s\S]*?getRecommendations[\s\S]*?\}\s+from\s+['"]@\/api\/cognitive\.js['"]/)
  // 模板必须渲染三个组件
  assert.match(src, /<StudentGraphPanel/)
  assert.match(src, /<CognitiveDashboard/)
  assert.match(src, /<RecommendationCard/)
  // CognitiveDashboard 必须传入 studentId（保留 null 语义）
  assert.match(src, /:student-id="studentId"/)
  // StudentGraphPanel 必须传入 courseId 与 nodeId
  assert.match(src, /:course-id="courseId"[\s\S]*?:node-id="nodeId"/)
})

// ============================================================================
// P1: 知识空间角色分流契约（教师预览不请求学生私有认知/推荐）
// ============================================================================

test('KnowledgeGraphPage.vue: 基于 analyticsEligible 分流，预览视角 studentId=null', () => {
  const src = read('frontend/src/app/pages/course/knowledge/KnowledgeGraphPage.vue')
  // 必须注入 analyticsEligible
  assert.match(src, /inject\(['"]courseContext['"]\)/)
  assert.match(src, /analyticsEligible/)
  // isPreview 必须基于 analyticsEligible（不是全局 role）
  assert.match(src, /isPreview\s*=\s*computed\(\(\)\s*=>\s*!analyticsEligible\.value\)/)
  // 预览视角下 studentId 必须为 null（不传自己的 user_id 给认知面板）
  assert.match(src, /analyticsEligible\.value\s*\?\s*\(counter\.userData\?\.id\s*\?\?\s*null\)\s*:\s*null/)
  // loadRecommendations 必须在预览视角短路
  assert.match(src, /if\s*\(isPreview\.value\s*\|\|\s*studentId\.value\s*==\s*null\)/)
  // 模板必须有 v-if="isPreview" 分支（隐藏学生私有数据）
  assert.match(src, /v-if="isPreview"/)
  assert.match(src, /v-else/)
})

test('backend: course_access_service.py owner analytics_excluded=True', () => {
  const src = read('backend/app/services/course_access_service.py')
  // owner 建为 analytics_excluded=True（预览视角不能查自己的认知状态）
  assert.match(src, /role=CourseRole\.OWNER[\s\S]*?analytics_excluded=True/)
  // _participation_mode 中非学生角色均返回 analytics_eligible=False
  assert.match(src, /def _participation_mode[\s\S]*?if role == CourseRole\.STUDENT and not analytics_excluded/)
})

// ============================================================================
// P1: 可视化页面 Course Access 契约（不再用全局 User.role）
// ============================================================================

test('VisualizationView.vue: 使用 allowed[course.mapping.edit] 而非全局 User.role', () => {
  const src = read('frontend/src/views/VisualizationView.vue')
  // 必须从 courseContext 注入 allowed
  assert.match(src, /inject\(['"]courseContext['"]\)/)
  assert.match(src, /const\s*\{\s*allowed\s*\}\s*=\s*inject\(['"]courseContext['"]\)/)
  // canEditVisualisation 必须基于 allowed['course.mapping.edit']（允许多行与尾逗号）
  assert.match(src, /canEditVisualisation\s*=\s*computed\([\s\S]*?Boolean\(allowed\.value\?\.\[['"]course\.mapping\.edit['"]\]\)[\s\S]*?\)/)
  // 禁止使用全局 counter.userData.role 判断可视化权限
  assert.doesNotMatch(src, /counter\.userData\.role.*mapping|mapping.*counter\.userData\.role/)
  assert.doesNotMatch(src, /isTeacher.*canEdit|canEdit.*isTeacher/)
})

// ============================================================================
// P1: TeachingAgent 受控接入契约（能力开关 + analyticsEligible + V1 回退）
// ============================================================================

test('teaching_agent.js: respondTeachingAgent 调用 POST /teaching-agent/respond', () => {
  const src = read('frontend/src/api/teaching_agent.js')
  // 必须调用 /teaching-agent/respond（不是 /chat/ask 或其他路径）
  assert.match(src, /url:\s*['"]\/teaching-agent\/respond['"]/)
  assert.match(src, /method:\s*['"]post['"]/)
  // 必须传递 student_id/course_id/session_id/message 四个必填字段
  assert.match(src, /student_id:\s*payload\.student_id/)
  assert.match(src, /course_id:\s*payload\.course_id/)
  assert.match(src, /session_id:\s*payload\.session_id/)
  assert.match(src, /message:\s*payload\.message/)
  // 必须使用 allowFlatResponse（后端返回扁平结构，无 code/message 包裹）
  assert.match(src, /allowFlatResponse:\s*true/)
  // 必须默认 skipErrorToast（503 回退 V1 时不弹错误提示）
  assert.match(src, /skipErrorToast:\s*payload\.skipErrorToast\s*\?\?\s*true/)
})

test('teaching_agent.js: 教师代查使用独立 learner-target 契约', () => {
  const src = read('frontend/src/api/teaching_agent.js')
  assert.match(src, /export function respondTeachingAgentForLearner/)
  assert.match(src, /url:\s*['"]\/teaching-agent\/respond-for-learner['"]/)
  assert.match(src, /learner_user_id:\s*payload\.learner_user_id/)
})

test('backend: teaching_agent.py 注册 POST /respond 路由', () => {
  const src = read('backend/app/api/v1/endpoints/teaching_agent.py')
  assert.match(src, /@router\.post\(["']\/respond["']/)
  // 必须校验 course.question.ask 权限（学生自问）
  assert.match(src, /course\.question\.ask/)
  // 必须校验 analytics_eligible（非学生不能请求个人教学响应）
  assert.match(src, /analytics_eligible/)
  // 无运行时时必须返回 503（TEACHING_AGENT_NOT_CONFIGURED）
  assert.match(src, /status_code=503/)
  assert.match(src, /TEACHING_AGENT_NOT_CONFIGURED/)
})

test('backend: main.py 注册 teaching-agent 路由前缀', () => {
  const src = read('backend/app/main.py')
  assert.match(src, /include_router\(teaching_agent\.router,\s*prefix=["']\/api\/v1\/teaching-agent["']/)
})

test('useLearningWorkspace.js: 导入 respondTeachingAgent 并在能力开关保护下调用', () => {
  const src = read('frontend/src/features/student-learning/composables/useLearningWorkspace.js')
  // 必须导入 TeachingAgent API 客户端
  assert.match(src, /import\s+\{\s*respondTeachingAgent\s*\}\s+from\s+['"]@\/api\/teaching_agent\.js['"]/)
  // 必须保留 V1 askQuestion 作为回退
  assert.match(src, /import\s+\{\s*askQuestion\s*\}\s+from\s+['"]@\/api\/chat\.js['"]/)
  // 必须检查 cognitive_analysis 能力开关
  assert.match(src, /capabilities\?\.cognitive_analysis/)
  // 必须检查 analyticsEligible
  assert.match(src, /analyticsEligible/)
  // 必须检查 studentId != null
  assert.match(src, /studentId\s*!=\s*null/)
  // canUseTeachingAgent 必须三重校验
  assert.match(src, /canUseTeachingAgent\s*=\s*Boolean\([\s\S]*?cognitive_analysis[\s\S]*?analyticsEligible[\s\S]*?studentId\s*!=\s*null[\s\S]*?\)/)
  // 失败时必须回退到 askV1
  assert.match(src, /catch\s*\(agentError\)[\s\S]*?askV1/)
  // 不满足条件时直接走 V1
  assert.match(src, /canUseTeachingAgent[\s\S]*?else[\s\S]*?askV1/)
})

test('useLearningWorkspace.js: TeachingAgent 自助调用不再从前端传 student_id', () => {
  const src = read('frontend/src/features/student-learning/composables/useLearningWorkspace.js')
  // learner subject is derived from the authenticated token by the backend
  assert.doesNotMatch(src, /respondTeachingAgent\(\{[\s\S]*?student_id:/)
  assert.match(src, /course_id:\s*String\(course\.value\.courseId\)/)
  assert.match(src, /session_id:\s*teachingSessionId/)
  assert.match(src, /message:\s*question/)
  // teachingSessionId 必须在 workspace 创建时生成
  assert.match(src, /teachingSessionId\s*=/)
})

test('LearnPage.vue: 从 courseContext 注入 analyticsEligible/capabilities 传入 workspace', () => {
  const src = read('frontend/src/app/pages/learn/LearnPage.vue')
  // 必须注入 analyticsEligible 和 capabilities
  assert.match(src, /inject\(['"]courseContext['"]\)/)
  assert.match(src, /analyticsEligible/)
  assert.match(src, /capabilities/)
  // 必须以 getter 形式传入 workspace（不是静态值，因为 courseContext 异步加载）
  assert.match(src, /getStudentId:\s*\(\)\s*=>\s*counter\.userData\?\.id\s*\?\?\s*null/)
  assert.match(src, /getAnalyticsEligible:\s*\(\)\s*=>\s*analyticsEligible\.value/)
  assert.match(src, /getCapabilities:\s*\(\)\s*=>\s*capabilities\.value/)
  // 禁止直接用全局 role 判断是否使用 Agent
  assert.doesNotMatch(src, /isTeacher.*teachingAgent|teachingAgent.*isTeacher/)
})

test('request.js: 支持 skipErrorToast 配置（Agent 503 回退时不弹错误提示）', () => {
  const src = read('frontend/src/utils/request.js')
  // 错误拦截器必须检查 skipErrorToast
  assert.match(src, /skipErrorToast/)
  assert.match(src, /if\s*\(!error\.config\?\.skipErrorToast\)/)
})

// ============================================================================
// P5.1: 平台音色/角色注册表契约
// ============================================================================

test('media_release.js: getPlatformMediaPresets 使用课程级 platform-presets 路径', () => {
  const src = read('frontend/src/api/media_release.js')
  assert.match(src, /export const getPlatformMediaPresets\s*=\s*\(courseId\)\s*=>\s*request\.get\(`\$\{base\(courseId\)\}\/platform-presets`\)/)
})

test('media_release.py: 注册表路由与 media.generate 权限一致', () => {
  const src = read('backend/app/api/v1/endpoints/media_release.py')
  assert.match(src, /@media_release_router\.get\("\/course\/\{course_id\}\/platform-presets"\)/)
  assert.match(src, /get_platform_media_presets[\s\S]*?course\.media\.generate/)
  assert.match(src, /list_public_presets\(session[\s\S]*?effective_provider/)
})

// ============================================================================
// 变更 3: TeachingAgent warning code → 可读文案映射（防回归）
// ============================================================================

test('useLearningWorkspace.js: 将 warning code 映射为可读 fallbackNotice', () => {
  const src = read('frontend/src/features/student-learning/composables/useLearningWorkspace.js')
  // 必须存在 warning → 文案映射表
  assert.match(src, /TEACHING_AGENT_WARNING_NOTICES\s*=\s*\{/)
  // 三个 warning code 都必须有对应文案
  assert.match(src, /COURSE_KNOWLEDGE_GRAPH_PENDING:\s*['"]课程知识图谱正在解析或暂不可用/)
  assert.match(src, /WEB_RESEARCH_PENDING_TEACHER_CONFIRMATION:\s*['"]联网资料检索需教师确认/)
  assert.match(src, /TOOL_LOCKED_BY_TEACHER:\s*['"]该能力已被教师关闭/)
  // 必须透传 warnings 数组（供未来面板展示）
  assert.match(src, /warnings,/)
})

// ============================================================================
// 听课时长埋点：NodeProgress.time_spent 上报契约
// ============================================================================

test('playerWorkspaceAdapter.js: buildProgressPayload 包含 time_spent_delta（上限60）', () => {
  const src = read('frontend/src/features/student-learning/adapters/playerWorkspaceAdapter.js')
  assert.match(src, /time_spent_delta:\s*clamp\(numberOr\(state\.timeSpentDelta/)
})

test('useLearningWorkspace.js: 仅 playing 时累计听课时长并随进度上报', () => {
  const src = read('frontend/src/features/student-learning/composables/useLearningWorkspace.js')
  assert.match(src, /lastProgressSaveAt/)
  assert.match(src, /if\s*\(isPlaying\.value\s*&&\s*lastProgressSaveAt\s*>\s*0\)/)
  assert.match(src, /timeSpentDelta/)
  assert.match(src, /timeSpentDelta,/)
})

test('backend: player.py ProgressSaveRequest 接受 time_spent_delta 并写入 NodeProgress.time_spent', () => {
  const src = read('backend/app/api/v1/endpoints/player.py')
  assert.match(src, /time_spent_delta:\s*float\s*=\s*Field\(default=0\.0/)
  assert.match(src, /NodeProgress\.time_spent/)
})

// ============================================================================
// 提示使用埋点：cognitive_context.hint_used 上报契约
// ============================================================================

test('question_bank.js: submitAttempt 支持 hintUsed 选项', () => {
  const src = read('frontend/src/api/question_bank.js')
  assert.match(src, /hint_used:\s*Boolean\(options\.hintUsed\)/)
})

test('PracticePanel.vue: 查看提示后记 hint_used 并随 attempt 上报', () => {
  const src = read('frontend/src/app/components/learn/PracticePanel.vue')
  assert.match(src, /hintUsed\s*=\s*ref\(false\)/)
  assert.match(src, /function showHint\(\)/)
  assert.match(src, /submitAttempt\(props\.courseId,\s*q\.id,\s*answer,\s*\{\s*hintUsed:\s*hintUsed\.value\s*\}\)/)
})

test('backend: question_bank.py submit_attempt 接受 hint_used 写入 cognitive_context', () => {
  const src = read('backend/app/api/v1/endpoints/question_bank.py')
  assert.match(src, /hint_used:\s*bool\s*=\s*Body\(False/)
  assert.match(src, /cognitive_context=\{"hint_used":\s*bool\(hint_used\)\}/)
})

// ============================================================================
// note.js ↔ note.py 契约（资源库「课程笔记」）
// ============================================================================

test('note.js: listNotes 调用 GET /notes（按课程筛选）', () => {
  const src = read('frontend/src/api/note.js')
  const p = extractFirstPath(src, 'listNotes')
  assert.equal(p, '/notes')
  assert.match(src, /listNotes\(courseId\)[\s\S]*?params:\s*\{\s*course_id:\s*courseId\s*\}/)
})

test('note.js: listNoteSummaries 调用 GET /notes/summary', () => {
  const src = read('frontend/src/api/note.js')
  const p = extractFirstPath(src, 'listNoteSummaries')
  assert.equal(p, '/notes/summary')
})

test('note.js: createNote/updateNote/deleteNote 路由模板与后端一致', () => {
  const src = read('frontend/src/api/note.js')
  assert.equal(extractFirstPath(src, 'createNote'), '/notes')
  assert.equal(extractFirstPath(src, 'updateNote'), '/notes/${noteId}')
  assert.equal(extractFirstPath(src, 'deleteNote'), '/notes/${noteId}')
})

test('backend: note.py 列表返回 items/total 形状（与平台列表惯例一致）', () => {
  const src = read('backend/app/api/v1/endpoints/note.py')
  assert.match(src, /data=\{"items":\s*\[_note_to_dict\(n\) for n in notes\],\s*"total":\s*len\(notes\)\}/)
})

test('backend: note.py 注册 /summary 且位于 /{note_id} 之前（避免路由吞参）', () => {
  const src = read('backend/app/api/v1/endpoints/note.py')
  const summaryIdx = src.indexOf('@router.get("/summary"')
  const detailIdx = src.indexOf('@router.get("/{note_id}"')
  assert.ok(summaryIdx >= 0, 'note.py 未注册 /summary')
  assert.ok(summaryIdx < detailIdx, '/summary 必须注册在 /{note_id} 之前')
  assert.match(src, /func\.count\(Note\.id\)/)
  assert.match(src, /func\.max\(Note\.updated_at\)/)
  assert.match(src, /group_by\(Note\.course_id\)/)
})
