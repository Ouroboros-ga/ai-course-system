import request from '@/utils/request.js'

/**
 * 安全围栏与沙箱策略 API（API 契约 §2：safety，状态 available）。
 * 端点前缀：/api/v1/safety
 * 响应经 request.js 统一剥离 code/message。
 *
 * 平台硬边界（宿主隔离、内网保护、资源限制、审计等）不可关闭；
 * 写操作分别需要 agent.policy.configure / sandbox.policy.configure 权限。
 */

/**
 * 课程安全围栏配置（page-design §18.5）。
 * GET /safety/course/{courseId}/safety-policy
 * → { course_type, forbidden_topics, required_citation_topics, keyword_rules, ... }
 */
export function getSafetyPolicy(courseId) {
  return request.get(`/safety/course/${courseId}/safety-policy`)
}

/**
 * 更新课程安全围栏配置（仅提交有变化的字段）。
 * PUT /safety/course/{courseId}/safety-policy
 */
export function updateSafetyPolicy(courseId, payload) {
  return request.put(`/safety/course/${courseId}/safety-policy`, payload)
}

/**
 * 课程沙箱权限配置（page-design §18.6）。
 * GET /safety/course/{courseId}/sandbox-policy
 */
export function getSandboxPolicy(courseId) {
  return request.get(`/safety/course/${courseId}/sandbox-policy`)
}

/**
 * 更新课程沙箱权限配置。
 * PUT /safety/course/{courseId}/sandbox-policy
 */
export function updateSandboxPolicy(courseId, payload) {
  return request.put(`/safety/course/${courseId}/sandbox-policy`, payload)
}

/**
 * 安全审计记录。
 * GET /safety/course/{courseId}/audit
 */
export function getSafetyAudit(courseId, params = {}) {
  return request.get(`/safety/course/${courseId}/audit`, { params })
}
