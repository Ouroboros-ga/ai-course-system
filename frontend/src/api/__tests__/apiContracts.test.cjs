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

test('cognitive.js: getCognitiveState 调用 /state?student_id=（不是 /students/{id}/state）', () => {
  const src = read('frontend/src/api/cognitive.js')
  const p = extractFirstPath(src, 'getCognitiveState')
  assert.equal(p, '/cognitive/course/${courseId}/state')
  assert.doesNotMatch(p, /\/students\//)
  // 必须通过 params 传递 student_id
  assert.match(src, /params:\s*\{\s*student_id:\s*studentId\s*\}/)
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
  assert.match(src, /v-for="plan in publishedPlans"[\s\S]*?:key="plan\.plan_id"/)
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

test('router.js: 注册 /app/course/:courseId/knowledge/:nodeId? 路由', () => {
  const src = read('frontend/src/app/router.js')
  // 必须注册 knowledge 路由（含可选 nodeId）
  assert.match(src, /path:\s*['"]knowledge\/:nodeId\?['"]/)
  assert.match(src, /name:\s*['"]app-course-knowledge['"]/)
  // 必须指向 KnowledgeSpacePage
  assert.match(src, /KnowledgeSpacePage\.vue/)
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

test('KnowledgeSpacePage.vue: 集成 StudentGraphPanel + CognitiveDashboard + RecommendationCard', () => {
  const src = read('frontend/src/app/pages/course/KnowledgeSpacePage.vue')
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
