import request from '@/utils/request.js'

/**
 * P2 批次3 认知状态与推荐 API
 *
 * 全部对接真实 V1 端点，响应经 request.js 统一剥离 code/message。
 * 端点前缀：/api/v1/cognitive
 *
 * 数据语义（page-design §6.x）：
 * - 六维认知值：observed_performance_score、evidence_confidence、confusion_risk、
 *   inquiry_depth、hint_dependency、explanation_need；
 * - 数据不足维度后端返回 confidence < 阈值或 abstain=true，前端必须展示
 *   「需要更多证据」，绝不编造数值；
 * - 推荐包含 policy_version、reason_codes、evidence_refs，便于追溯策略版本。
 */

// ---------------------------------------------------------------------------
// 认知状态
// ---------------------------------------------------------------------------

/**
 * 获取学生当前六维认知状态（最近一次计算结果）。
 * GET /cognitive/course/{courseId}/state?student_id={studentId}
 *
 * 后端使用 Query 参数 student_id 接收学生 ID（教师查看他人时必须指定）；
 * 学生查看自己时由后端从 JWT 中提取 user_id。
 *
 * @param {number|string} courseId - 课程 ID
 * @param {number|string} studentId - 学生 ID
 * @returns {Promise<Object>} 认知状态对象（含 dimensions/mastery_level/policy_version）
 */
export function getCognitiveState(courseId, studentId = null, nodeId = null) {
  const params = {}
  if (studentId != null) params.student_id = studentId
  if (nodeId != null) params.node_id = nodeId
  return request.get(
    `/cognitive/course/${courseId}/state`,
    { params },
  )
}

/**
 * 触发后端重新计算认知状态（基于已有学习证据）。
 * POST /cognitive/course/{courseId}/compute
 *
 * 仅课程学习者可生成个人认知状态（后端通过 analytics_eligible 校验）。
 * 学生 ID 由后端从 JWT 中提取，不接受前端传入。
 *
 * @param {number|string} courseId
 * @param {number|string} [_studentId] - 仅为对齐签名，后端忽略（保留以兼容旧调用）
 * @returns {Promise<Object>} 计算后的认知状态
 */
export function computeCognitiveState(courseId, _studentId) {
  return request.post(
    `/cognitive/course/${courseId}/compute`,
  )
}

// ---------------------------------------------------------------------------
// 推荐
// ---------------------------------------------------------------------------

/**
 * 生成学习推荐（基于当前认知状态与策略版本）。
 * POST /cognitive/course/{courseId}/recommend
 *
 * 后端使用 Body 接收 { node_id?, force_recompute? }；
 * 学生 ID 由后端从 JWT 中提取，不接受前端传入。
 *
 * @param {number|string} courseId
 * @param {Object} [payload] - { node_id?, force_recompute? }
 * @returns {Promise<Object>} 推荐对象（含 policy_version/reason_codes/evidence_refs）
 */
export function generateRecommendation(courseId, payload = {}) {
  return request.post(
    `/cognitive/course/${courseId}/recommend`,
    payload,
  )
}

/**
 * 获取当前学生（或课程视角）的推荐列表。
 * GET /cognitive/course/{courseId}/recommendations
 *
 * @param {number|string} courseId
 * @returns {Promise<Object>} { items: [...] }
 */
export function getRecommendations(courseId) {
  return request.get(`/cognitive/course/${courseId}/recommendations`)
}

/**
 * 消费一条推荐（标记为已采用/已忽略）。
 * POST /cognitive/recommendation/{recommendationId}/consume
 *
 * @param {string} recommendationId - 推荐 ID (UUID)
 * @param {Object} [payload] - 可选 { action: 'accepted'|'dismissed', ... }
 * @returns {Promise<Object>} 消费后的状态
 */
export function consumeRecommendation(recommendationId, payload = {}) {
  return request.post(
    `/cognitive/recommendation/${recommendationId}/consume`,
    payload,
  )
}

// ---------------------------------------------------------------------------
// 学习证据（学生视角）
// ---------------------------------------------------------------------------

/**
 * 获取当前学生在课程下的学习证据列表（用于推荐理由回溯）。
 * GET /cognitive/course/{courseId}/evidence
 *
 * @param {number|string} courseId
 * @returns {Promise<Object>} { items: [...] }
 */
export function getLearningEvidence(courseId) {
  return request.get(`/cognitive/course/${courseId}/evidence`)
}

// ---------------------------------------------------------------------------
// 教师锁定/解锁推荐
// ---------------------------------------------------------------------------

/**
 * 教师锁定某条推荐（防止学生消费/忽略，常用于定向干预）。
 * POST /cognitive/recommendation/{recommendationId}/lock
 *
 * 权限：analytics.view_member 或 agent.policy.configure（满足其一即可）。
 *
 * @param {string} recommendationId - 推荐 ID (UUID)
 * @returns {Promise<Object>} 锁定后的状态
 */
export function lockRecommendation(recommendationId) {
  return request.post(
    `/cognitive/recommendation/${recommendationId}/lock`,
  )
}

/**
 * 教师解锁某条推荐。
 * POST /cognitive/recommendation/{recommendationId}/unlock
 *
 * 权限：analytics.view_member 或 agent.policy.configure（满足其一即可）。
 *
 * @param {string} recommendationId - 推荐 ID (UUID)
 * @returns {Promise<Object>} 解锁后的状态
 */
export function unlockRecommendation(recommendationId) {
  return request.post(
    `/cognitive/recommendation/${recommendationId}/unlock`,
  )
}
